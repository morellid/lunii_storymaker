"""storymaker build | voices | add-voice"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from storymaker.elevenlabs import ElevenLabs
from storymaker.pack import cover_png, write_pack
from storymaker.render import AMBIENCE_LOOP_SECONDS, group_lines, render_story, render_title, to_mp3
from storymaker.script import Script, ScriptError, Sfx, load_script

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
    voices = commands.add_parser("voices", help="search Italian voices in the ElevenLabs library")
    voices.add_argument("--search")
    add_voice = commands.add_parser("add-voice", help="add a library voice to the account, print its voice_id")
    add_voice.add_argument("public_owner_id")
    add_voice.add_argument("voice_id")
    add_voice.add_argument("name")
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
        for voice in _client().italian_voices(args.search):
            details = " ".join(str(voice.get(field) or "-") for field in ("accent", "locale", "gender", "age"))
            print(f"{voice['public_owner_id']} {voice['voice_id']}  {voice['name']} | {details} | {voice.get('preview_url')}")
            print(f"    {(voice.get('description') or '')[:160]}")
    else:
        print(_client().add_voice(args.public_owner_id, args.voice_id, args.name))


def build_pack(script: Script, script_path: Path, client: ElevenLabs) -> Path:
    slug = script_path.resolve().parent.name
    out_dir = script_path.parent / "build"
    story_mp3 = to_mp3(render_story(script, client))
    out_dir.mkdir(exist_ok=True)
    (out_dir / "story.mp3").write_bytes(story_mp3)  # to listen to before uploading
    pack_path = out_dir / f"{slug}.zip"
    write_pack(pack_path, slug, script.title, script.description, cover_png(script.title), to_mp3(render_title(script, client)), story_mp3)
    return pack_path


def estimate(script: Script) -> str:
    chars = len(script.title)
    sfx_seconds = 0.0
    for scene in script.scenes:
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
