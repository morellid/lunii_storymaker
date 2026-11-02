"""Minimal ElevenLabs client. Audio responses are cached on disk by request, so rebuilding a story never pays twice."""

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import httpx

API_URL = "https://api.elevenlabs.io/v1"
OUTPUT_FORMAT = "mp3_44100_128"
TTS_MODEL = "eleven_v4"
SFX_MODEL = "eleven_text_to_sound_v2"


class ElevenLabs:
    def __init__(self, api_key: str, cache_dir: Path) -> None:
        self._http = httpx.Client(base_url=API_URL, headers={"xi-api-key": api_key}, timeout=300)
        self._cache_dir = cache_dir

    def dialogue(self, lines: Sequence[tuple[str, str]], take: int = 0, language: str = "it") -> bytes:
        """lines are (voice_id, text) pairs, spoken in order as one performance."""
        body: dict[str, Any] = {
            "model_id": TTS_MODEL,
            "language_code": language,
            "inputs": [{"voice_id": voice_id, "text": text} for voice_id, text in lines],
        }
        if take:
            body["seed"] = take
        return self._audio("/text-to-dialogue", body, take)

    def sound(self, prompt: str, duration: float | None, loop: bool = False, take: int = 0) -> bytes:
        # The Sound Effects API takes no seed: a new take only needs a new cache key, generation varies anyway.
        body = {"model_id": SFX_MODEL, "text": prompt, "duration_seconds": duration, "loop": loop}
        return self._audio("/sound-generation", body, take)

    def library_voices(self, search: str | None, language: str = "it", page_size: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"language": language, "page_size": page_size, "sort": "usage_character_count_1y"}
        if search:
            params["search"] = search
        response = self._http.get("/shared-voices", params=params)
        _raise_for_status(response)
        return response.json()["voices"]

    def add_voice(self, public_owner_id: str, voice_id: str, name: str) -> str:
        """Library voices must be added to the account before the API accepts them. Returns the usable voice_id."""
        response = self._http.post(f"/voices/add/{public_owner_id}/{voice_id}", json={"new_name": name})
        _raise_for_status(response)
        return response.json()["voice_id"]

    def _audio(self, path: str, body: dict[str, Any], take: int) -> bytes:
        key = hashlib.sha256(json.dumps([path, OUTPUT_FORMAT, body, take], sort_keys=True).encode()).hexdigest()
        cached = self._cache_dir / f"{key}.mp3"
        if cached.exists():
            return cached.read_bytes()
        response = self._http.post(path, params={"output_format": OUTPUT_FORMAT}, json=body)
        _raise_for_status(response)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(response.content)
        return response.content


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_error:
        raise RuntimeError(f"ElevenLabs {response.request.url.path} failed ({response.status_code}): {response.text}")
