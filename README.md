# Lunii Story Maker

Turns a story script into a Lunii pack: voices acted by ElevenLabs Eleven v4 (Text to Dialogue), sound effects and looped ambience from the ElevenLabs Sound Effects API, mixed locally, packed in the STUdio format that [Lunii.QT](https://github.com/o-daneel/Lunii.QT) imports.

The script is written by Claude (or by hand). This tool does no writing of its own.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and ffmpeg (`brew install ffmpeg`). Put your API key in `.env` at the repo root:

```
ELEVENLABS_API_KEY=...
```

## Usage

```bash
uv run storymaker voices --search "narratore caldo"       # Italian voices in the ElevenLabs library
uv run storymaker add-voice <public_owner_id> <voice_id> "Nonna"   # library voices must be added before use; prints the voice_id to put in the script
uv run storymaker build path/to/my-story/script.json --dry-run      # validate and estimate cost
uv run storymaker build path/to/my-story/script.json                # writes path/to/my-story/build/my-story.zip and story.mp3
```

Then open Lunii.QT with the Lunii plugged in and drop the zip on it. The pack UUID is derived from the story folder name, so a rebuilt pack has the same UUID: remove the old one from the Lunii before importing the new one.

Every API response is cached in `~/.cache/lunii-storymaker`, keyed by request. Editing one scene and rebuilding only pays for that scene.

## Script format

```json
{
  "title": "Il faro di Nina",
  "description": "Optional, shown in Lunii.QT",
  "narrator": "narratore",
  "voices": {"narratore": "<voice_id>", "nina": "<voice_id>"},
  "scenes": [
    {
      "ambience": {"prompt": "gentle waves on rocks, distant seagulls, steady", "volume_db": -20},
      "cues": [
        {"voice": "narratore", "text": "[calm] C'era una volta un faro, in cima a uno scoglio."},
        {"voice": "nina", "text": "[whispers] Chi c'è?"},
        {"sfx": "old wooden door creaking open slowly", "duration": 2.5},
        {"pause": 1.0}
      ]
    }
  ]
}
```

- `narrator` reads the title on the Lunii menu.
- `voices` maps character names to ElevenLabs voice IDs, at most 10.
- Each cue is exactly one of:
  - `voice` + `text`: a spoken line. Bracketed audio tags (`[whispers]`, `[laughs]`, `[excited]`...) set the delivery and are not read aloud.
  - `sfx` + optional `duration` (0.5 to 30 seconds): a sound effect, levelled just under the dialogue.
  - `pause`: silence, in seconds.
  - Lines and effects take an optional `take` (integer, default 0). The cache returns the same audio for the same request, so bump `take` to get a new rendition of unchanged text.
- Consecutive lines are sent as one dialogue request, so the voices react to each other. A sound effect or a pause starts a new request, as does reaching 2,000 characters (the API limit).
- `choice` (optional) turns the pack into a menu: `scenes` becomes the introduction, then the narrator asks `question` and the Lunii wheel picks one of `options` (`{"title": ..., "scenes": [...]}`, at least 2). Each option shows a card with its title; its story ends back at the question so another can be picked.

  ```json
  "choice": {"question": "Quale traccia vuoi toccare?", "options": [{"title": "La pista nella sabbia", "scenes": [...]}, {"title": "L'orma nel fango", "scenes": [...]}]}
  ```
- `image` (optional, on the script and on each option): a path, relative to `script.json`, to a light icon on a dark or transparent background. It is centred on black and shown instead of the title, which is hard to read on the Lunii screen. Simple filled silhouettes work best, e.g. [game-icons](https://game-icons.net) via `https://api.iconify.design/game-icons/<name>.svg`.
- `ambience` (optional) is a 30-second loop generated once per scene and repeated under it, `volume_db` below the scene's level (default -20).

## Tests

```bash
uv run pytest
```
