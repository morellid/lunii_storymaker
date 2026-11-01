"""Writes a STUdio-format pack (story.json + assets/) that Lunii.QT imports directly.

The pack is one cover node (title image and audio, shown on the Lunii wheel) leading to one story node,
which returns to the cover when it ends.
"""

import hashlib
import io
import json
import textwrap
import uuid
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COVER_SIZE = (320, 240)  # Lunii screen
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/morellid/lunii_storymaker")


def pack_uuid(slug: str) -> uuid.UUID:
    """Stable per story, so a rebuilt pack replaces the old one instead of piling up beside it."""
    return uuid.uuid5(NAMESPACE, slug)


def cover_png(title: str) -> bytes:
    image = Image.new("RGB", COVER_SIZE, (20, 30, 70))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    text = "\n".join(textwrap.wrap(title, width=16))
    draw.multiline_text((COVER_SIZE[0] / 2, COVER_SIZE[1] / 2), text, font=font, fill="white", anchor="mm", align="center", spacing=8)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_pack(
    path: Path, slug: str, title: str, description: str, cover: bytes, title_mp3: bytes, story_mp3: bytes
) -> None:
    assets = {data: f"{hashlib.sha1(data).hexdigest()}.{ext}" for data, ext in ((cover, "png"), (title_mp3, "mp3"), (story_mp3, "mp3"))}
    # Lunii.QT renames each asset to the last 8 characters of its name, so those must not collide.
    if len({name.split(".")[0][-8:] for name in assets.values()}) != len(assets):
        raise ValueError("asset names collide on their last 8 characters")

    cover_id = pack_uuid(slug)  # Lunii.QT takes the first stage node's uuid as the pack uuid
    story_id = uuid.uuid5(cover_id, "story")
    to_story = uuid.uuid5(cover_id, "to-story")
    to_cover = uuid.uuid5(cover_id, "to-cover")
    story_json = {
        "format": "v1",
        "version": 1,
        "title": title,
        "description": description,
        "nightModeAvailable": False,
        "stageNodes": [
            {
                "uuid": str(cover_id),
                "type": "cover",
                "name": title,
                "position": None,
                "image": assets[cover],
                "audio": assets[title_mp3],
                "okTransition": {"actionNode": str(to_story), "optionIndex": 0},
                "homeTransition": None,
                "controlSettings": {"wheel": True, "ok": True, "home": False, "pause": False, "autoplay": False},
                "squareOne": True,
            },
            {
                "uuid": str(story_id),
                "type": "story",
                "name": title,
                "position": None,
                "image": None,
                "audio": assets[story_mp3],
                "okTransition": {"actionNode": str(to_cover), "optionIndex": 0},
                "homeTransition": {"actionNode": str(to_cover), "optionIndex": 0},
                "controlSettings": {"wheel": False, "ok": False, "home": True, "pause": True, "autoplay": True},
            },
        ],
        "actionNodes": [
            {"id": str(to_story), "name": "Story", "position": None, "options": [str(story_id)]},
            {"id": str(to_cover), "name": "Cover", "position": None, "options": [str(cover_id)]},
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("story.json", json.dumps(story_json, ensure_ascii=False, indent=2))
        archive.writestr("thumbnail.png", cover)
        for data, name in assets.items():
            archive.writestr(f"assets/{name}", data)
