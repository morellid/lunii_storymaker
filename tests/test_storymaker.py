import io
import json
import zipfile
from pathlib import Path
from typing import Any, Sequence

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from storymaker.cli import build_pack, main
from storymaker.pack import Menu, MenuOption, glyph_png, pack_uuid, write_pack
from storymaker.render import group_lines, render_scene, render_scenes, to_mp3
from storymaker.script import Choice, Line, Pause, ScriptError, Sfx, load_script, parse_script


def script_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": "Il faro di Nina",
        "image": "icon.png",
        "narrator": "narratore",
        "voices": {"narratore": "v-narr", "nina": "v-nina"},
        "scenes": [
            {
                "ambience": {"prompt": "onde sugli scogli"},
                "cues": [
                    {"voice": "narratore", "text": "[calm] C'era una volta un faro."},
                    {"voice": "nina", "text": "[whispers] Chi c'è?"},
                    {"sfx": "porta di legno che cigola", "duration": 2},
                    {"pause": 0.5},
                    {"voice": "narratore", "text": "Era il vento."},
                ],
            }
        ],
    }
    data.update(overrides)
    return data


class FakeSource:
    """Stands in for ElevenLabs: tones instead of speech, records every request."""

    def __init__(self, sfx_volume_db: float = -20.0) -> None:
        self.dialogue_calls: list[list[tuple[str, str]]] = []
        self.sound_calls: list[tuple[str, float | None, bool]] = []
        self.takes: list[int] = []
        self.languages: list[str] = []
        self.sfx_volume_db = sfx_volume_db

    def dialogue(self, lines: Sequence[tuple[str, str]], take: int = 0, language: str = "it") -> bytes:
        self.dialogue_calls.append(list(lines))
        self.takes.append(take)
        self.languages.append(language)
        return to_mp3(Sine(220).to_audio_segment(duration=800, volume=-20))

    def sound(self, prompt: str, duration: float | None, loop: bool = False, take: int = 0) -> bytes:
        self.sound_calls.append((prompt, duration, loop))
        return to_mp3(Sine(880).to_audio_segment(duration=int((duration or 1) * 1000), volume=self.sfx_volume_db))


def test_parse_valid_script() -> None:
    script = parse_script(script_data())
    assert script.scenes[0].cues[2] == Sfx("porta di legno che cigola", 2)
    assert script.scenes[0].ambience is not None and script.scenes[0].ambience.volume_db == -20.0


@pytest.mark.parametrize(
    "scenes, message",
    [
        ([{"cues": [{"voice": "lupo", "text": "Ciao"}]}], "unknown voice"),
        ([{"cues": [{"voice": "nina", "text": "Ciao", "sfx": "tuono"}]}], "exactly one"),
        ([{"cues": [{"sfx": "tuono", "duration": 45}]}], "between"),
        ([{"cues": []}], "no cues"),
        ([{"ambience": {}, "cues": [{"pause": 1}]}], "prompt"),
    ],
)
def test_parse_rejects_bad_cues(scenes: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ScriptError, match=message):
        parse_script(script_data(scenes=scenes))


def test_parse_rejects_unknown_narrator() -> None:
    with pytest.raises(ScriptError, match="narrator"):
        parse_script(script_data(narrator="lupo"))


def test_group_lines_keeps_dialogue_together_and_splits_at_limit() -> None:
    long = Line("a", "x" * 1200)
    segments = group_lines([Line("a", "uno"), Line("b", "due"), Sfx("tuono"), long, long, Pause(1)])
    assert segments == [(Line("a", "uno"), Line("b", "due")), Sfx("tuono"), (long,), (long,), Pause(1)]


def test_render_scene_requests_dialogue_sfx_and_looped_ambience() -> None:
    script = parse_script(script_data())
    source = FakeSource()
    render_scene(script.scenes[0], script.voices, source)
    assert source.dialogue_calls == [
        [("v-narr", "[calm] C'era una volta un faro."), ("v-nina", "[whispers] Chi c'è?")],
        [("v-narr", "Era il vento.")],
    ]
    assert source.sound_calls == [("porta di legno che cigola", 2, False), ("onde sugli scogli", 30.0, True)]


def test_loud_sfx_is_brought_down_to_dialogue_level() -> None:
    data = script_data(scenes=[{"cues": [{"voice": "nina", "text": "Ciao"}, {"sfx": "tuono", "duration": 1}]}])
    script = parse_script(data)
    track = render_scene(script.scenes[0], script.voices, FakeSource(sfx_volume_db=0))
    dialogue, sfx = track[:800], track[-1000:]
    assert sfx.dBFS < dialogue.dBFS


