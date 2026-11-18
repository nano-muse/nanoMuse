"""Pictures in the conversation.

A user message may carry images (``Message.images``: absolute paths of files in the
workspace). Providers turn them into image content when the model can take images and
drop them — telling the model what it is missing — when it cannot (``llm.vision``).

Phone photos are 3–12 MB and the whole conversation is sent again on every step of a
tool loop, so images are scaled down before they are encoded: the longest side to 1568
px (what vision models resize to anyway) as JPEG, and the result is cached per file.
"""

from __future__ import annotations

import base64
import io
import mimetypes
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from nanomuse.logger import logger
from nanomuse.schema import Message, Role
from nanomuse.workspaces import open_file

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MAX_SIDE = 1568
# at most this many pixels after scaling (C9): a 4K screenshot is 8 Mpx and 3–8 MB as PNG;
# at 2 Mpx and JPEG 85 it is a few hundred KB and still readable for a hands model
MAX_PIXELS = 2_000_000
MAX_BYTES = 4 * 1024 * 1024  # an image that is still bigger than this after scaling is left out
REMOVED_NOTE = " (screenshot removed to keep the request small)"
_NO_IMAGES_RE = re.compile(
    r"image|vision|multimodal|multi-modal|image_url|input_image|content type|content must be a string|"
    r"invalid type for 'messages\[\d+\]\.content'|unsupported content|expected a string|"
    r"does not support|not supported",
    re.IGNORECASE,
)


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def says_no_images(message: str) -> bool:
    """Does a 400 read like the endpoint refusing image content?"""
    return bool(_NO_IMAGES_RE.search(message or ""))


def model_takes_images(model: str) -> bool | None:
    """What the model's id says about pictures, before the first request (contract C4).

    DeepSeek's models are text-only unless the id says ``v4.1``, ``vision`` or ``ocr``, or
    names the Flash line (``deepseek-flash`` and ``deepseek-v4-flash*`` are served by
    DeepSeek-V4.1-Flash, which takes pictures; ``deepseek-chat`` and ``deepseek-v4-pro``
    do not). Qwen's ``*-vl`` models and the ``qwen3.8`` family take pictures. Anything
    else is ``None``: unknown, so ``llm.vision = "auto"`` finds out from the endpoint's
    answer, as before.
    """
    name = (model or "").lower().rsplit("/", 1)[-1].strip()
    if not name:
        return None
    if name.startswith("deepseek") or "/deepseek" in (model or "").lower():
        if name in ("deepseek-flash",) or name.startswith("deepseek-v4-flash"):
            return True
        return any(mark in name for mark in ("v4.1", "vision", "ocr"))
    if name.startswith("qwen"):
        if "-vl" in name or name.startswith("qwen3.8"):
            return True
        return None
    return None


@lru_cache(maxsize=64)
def _encoded(path: str, mtime_ns: int, size: int) -> tuple[str, str] | None:
    """(media type, base64) for the image at ``path``, scaled down — cached by file state."""
    target = Path(path).absolute()
    try:
        if target.resolve() != target:
            return None
        with open_file(Path(target.anchor), target, "rb") as stream:
            data = stream.read()
    except OSError:
        return None
    media = mimetypes.guess_type(path)[0] or "image/jpeg"
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as opened:
            im: Image.Image = ImageOps.exif_transpose(opened)  # phones store the rotation as a tag
            w, h = im.size
            animated = getattr(opened, "is_animated", False)
            if (
                max(w, h) > MAX_SIDE
                or w * h > MAX_PIXELS
                or len(data) > 1024 * 1024
                or (media == "image/gif" and not animated)
            ):
                scale = min(1.0, MAX_SIDE / max(w, h), (MAX_PIXELS / (w * h)) ** 0.5)
                if scale < 1.0:
                    im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))))
                if media == "image/png" and im.mode in ("RGBA", "LA", "P") and _has_alpha(im):
                    out = io.BytesIO()
                    im.save(out, format="PNG", optimize=True)
                    data, media = out.getvalue(), "image/png"
                else:
                    out = io.BytesIO()
                    im.convert("RGB").save(out, format="JPEG", quality=85, optimize=True)
                    data, media = out.getvalue(), "image/jpeg"
    except Exception as exc:  # noqa: BLE001 — a picture we cannot decode goes as it is
        logger.debug("image {} not scaled ({}); sent as is", path, exc)
    if len(data) > MAX_BYTES:
        return None
    return media, base64.b64encode(data).decode("ascii")


