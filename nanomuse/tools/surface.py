"""What the phone tools and the computer tools do the same way.

A *surface* is a screen the hands work on: the phone's, or this computer's. Reading it,
waiting while the user has it, handing it over and taking it back (contract C1 in
docs/browser.md) are the same steps on both; only the words differ. The two tool modules
(:mod:`nanomuse.tools.phone`, :mod:`nanomuse.tools.computer`) each describe their surface
once and call the functions here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from nanomuse.agent.holds import took_over_note
from nanomuse.phone.link import DeviceError
from nanomuse.phone.screen import Screen
from nanomuse.schema import ToolResult


@dataclass(frozen=True)
class Surface:
    """The words for one kind of screen."""

    #: the hold's device name: ``"phone"`` or ``"computer"``
    device: str
    #: where the user does their part: ``"on the phone"``, ``"on the screen"``
    where: str
    #: what a missing screenshot means here
    no_shot: str
    #: say the picture's size and the coordinate unit under every screen (the computer)
    say_size: bool = False
    #: how far outside the picture a point may still count as on it (the phone's rounding)
    slack: float = 0.0


PHONE = Surface(
    device="phone",
    where="on the phone",
    no_shot="the phone may be locked or showing a protected screen",
    slack=1.0,
)
COMPUTER = Surface(
    device="computer",
    where="on the screen",
    no_shot="the display may be locked",
    say_size=True,
)


class _Link(Protocol):
    async def screen(self) -> Screen: ...


def num(value: Any) -> str:
    """A number for a summary (``12``, ``0.5``), or ``?`` when it is not one."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "?"


def inside(point: tuple[float, float], screen: Screen, surface: Surface) -> bool:
    """Is the point on the picture (within the surface's slack)? True when the screen's
    size is unknown."""
    if not (screen.width and screen.height):
        return True
    x, y = point
    s = surface.slack
    return -s <= x <= screen.width + s and -s <= y <= screen.height + s


def trusted_node_words(screen: Screen | None, point: tuple[float, float] | None) -> str | None:
    """The words of the smallest element the screen reported whose bounds contain ``point``,
    or None when the screen reported no such element (no tree, or nothing under the point).

    The model's `label` is its own claim and is not trusted for risk. The element is the
    screen's evidence. Only reported bounds count as a hit: a centre alone says nothing
    about an element's area."""
    if screen is None or point is None:
        return None
    x, y = point
    matches: list[tuple[float, dict[str, Any]]] = []
    for node in screen.nodes:
        box = node.get("box")
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            left, top, right, bottom = (float(value) for value in box)
        except (TypeError, ValueError):
            continue
        if left <= x <= right and top <= y <= bottom and right > left and bottom > top:
            matches.append(((right - left) * (bottom - top), node))
    if not matches:
        return None
    node = min(matches, key=lambda item: item[0])[1]
    words = " / ".join(
        str(node[key]).strip() for key in ("text", "desc", "hint", "res") if node.get(key)
    )
    return words or None


def screen_result(screen: Screen, surface: Surface, prefix: str = "") -> ToolResult:
    """The screen as a tool result: its rendering, the screenshot when there is one, and a
    note when there is not."""
    text = (prefix + "\n\n" if prefix else "") + screen.render()
    if not screen.image_path:
        text += f"\n(no screenshot came back; {surface.no_shot})"
    elif surface.say_size and screen.width and screen.height:
        # the picture is the unit: nothing here speaks of the display's own size
        text += (
            f"\nCoordinates: pixels of this {screen.width}×{screen.height} picture, (0,0) top-left."
        )
    return ToolResult(output=text, images=[screen.image_path] if screen.image_path else None)


async def wait_hold(holds: Any, surface: Surface) -> str:
    """Wait while the user has the surface (a hold is on); the note for the model when
    there was one, so it looks again before acting on what it last saw."""
    if holds is None:
        return ""
    return (
        took_over_note(surface.device) if await holds.wait(holds.thread(), surface.device) else ""
    )


async def hand_over(
    holds: Any, link: _Link, reason: str, timeout: float, surface: Surface
) -> ToolResult:
    """The agent gives the surface to the user (contract C1): a hold goes on with the
    reason, the user does their part (a password, a code, a confirmation) and presses
    Done; the tool returns the screen as they left it."""
    reason = " ".join(str(reason or "").split())
    if not reason:
        return ToolResult.fail(f"`reason` is required: say what the user should do {surface.where}")
    if holds is None:
        return ToolResult.fail(
            "hand_over is not available here; ask the user with `ask_user` to do it and tell "
            "you when it is done"
        )
    finished = await holds.hand_over(holds.thread(), surface.device, reason, timeout=timeout)
    note = took_over_note(surface.device, finished)
    try:
        screen = await link.screen()
    except DeviceError as exc:
        return ToolResult(output=f"{note}\n\n(the screen could not be read afterwards: {exc})")
    return screen_result(screen, surface, note)


__all__ = [
    "COMPUTER",
    "PHONE",
    "Surface",
    "hand_over",
    "inside",
    "num",
    "screen_result",
    "trusted_node_words",
    "wait_hold",
]