class QuietBellSource(FakeSource):
    """A short loud strike followed by a long near-silent tail: low average loudness, high peak."""

    def sound(self, prompt: str, duration: float | None, loop: bool = False, take: int = 0) -> bytes:
        self.sound_calls.append((prompt, duration, loop))
        strike = Sine(880).to_audio_segment(duration=50, volume=-3)
        return to_mp3(strike + AudioSegment.silent(2450))


def test_quiet_sfx_is_not_boosted_into_clipping() -> None:
    data = script_data(scenes=[{"cues": [{"voice": "nina", "text": "Ciao"}, {"sfx": "campanella", "duration": 2.5}]}])
    script = parse_script(data)
    track = render_scene(script.scenes[0], script.voices, QuietBellSource())
    assert track[-2500:].max_dBFS <= -1.0


def test_take_changes_the_request_so_a_line_can_be_regenerated() -> None:
    lines = [{"voice": "nina", "text": "Ciao"}, {"voice": "nina", "text": "Ciao", "take": 2}]
    calls = []
    for line in lines:
        source = FakeSource()
        script = parse_script(script_data(scenes=[{"cues": [line]}]))
        render_scene(script.scenes[0], script.voices, source)
        calls.append(source.takes)
    assert calls == [[0], [2]]


@pytest.mark.parametrize("cue", [{"pause": "lungo"}, {"pause": -1}, {"sfx": "tuono", "duration": "due"}])
def test_parse_rejects_bad_numbers(cue: dict[str, Any]) -> None:
    with pytest.raises(ScriptError):
        parse_script(script_data(scenes=[{"cues": [cue]}]))


def test_render_scenes_is_mono_44k() -> None:
    script = parse_script(script_data())
    story = render_scenes(script.scenes, script.voices, FakeSource())
    assert (story.channels, story.frame_rate) == (1, 44100)


BRANCH = [{"cues": [{"voice": "nina", "text": "Eccomi!"}]}]


def choice_data(*titles: str) -> dict[str, Any]:
    return {"question": "Quale traccia vuoi toccare?", "options": [{"title": t, "image": "icon.png", "scenes": BRANCH} for t in titles]}


def menu_data() -> dict[str, Any]:
    return script_data(choice=choice_data("La pista", "L'orma"))


def inline_data() -> dict[str, Any]:
    scene = {"cues": [{"voice": "narratore", "text": "Poi..."}]}
    return script_data(scenes=[scene, {"choice": choice_data("Dieci", "Quindici")}, scene])


def story_dir(tmp_path: Path, name: str) -> Path:
    """A story folder with the icon the fixtures point at; returns the script path."""
    from PIL import Image

    (tmp_path / name).mkdir()
    Image.new("L", (100, 100), 255).save(tmp_path / name / "icon.png")
    return tmp_path / name / "script.json"


def png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("L", (320, 240), 0).save(buffer, format="PNG")
    return buffer.getvalue()


def test_parse_choice() -> None:
    script = parse_script(menu_data())
    assert script.choice is not None
    assert [option.title for option in script.choice.options] == ["La pista", "L'orma"]


def test_parse_rejects_choice_with_one_option() -> None:
    data = menu_data()
    data["choice"]["options"] = data["choice"]["options"][:1]
    with pytest.raises(ScriptError, match="at least 2"):
        parse_script(data)


def read_pack(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, list[str]], set[str]]:
    with zipfile.ZipFile(path) as archive:
        story = json.loads(archive.read("story.json"))
        names = set(archive.namelist())
    stages = {node["uuid"]: node for node in story["stageNodes"]}
    actions = {node["id"]: node["options"] for node in story["actionNodes"]}
    for node in stages.values():
        for transition in (node["okTransition"], node["homeTransition"]):
            assert transition is None or set(actions[transition["actionNode"]]) <= set(stages)
        for asset in (node["image"], node["audio"]):
            assert asset is None or f"assets/{asset}" in names
    return story, stages, actions, names


def next_stages(node: dict[str, Any], actions: dict[str, list[str]]) -> list[str]:
    return actions[node["okTransition"]["actionNode"]]


def tone(hz: int) -> bytes:
    return to_mp3(Sine(hz).to_audio_segment(duration=300))


def test_single_story_pack_goes_cover_story_cover(tmp_path: Path) -> None:
    path = tmp_path / "faro.zip"
    write_pack(path, "faro", "Il faro", "", png(), tone(300), (tone(400),))
    story, stages, actions, names = read_pack(path)
    cover = story["stageNodes"][0]
    assert cover["type"] == "cover" and cover["uuid"] == str(pack_uuid("faro"))
    [story_id] = next_stages(cover, actions)
    assert next_stages(stages[story_id], actions) == [cover["uuid"]]
    assert "thumbnail.png" in names


