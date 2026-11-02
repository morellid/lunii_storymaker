"""Writes a STUdio-format pack (story.json + assets/) that Lunii.QT imports directly.

The story is a flow of parts: audio, or a fork where the wheel picks an option and its branch plays before the
story goes on. Without a menu the flow ends back at the cover. With a menu (same node layout as packs made in
STUdio) it ends at a question -> the wheel picks an option -> its story -> back to the question.
"""

import hashlib
import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

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


def glyph_png(text: str) -> bytes:
    """1 to 3 characters (a number like 10) drawn as large as the card allows: the only text the Lunii screen shows legibly."""
    text = text.strip()
    if not 1 <= len(text) <= 3:
        raise ValueError("a card glyph is 1 to 3 characters: anything longer is unreadable, use an icon")
    image = Image.new("L", COVER_SIZE, 0)
    draw = ImageDraw.Draw(image)
    size = COVER_SIZE[1] * 3  # shrinks until the drawn glyph fits, so small glyphs like + still fill the card
    while True:
        font = ImageFont.load_default(size=size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=size // 20)
        if (right - left <= COVER_SIZE[0] - 20 and bottom - top <= COVER_SIZE[1] - 20) or size <= 20:
            break
        size -= 8
    draw.text((COVER_SIZE[0] / 2, COVER_SIZE[1] / 2), text, font=font, fill=255, anchor="mm", stroke_width=size // 20, stroke_fill=255)
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
    flow: Sequence[bytes | Menu],
    menu: Menu | None = None,
) -> None:
    """flow is the story (or the introduction played before the menu): audio parts, and forks whose branches rejoin it."""
    graph = _Graph(pack_uuid(slug))  # Lunii.QT takes the first stage node's uuid as the pack uuid
    cover_id = graph.stage("cover", "cover", title, cover, title_mp3, COVER, squareOne=True)
    ends = [cover_id]  # stages whose OK, or the end of their audio, goes to what comes next

    def go_on(target: str) -> None:
        for source in ends:  # home leaves the story for the cover, it never skips ahead
            graph.link(source, [target], home_targets=None if source == cover_id else [cover_id])

    for i, part in enumerate(flow):
        if isinstance(part, bytes):
            part_id = graph.stage("story" if i == 0 else f"part-{i}", "story", title, None, part, STORY)
            go_on(part_id)
            ends = [part_id]
            continue
        question_id = graph.stage(f"fork-{i}", "menu.questionstage", "Question", None, part.question_mp3, QUESTION)
        go_on(question_id)
        ends = []
        option_ids = []
        for j, option in enumerate(part.options):
            option_ids.append(graph.stage(f"fork-{i}-option-{j}", "menu.optionstage", f"Option {j + 1}", option.image, option.title_mp3, OPTION))
            ends.append(graph.stage(f"fork-{i}-story-{j}", "story", f"Branch {j + 1}", None, option.story_mp3, STORY))
            graph.link(option_ids[-1], [ends[-1]], home_targets=[cover_id])
        graph.link(question_id, option_ids)
    if menu is None:
        go_on(cover_id)
    else:
        question_id = graph.stage("question", "menu.questionstage", "Question", None, menu.question_mp3, QUESTION)
        go_on(question_id)
        option_ids = [
            graph.stage(f"option-{i}", "menu.optionstage", f"Option {i + 1}", option.image, option.title_mp3, OPTION)
            for i, option in enumerate(menu.options)
        ]
        graph.link(question_id, option_ids)
        for i, (option_id, option) in enumerate(zip(option_ids, menu.options)):
            branch_id = graph.stage(f"story-{i}", "story", f"Story {i + 1}", None, option.story_mp3, STORY)
            graph.link(option_id, [branch_id])
            graph.link(branch_id, [question_id], home_targets=[question_id])

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

    def link(self, source: str, targets: list[str], home_targets: list[str] | None = None) -> None:
        """OK (or the end of an autoplayed audio) on source goes to an action node offering targets; Home, if given,
        to one offering home_targets."""
        self.stages[source]["okTransition"] = self._action(source, targets)
        if home_targets:
            self.stages[source]["homeTransition"] = self._action(source, home_targets)

    def _action(self, source: str, targets: list[str]) -> dict[str, Any]:
        action_id = str(uuid.uuid5(self.root, f"{source}->{','.join(targets)}"))
        if all(action["id"] != action_id for action in self.actions):
            self.actions.append({"id": action_id, "name": "Action", "position": None, "options": targets})
        return {"actionNode": action_id, "optionIndex": 0}

    def _asset(self, data: bytes, ext: str) -> str:
        return self.assets.setdefault(data, f"{hashlib.sha1(data).hexdigest()}.{ext}")
