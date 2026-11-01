"""The story script Claude writes, validated before any credits are spent."""

import json
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
class Script:
    title: str
    description: str
    narrator: str  # voice name that reads the title on the Lunii menu
    voices: dict[str, str]  # voice name -> ElevenLabs voice_id
    scenes: tuple[Scene, ...]


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
    scenes = tuple(_parse_scene(raw, f"scenes[{i}]", voices) for i, raw in enumerate(data.get("scenes") or []))
    if not scenes:
        raise ScriptError("'scenes' is empty")
    return Script(title, str(data.get("description", "")), narrator, dict(voices), scenes)


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
            return Line(raw["voice"], text, _take(raw, where))
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