def _has_alpha(im: Any) -> bool:
    try:
        if im.mode == "P":
            return "transparency" in im.info
        low = im.getchannel("A").getextrema()[0]
        return bool(low < 255)
    except Exception:  # noqa: BLE001
        return False


def image_data_url(path: str) -> str | None:
    """A ``data:`` URL for the image, or None when the file is gone or too big."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    encoded = _encoded(path, st.st_mtime_ns, st.st_size)
    if encoded is None:
        return None
    media, b64 = encoded
    return f"data:{media};base64,{b64}"


def has_images(messages: list[Message]) -> bool:
    return any(m.role == Role.USER and m.images for m in messages)


def missing_note(names: list[str]) -> str:
    """What a model that cannot take images is told instead of the picture."""
    shown = ", ".join(names[:5]) + (" …" if len(names) > 5 else "")
    return (
        f"\n\n[{len(names)} attached image{'s' if len(names) != 1 else ''} ({shown}) cannot "
        "be shown to you: this model does not take images. Say so plainly rather than "
        "describing what you cannot see; the files are in the workspace.]"
    )


def content_parts(message: Message, image_type: str = "image_url") -> str | list[dict[str, object]]:
    """The user message as content parts with its images, for the Chat Completions API
    (``image_type="image_url"``) or the Responses API (``"input_image"``). A plain string
    when there is nothing to attach."""
    if not message.images:
        return message.content or ""
    parts: list[dict[str, object]] = []
    dropped: list[str] = []
    for path in message.images:
        url = image_data_url(path)
        if url is None:
            dropped.append(Path(path).name)
            continue
        if image_type == "input_image":
            parts.append({"type": "input_image", "image_url": url, "detail": "auto"})
        else:
            parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
    text = message.content or ""
    if dropped:
        text += (
            f"\n\n[{len(dropped)} attached image{'s' if len(dropped) != 1 else ''} could not be "
            f"included: {', '.join(dropped)}; missing or too large.]"
        )
    if not parts:
        return text
    text_type = "input_text" if image_type == "input_image" else "text"
    return [{"type": text_type, "text": text}, *parts]


def keep_newest_images(messages: list[Message], keep: int) -> list[Message]:
    """The same conversation with pictures only on the newest ``keep`` image-bearing
    messages (C9: a hands session adds a screenshot or two per step, and every step sends
    the whole conversation again). Older ones lose their images and say so in a short note,
    so the model still knows a screenshot was there. ``keep <= 0`` keeps everything. Pure:
    copies, never the originals."""
    if keep <= 0:
        return list(messages)
    with_images = [i for i, m in enumerate(messages) if m.role == Role.USER and m.images]
    drop = set(with_images[:-keep]) if len(with_images) > keep else set()
    if not drop:
        return list(messages)
    out: list[Message] = []
    for i, m in enumerate(messages):
        if i in drop:
            out.append(
                m.model_copy(update={"images": None, "content": (m.content or "") + REMOVED_NOTE})
            )
        else:
            out.append(m)
    return out


def without_images(messages: list[Message]) -> list[Message]:
    """The same conversation for a model that cannot take images: pictures dropped, and
    each message that had some says so."""
    out: list[Message] = []
    for m in messages:
        if m.role == Role.USER and m.images:
            names = [Path(p).name for p in m.images]
            out.append(
                m.model_copy(
                    update={"images": None, "content": (m.content or "") + missing_note(names)}
                )
            )
        else:
            out.append(m)
    return out


__all__ = [
    "model_takes_images",
    "IMAGE_SUFFIXES",
    "content_parts",
    "has_images",
    "image_data_url",
    "is_image",
    "keep_newest_images",
    "missing_note",
    "says_no_images",
    "without_images",
]
