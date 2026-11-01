"""Turns a Script into one mixed story track: dialogue, sound effects and a looped ambience bed per scene."""

import io
import math
from typing import Protocol, Sequence

from pydub import AudioSegment, effects

from storymaker.script import MAX_DIALOGUE_CHARS, Cue, Line, Pause, Scene, Script, Sfx

GAP_MS = 350  # breath between consecutive segments
SCENE_GAP_MS = 800
AMBIENCE_LEAD_MS = 1500  # ambience starts before the first word and lingers after the last
AMBIENCE_LOOP_SECONDS = 30.0
SFX_DB = -3.0  # effects sit slightly under the dialogue level, so nothing startles at bedtime
PEAK_CEILING_DB = -1.0  # levelling never pushes a peak past this, so quiet transients aren't boosted into clipping
LOOP_CROSSFADE_MS = 50  # hides the MP3 padding at each ambience loop seam


class AudioSource(Protocol):
    def dialogue(self, lines: Sequence[tuple[str, str]], take: int = 0) -> bytes: ...

    def sound(self, prompt: str, duration: float | None, loop: bool = False, take: int = 0) -> bytes: ...


Segment = tuple[Line, ...] | Sfx | Pause


def group_lines(cues: Sequence[Cue]) -> list[Segment]:
    """Consecutive lines become one dialogue request (so voices react to each other), split at the API size limit."""
    segments: list[Segment] = []
    chunk: list[Line] = []
    for cue in cues:
        if isinstance(cue, Line):
            if chunk and sum(len(line.text) for line in chunk) + len(cue.text) > MAX_DIALOGUE_CHARS:
                segments.append(tuple(chunk))
                chunk = []
            chunk.append(cue)
            continue
        if chunk:
            segments.append(tuple(chunk))
            chunk = []
        segments.append(cue)
    if chunk:
        segments.append(tuple(chunk))
    return segments


def render_title(script: Script, source: AudioSource) -> AudioSegment:
    return _finish(_decode(source.dialogue([(script.voices[script.narrator], script.title)])))


def render_story(script: Script, source: AudioSource) -> AudioSegment:
    story = AudioSegment.silent(0)
    for scene in script.scenes:
        if len(story):
            story += AudioSegment.silent(SCENE_GAP_MS)
        story += render_scene(scene, script.voices, source)
    return _finish(story)


def render_scene(scene: Scene, voices: dict[str, str], source: AudioSource) -> AudioSegment:
    parts: list[tuple[Segment, AudioSegment]] = []
    for segment in group_lines(scene.cues):
        if isinstance(segment, tuple):
            take = max(line.take for line in segment)
            audio = _decode(source.dialogue([(voices[line.voice], line.text) for line in segment], take))
        elif isinstance(segment, Sfx):
            audio = _decode(source.sound(segment.prompt, segment.duration, take=segment.take))
        else:
            audio = AudioSegment.silent(int(segment.seconds * 1000))
        parts.append((segment, audio))

    dialogue = [audio for segment, audio in parts if isinstance(segment, tuple)]
    reference_db = sum(audio.dBFS for audio in dialogue) / len(dialogue) if dialogue else -20.0

    track = AudioSegment.silent(0)
    for segment, audio in parts:
        if isinstance(segment, Sfx):
            audio = _level(audio, reference_db + SFX_DB)
        if len(track):
            track += AudioSegment.silent(GAP_MS)
        track += audio

    if scene.ambience is None:
        return track
    track = AudioSegment.silent(AMBIENCE_LEAD_MS) + track + AudioSegment.silent(AMBIENCE_LEAD_MS)
    loop = _decode(source.sound(scene.ambience.prompt, AMBIENCE_LOOP_SECONDS, loop=True))
    bed = loop
    while len(bed) < len(track):
        bed = bed.append(loop, crossfade=min(LOOP_CROSSFADE_MS, len(loop)))
    bed = bed[: len(track)]
    bed = _level(bed, reference_db + scene.ambience.volume_db).fade_in(AMBIENCE_LEAD_MS).fade_out(AMBIENCE_LEAD_MS)
    return track.overlay(bed)


def to_mp3(audio: AudioSegment) -> bytes:
    buffer = io.BytesIO()
    audio.export(buffer, format="mp3", bitrate="128k")
    return buffer.getvalue()


def _decode(data: bytes) -> AudioSegment:
    return AudioSegment.from_file(io.BytesIO(data), format="mp3")


def _level(audio: AudioSegment, target_db: float) -> AudioSegment:
    if audio.dBFS == -math.inf:
        return audio
    return audio.apply_gain(min(target_db - audio.dBFS, PEAK_CEILING_DB - audio.max_dBFS))


def _finish(audio: AudioSegment) -> AudioSegment:
    # Mono 44.1 kHz MP3 is what the Lunii plays; Lunii.QT then imports it without transcoding.
    return effects.normalize(audio.set_channels(1).set_frame_rate(44100), headroom=1.0)
