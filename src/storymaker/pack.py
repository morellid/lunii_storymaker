"""Writes a STUdio-format pack (story.json + assets/) that Lunii.QT imports directly.

Without a menu: cover -> story -> back to the cover.
With a menu (same node layout as packs made in STUdio): cover -> introduction -> question -> the wheel picks
an option -> its story -> back to the question, so the listener can pick another.
"""

import hashlib
import io
import json
import textwrap
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

COVER_SIZE = (320, 240)  # Lunii screen
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/morellid/lunii_storymaker")

COVER = {"wheel": True, "ok": True, "home": False, "pause": False, "autoplay": False}
STORY = {"wheel": False, "ok": False, "home": True, "pause": True, "autoplay": True}
QUESTION = {"wheel": False, "ok": False, "home": False, "pause": False, "autoplay": True}
OPTION = {"wheel": True, "ok": True, "home": True, "pause": False, "autoplay": False}


@dataclass(frozen=True)
class MenuOption:
    image: bytes
    title_mp3: bytes
    story_mp3: bytes


@dataclass(frozen=True)
class Menu:
    question_mp3: bytes
    options: tuple[MenuOption, ...]


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


def icon_png(path: Path) -> bytes:
    """A light icon centred on black: the Lunii screen is tiny, a silhouette reads where text doesn't."""
    icon = Image.open(path)
    if icon.mode in ("RGBA", "LA", "P"):
        icon = icon.convert("RGBA")
        icon = Image.alpha_composite(Image.new("RGBA", icon.size, "black"), icon)
    icon = icon.convert("L")
    icon.thumbnail((COVER_SIZE[1] - 40, COVER_SIZE[1] - 40))
    image = Image.new("L", COVER_SIZE, 0)
    image.paste(icon, ((COVER_SIZE[0] - icon.width) // 2, (COVER_SIZE[1] - icon.height) // 2))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_pack(
    path: Path,
    slug: str,
    title: str,
    description: str,
    cover: bytes,
    title_mp3: bytes,
    story_mp3: bytes,
    menu: Menu | None = None,
) -> None:
    """story_mp3 is the whole story, or the introduction played before the menu."""
    graph = _Graph(pack_uuid(slug))  # Lunii.QT takes the first stage node's uuid as the pack uuid
    cover_id = graph.stage("cover", "cover", title, cover, title_mp3, COVER, squareOne=True)
    story_id = graph.stage("story", "story", title, None, story_mp3, STORY)
    graph.link(cover_id, [story_id])
    if menu is None:
        graph.link(story_id, [cover_id], home=True)
    else:
        question_id = graph.stage("question", "menu.questionstage", "Question", None, menu.question_mp3, QUESTION)
        graph.link(story_id, [question_id], home=True)
        option_ids = [
            graph.stage(f"option-{i}", "menu.optionstage", f"Option {i + 1}", option.image, option.title_mp3, OPTION)
            for i, option in enumerate(menu.options)
        ]
        graph.link(question_id, option_ids)
        for i, (option_id, option) in enumerate(zip(option_ids, menu.options)):
            branch_id = graph.stage(f"story-{i}", "story", f"Story {i + 1}", None, option.story_mp3, STORY)
            graph.link(option_id, [branch_id])
            graph.link(branch_id, [question_id], home=True)

    # Lunii.QT renames each asset to the last 8 characters of its name, so those must not collide.
    if len({name.split(".")[0][-8:] for name in graph.assets.values()}) != len(graph.assets):
        raise ValueError("asset names collide on their last 8 characters")
    story_json = {
        "format": "v1",
        "version": 1,
        "title": title,
        "description": description,
        "nightModeAvailable": False,
        "stageNodes": list(graph.stages.values()),
        "actionNodes": graph.actions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("story.json", json.dumps(story_json, ensure_ascii=False, indent=2))
        archive.writestr("thumbnail.png", cover)
        for data, name in graph.assets.items():
            archive.writestr(f"assets/{name}", data)


class _Graph:
    def __init__(self, root: uuid.UUID) -> None:
        self.root = root
        self.stages: dict[str, dict[str, Any]] = {}
        self.actions: list[dict[str, Any]] = []
        self.assets: dict[bytes, str] = {}  # content -> file name, so identical audio is stored once

    def stage(
        self, key: str, kind: str, name: str, image: bytes | None, audio: bytes, controls: dict[str, bool], **extra: Any
    ) -> str:
        node_id = str(self.root if not self.stages else uuid.uuid5(self.root, key))
        self.stages[node_id] = {
            "uuid": node_id,
            "type": kind,
            "name": name,
            "position": None,
            "image": self._asset(image, "png") if image else None,
            "audio": self._asset(audio, "mp3"),
            "okTransition": None,
            "homeTransition": None,
            "controlSettings": controls,
            **extra,
        }
        return node_id

    def link(self, source: str, targets: list[str], home: bool = False) -> None:
        """OK (or the end of an autoplayed audio) on source goes to an action node offering targets."""
        action_id = str(uuid.uuid5(self.root, f"{source}->{','.join(targets)}"))
        if all(action["id"] != action_id for action in self.actions):
            self.actions.append({"id": action_id, "name": "Action", "position": None, "options": targets})
        transition = {"actionNode": action_id, "optionIndex": 0}
        self.stages[source]["okTransition"] = transition
        if home:
            self.stages[source]["homeTransition"] = transition

    def _asset(self, data: bytes, ext: str) -> str:
        return self.assets.setdefault(data, f"{hashlib.sha1(data).hexdigest()}.{ext}")