def test_menu_pack_returns_to_the_question_after_each_branch(tmp_path: Path) -> None:
    path = tmp_path / "tracce.zip"
    options = tuple(MenuOption(png(), tone(500 + i), tone(600 + i)) for i in range(3))
    write_pack(path, "tracce", "Le tracce", "", png(), tone(300), (tone(400),), Menu(tone(450), options))
    story, stages, actions, _ = read_pack(path)

    [intro_id] = next_stages(story["stageNodes"][0], actions)
    [question_id] = next_stages(stages[intro_id], actions)
    option_ids = next_stages(stages[question_id], actions)
    assert [stages[option_id]["type"] for option_id in option_ids] == ["menu.optionstage"] * 3
    branches = [next_stages(stages[option_id], actions)[0] for option_id in option_ids]
    assert len({stages[branch]["audio"] for branch in branches}) == 3
    for branch in branches:
        assert next_stages(stages[branch], actions) == [question_id]
        assert stages[branch]["homeTransition"] == stages[branch]["okTransition"]


def test_build_pack_with_choice_writes_zip_and_branch_mp3s(tmp_path: Path) -> None:
    script_path = story_dir(tmp_path, "tracce")
    pack = build_pack(parse_script(menu_data()), script_path, FakeSource())
    assert pack == tmp_path / "tracce" / "build" / "tracce.zip"
    assert {p.name for p in pack.parent.glob("*.mp3")} == {"intro.mp3", "1.mp3", "2.mp3"}


def test_build_pack_uses_icons_instead_of_text_cards(tmp_path: Path) -> None:
    from PIL import Image

    pack = build_pack(parse_script(menu_data()), story_dir(tmp_path, "tracce"), FakeSource())

    story, stages, _, _ = read_pack(pack)
    with zipfile.ZipFile(pack) as archive:
        cards = [archive.read("thumbnail.png")] + [
            archive.read(f"assets/{node['image']}") for node in stages.values() if node["type"] in ("cover", "menu.optionstage")
        ]
    assert len(cards) == 4
    for card in cards:
        image = Image.open(io.BytesIO(card)).convert("L")
        assert image.size == (320, 240)
        assert image.getpixel((5, 5)) == 0 and image.getpixel((160, 120)) == 255


def test_parse_rejects_missing_image_path() -> None:
    data = menu_data()
    data["image"] = 3
    with pytest.raises(ScriptError, match="image"):
        parse_script(data)


def test_cards_need_an_icon_text_is_unreadable_on_the_lunii() -> None:
    data = script_data()
    del data["image"]
    with pytest.raises(ScriptError, match="image"):
        parse_script(data)
    data = menu_data()
    del data["choice"]["options"][1]["image"]
    with pytest.raises(ScriptError, match="image"):
        parse_script(data)


def test_glyph_is_huge_and_at_most_three_characters() -> None:
    from PIL import Image

    image = Image.open(io.BytesIO(glyph_png("10"))).convert("L")
    assert image.size == (320, 240)
    left, top, right, bottom = image.point(lambda v: 255 if v > 128 else 0).getbbox()
    assert bottom - top > 150
    plus = Image.open(io.BytesIO(glyph_png("+"))).convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
    assert plus[3] - plus[1] > 150
    with pytest.raises(ValueError):
        glyph_png("dieci")


