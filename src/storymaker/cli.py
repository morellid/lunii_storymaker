"""storymaker build | voices | add-voice"""

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from storymaker.elevenlabs import ElevenLabs
from storymaker.pack import Menu, MenuOption, glyph_png, icon_png, write_pack
from storymaker.render import AMBIENCE_LOOP_SECONDS, AudioSource, group_lines, render_scenes, render_spoken, to_mp3
from storymaker.script import Choice, Scene, Script, ScriptError, Sfx, load_script

CACHE_DIR = Path.home() / ".cache" / "lunii-storymaker"
# Rough third-party figures (Nov 2026). ElevenLabs bills in plan credits, so the real cost depends on the plan.
TTS_USD_PER_1K_CHARS = 0.08
SFX_USD_PER_SECOND = 0.002


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="storymaker")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="render a script.json into <its folder>/build/<folder name>.zip")
    build.add_argument("script", type=Path)
    build.add_argument("--dry-run", action="store_true", help="validate and estimate cost, call nothing")
    voices = commands.add_parser("voices", help="search voices in the ElevenLabs library (Italian by default)")
    voices.add_argument("--search")
    voices.add_argument("--language", default="it", help="two-letter code, e.g. en for English-speaking characters")
    add_voice = commands.add_parser("add-voice", help="add a library voice to the account, print its voice_id")
    add_voice.add_argument("public_owner_id")
    add_voice.add_argument("voice_id")
    add_voice.add_argument("name")
    glyph = commands.add_parser("glyph", help="draw 1 to 3 characters as large as a card allows, e.g. a number")
    glyph.add_argument("text")
    glyph.add_argument("out", type=Path)
    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            script = load_script(args.script)
        except ScriptError as error:
            sys.exit(f"{args.script}: {error}")
        print(estimate(script))
        if not args.dry_run:
            print(f"Pack written to {build_pack(script, args.script, _client())}")
    elif args.command == "voices":
        for voice in _client().library_voices(args.search, args.language):
            details = " ".join(str(voice.get(field) or "-") for field in ("accent", "locale", "gender", "age"))
            print(f"{voice['public_owner_id']} {voice['voice_id']}  {voice['name']} | {details} | {voice.get('preview_url')}")
            print(f"    {(voice.get('description') or '')[:160]}")
    elif args.command == "glyph":
        try:
            args.out.write_bytes(glyph_png(args.text))
        except ValueError as error:
            sys.exit(str(error))
    else:
        print(_client().add_voice(args.public_owner_id, args.voice_id, args.name))


def build_pack(script: Script, script_path: Path, client: AudioSource) -> Path:
    slug = script_path.resolve().parent.name
    out_dir = script_path.parent / "build"
    out_dir.mkdir(exist_ok=True)
    narrator = script.voices[script.narrator]

    def render(name: str, scenes: Sequence[Scene]) -> bytes:
        mp3 = to_mp3(render_scenes(scenes, script.voices, client))
        (out_dir / f"{name}.mp3").write_bytes(mp3)  # to listen to before uploading
        return mp3

    def fork(choice: Choice, name: str) -> Menu:
        return Menu(
            to_mp3(render_spoken(choice.question, narrator, client)),
            tuple(
                MenuOption(icon_png(script_path.parent / option.image), to_mp3(render_spoken(option.title, narrator, client)), render(name.format(i + 1), option.scenes))
                for i, option in enumerate(choice.options)
            ),
        )

    menu = fork(script.choice, "{}") if script.choice else None
    parts = _parts(script.scenes)
    flow: list[bytes | Menu] = []
    forks = audio = 0
    for part in parts:
        if isinstance(part, Choice):
            forks += 1
            flow.append(fork(part, f"scelta-{forks}-{{}}"))
        else:
            audio += 1
            flow.append(render(f"parte-{audio}" if len(parts) > 1 else "intro" if menu else "story", part))
    pack_path = out_dir / f"{slug}.zip"
    title_mp3 = to_mp3(render_spoken(script.title, narrator, client))
    write_pack(pack_path, slug, script.title, script.description, icon_png(script_path.parent / script.image), title_mp3, flow, menu)
    return pack_path


def _parts(items: Sequence[Scene | Choice]) -> list[list[Scene] | Choice]:
    """Consecutive scenes become one audio part; each choice is a fork between parts."""
    parts: list[list[Scene] | Choice] = []
    for item in items:
        if isinstance(item, Choice):
            parts.append(item)
        elif parts and isinstance(parts[-1], list):
            parts[-1].append(item)
        else:
            parts.append([item])
    return parts


def estimate(script: Script) -> str:
    scenes = [item for item in script.scenes if isinstance(item, Scene)]
    chars = len(script.title)
    for choice in [item for item in script.scenes if isinstance(item, Choice)] + ([script.choice] if script.choice else []):
        chars += len(choice.question) + sum(len(option.title) for option in choice.options)
        scenes += [scene for option in choice.options for scene in option.scenes]
    sfx_seconds = 0.0
    for scene in scenes:
        for segment in group_lines(scene.cues):
            if isinstance(segment, tuple):
                chars += sum(len(line.text) for line in segment)
            elif isinstance(segment, Sfx):
                sfx_seconds += segment.duration or 5.0
        if scene.ambience:
            sfx_seconds += AMBIENCE_LOOP_SECONDS
    cost = chars / 1000 * TTS_USD_PER_1K_CHARS + sfx_seconds * SFX_USD_PER_SECOND
    minutes = chars / 900  # Italian narration runs at roughly 900 characters a minute
    return (
        f"{chars} characters (~{minutes:.0f} min of speech), {sfx_seconds:.0f}s of effects, uncached. "
        f"Rough cost ${cost:.2f}, could be 2-3x on some plans: check the ElevenLabs usage page after the first build"
    )


def _client() -> ElevenLabs:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY is not set (put it in the repo's .env)")
    return ElevenLabs(api_key, CACHE_DIR)
