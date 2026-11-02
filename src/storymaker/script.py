"""The story script Claude writes, validated before any credits are spent."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_DIALOGUE_CHARS = 2000  # Text to Dialogue limit per request
MAX_VOICES = 10  # Text to Dialogue limit of distinct voices per request
SFX_SECONDS = (0.5, 30.0)  # Sound Effects API duration range


class ScriptError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    voice: str
    text: str
    take: int = 0  # bump to regenerate a line whose text is unchanged
    lang: str = "it"  # ISO 639-1 code the line is spoken in


@dataclass(frozen=True)
class Sfx:
    prompt: str
    duration: float | None = None
    take: int = 0


@dataclass(frozen=True)
class Pause:
    seconds: float


Cue = Line | Sfx | Pause


@dataclass(frozen=True)
class Ambience:
    prompt: str
    volume_db: float = -20.0  # relative to the scene's loudness


@dataclass(frozen=True)
class Scene:
    cues: tuple[Cue, ...]
    ambience: Ambience | None = None


@dataclass(frozen=True)
class Option:
    title: str
    scenes: tuple[Scene, ...]
    image: str | None = None  # icon path relative to script.json; without it the card shows the title


@dataclass(frozen=True)
class Choice:
    question: str  # read by the narrator, then the wheel picks an option
    options: tuple[Option, ...]


@dataclass(frozen=True)
class Script:
    title: str
    description: str
    narrator: str  # voice name that reads the titles and the question
    voices: dict[str, str]  # voice name -> ElevenLabs voice_id
    scenes: tuple[Scene, ...]  # the whole story, or the introduction when there is a choice
    choice: Choice | None = None
    image: str | None = None  # cover icon, as Option.image


def load_script(path: Path) -> Script:
    return parse_script(json.loads(path.read_text(encoding="utf-8")))


def parse_script(data: dict[str, Any]) -> Script:
    title = str(data.get("title", "")).strip()
    if not title:
        raise ScriptError("'title' is required")
    voices = data.get("voices") or {}
    if not voices:
        raise ScriptError("'voices' must map at least one name to a voice_id")
    if len(set(voices.values())) > MAX_VOICES:
        raise ScriptError(f"at most {MAX_VOICES} distinct voices per story")
    narrator = data.get("narrator")
    if narrator not in voices:
        raise ScriptError(f"narrator {narrator!r} is not in 'voices'")
    scenes = _parse_scenes(data.get("scenes"), "scenes", voices)
    choice = _parse_choice(data["choice"], voices) if "choice" in data else None
    return Script(title, str(data.get("description", "")), narrator, dict(voices), scenes, choice, _image(data, "image"))


def _image(raw: dict[str, Any], where: str) -> str | None:
    image = raw.get("image")
    if image is not None and (not isinstance(image, str) or not image.strip()):
        raise ScriptError(f"{where} must be a path to an image file")
    return image


def _parse_choice(raw: dict[str, Any], voices: dict[str, str]) -> Choice:
    question = str(raw.get("question", "")).strip()
    if not question:
        raise ScriptError("choice needs a 'question'")
    options = []
    for i, option in enumerate(raw.get("options") or []):
        title = str(option.get("title", "")).strip()
        if not title:
            raise ScriptError(f"choice.options[{i}] needs a 'title'")
        scenes = _parse_scenes(option.get("scenes"), f"choice.options[{i}].scenes", voices)
        options.append(Option(title, scenes, _image(option, f"choice.options[{i}].image")))
    if len(options) < 2:
        raise ScriptError("choice needs at least 2 options")
    return Choice(question, tuple(options))


def _parse_scenes(raw: list[dict[str, Any]] | None, where: str, voices: dict[str, str]) -> tuple[Scene, ...]:
    scenes = tuple(_parse_scene(scene, f"{where}[{i}]", voices) for i, scene in enumerate(raw or []))
    if not scenes:
        raise ScriptError(f"'{where}' is empty")
    return scenes


def _parse_scene(raw: dict[str, Any], where: str, voices: dict[str, str]) -> Scene:
    cues = tuple(_parse_cue(cue, f"{where}.cues[{j}]", voices) for j, cue in enumerate(raw.get("cues") or []))
    if not cues:
        raise ScriptError(f"{where} has no cues")
    ambience = raw.get("ambience")
    if ambience is None:
        return Scene(cues)
    if not ambience.get("prompt"):
        raise ScriptError(f"{where}.ambience needs a 'prompt'")
    return Scene(cues, Ambience(ambience["prompt"], float(ambience.get("volume_db", -20.0))))


def _parse_cue(raw: dict[str, Any], where: str, voices: dict[str, str]) -> Cue:
    kinds = [kind for kind in ("voice", "sfx", "pause") if kind in raw]
    if len(kinds) != 1:
        raise ScriptError(f"{where} needs exactly one of 'voice', 'sfx', 'pause'")
    match kinds[0]:
        case "voice":
            if raw["voice"] not in voices:
                raise ScriptError(f"{where} uses unknown voice {raw['voice']!r}")
            text = str(raw.get("text", "")).strip()
            if not text:
                raise ScriptError(f"{where} has no 'text'")
            if len(text) > MAX_DIALOGUE_CHARS:
                raise ScriptError(f"{where} is longer than {MAX_DIALOGUE_CHARS} characters, split it")
            lang = raw.get("lang", "it")
            if not isinstance(lang, str) or not re.fullmatch(r"[a-z]{2}", lang):
                raise ScriptError(f"{where} lang must be a two-letter language code like 'en'")
            return Line(raw["voice"], text, _take(raw, where), lang)
        case "sfx":
            duration = raw.get("duration")
            if duration is not None and not SFX_SECONDS[0] <= _number(duration, where) <= SFX_SECONDS[1]:
                raise ScriptError(f"{where} duration must be between {SFX_SECONDS[0]} and {SFX_SECONDS[1]} seconds")
            return Sfx(raw["sfx"], duration, _take(raw, where))
        case _:
            seconds = _number(raw["pause"], where)
            if seconds <= 0:
                raise ScriptError(f"{where} pause must be positive")
            return Pause(seconds)


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScriptError(f"{where} expects a number, got {value!r}")
    return float(value)


def _take(raw: dict[str, Any], where: str) -> int:
    take = raw.get("take", 0)
    if not isinstance(take, int) or take < 0:
        raise ScriptError(f"{where} take must be a non-negative integer")
    return take