def test_dry_run_estimates_without_calling_the_api(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script_path = story_dir(tmp_path, "faro")
    script_path.write_text(json.dumps(script_data()), encoding="utf-8")
    main(["build", str(script_path), "--dry-run"])
    assert "characters" in capsys.readouterr().out
    assert not (script_path.parent / "build").exists()


def test_a_language_change_starts_a_new_request_in_that_language() -> None:
    cues = [
        {"voice": "narratore", "text": "Il mostro disse:"},
        {"voice": "nina", "text": "Hello! My name is Nina.", "lang": "en"},
        {"voice": "nina", "text": "I am thirteen.", "lang": "en"},
        {"voice": "narratore", "text": "Ciao, mi chiamo Nina."},
    ]
    source = FakeSource()
    script = parse_script(script_data(scenes=[{"cues": cues}]))
    render_scene(script.scenes[0], script.voices, source)
    assert [len(call) for call in source.dialogue_calls] == [1, 2, 1]
    assert source.languages == ["it", "en", "it"]


def test_parse_rejects_a_bad_language() -> None:
    with pytest.raises(ScriptError, match="lang"):
        parse_script(script_data(scenes=[{"cues": [{"voice": "nina", "text": "Hi", "lang": "english"}]}]))


def test_parse_choice_inside_the_story() -> None:
    script = parse_script(inline_data())
    assert isinstance(script.scenes[1], Choice) and [o.title for o in script.scenes[1].options] == ["Dieci", "Quindici"]


def test_parse_rejects_a_choice_inside_a_branch() -> None:
    data = inline_data()
    data["scenes"][1]["choice"]["options"][0]["scenes"] = [{"choice": choice_data("A", "B")}]
    with pytest.raises(ScriptError, match="inside a branch"):
        parse_script(data)


def test_branches_of_a_choice_inside_the_story_rejoin_it(tmp_path: Path) -> None:
    path = tmp_path / "gara.zip"
    fork = Menu(tone(450), tuple(MenuOption(png(), tone(500 + i), tone(600 + i)) for i in range(2)))
    write_pack(path, "gara", "La gara", "", png(), tone(300), (tone(400), fork, tone(700)))
    story, stages, actions, _ = read_pack(path)
    cover = story["stageNodes"][0]

    [first_id] = next_stages(cover, actions)
    [question_id] = next_stages(stages[first_id], actions)
    option_ids = next_stages(stages[question_id], actions)
    branches = [next_stages(stages[option_id], actions)[0] for option_id in option_ids]
    assert len({stages[branch]["audio"] for branch in branches}) == 2
    [after_id] = {next_stages(stages[branch], actions)[0] for branch in branches}
    assert stages[after_id]["audio"] != stages[first_id]["audio"]
    assert next_stages(stages[after_id], actions) == [cover["uuid"]]
    for node_id in [first_id, *branches, after_id]:  # home leaves the story, it does not skip ahead
        assert actions[stages[node_id]["homeTransition"]["actionNode"]] == [cover["uuid"]]


def test_build_pack_with_a_choice_inside_writes_each_part(tmp_path: Path) -> None:
    pack = build_pack(parse_script(inline_data()), story_dir(tmp_path, "gara"), FakeSource())
    assert {p.name for p in pack.parent.glob("*.mp3")} == {"parte-1.mp3", "scelta-1-1.mp3", "scelta-1-2.mp3", "parte-2.mp3"}


def test_dry_run_counts_the_branches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script_path = story_dir(tmp_path, "gara")
    script_path.write_text(json.dumps(inline_data()), encoding="utf-8")
    main(["build", str(script_path), "--dry-run"])
    with_choice = capsys.readouterr().out
    script_path.write_text(json.dumps(script_data()), encoding="utf-8")
    main(["build", str(script_path), "--dry-run"])
    assert int(with_choice.split()[0]) > int(capsys.readouterr().out.split()[0])


def test_a_missing_icon_fails_before_anything_is_rendered(tmp_path: Path) -> None:
    script_path = story_dir(tmp_path, "gara")
    data = inline_data()
    data["scenes"][1]["choice"]["options"][1]["image"] = "manca.png"
    script_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ScriptError, match="manca.png"):
        load_script(script_path)


def test_parse_rejects_a_choice_with_cues() -> None:
    data = inline_data()
    data["scenes"][1]["cues"] = [{"pause": 1}]
    with pytest.raises(ScriptError, match="either"):
        parse_script(data)


def test_home_on_a_fork_card_goes_to_the_cover(tmp_path: Path) -> None:
    path = tmp_path / "gara.zip"
    fork = Menu(tone(450), tuple(MenuOption(png(), tone(500 + i), tone(600 + i)) for i in range(2)))
    write_pack(path, "gara", "La gara", "", png(), tone(300), (tone(400), fork, tone(700)))
    story, stages, actions, _ = read_pack(path)
    cards = [node for node in stages.values() if node["type"] == "menu.optionstage"]
    assert len(cards) == 2
    for card in cards:
        assert actions[card["homeTransition"]["actionNode"]] == [story["stageNodes"][0]["uuid"]]


class QuietVoiceSource(FakeSource):
    """One voice comes back from the API 12 dB quieter than the other, as Kina does next to Lance Blackwood."""

    def dialogue(self, lines: Sequence[tuple[str, str]], take: int = 0, language: str = "it") -> bytes:
        super().dialogue(lines, take, language)
        volume = -32 if lines[0][0] == "v-nina" else -20
        return to_mp3(Sine(220).to_audio_segment(duration=800, volume=volume))


def test_a_quiet_voice_is_brought_close_to_the_others() -> None:
    cues = [{"voice": "narratore", "text": "Ciao"}, {"pause": 1}, {"voice": "nina", "text": "Ciao"}]
    script = parse_script(script_data(scenes=[{"cues": cues}]))
    track = render_scene(script.scenes[0], script.voices, QuietVoiceSource())
    loud, quiet = track[:800], track[-800:]
    assert loud.dBFS - quiet.dBFS < 4  # was 12; a little difference is left, so a whisper stays a whisper
    assert loud.dBFS - quiet.dBFS > 1
