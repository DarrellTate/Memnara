"""Generic locomotion outcome from observations the loop already has.

No extra vision call, map, or title-specific collision rule. A locomotion
action is any name that starts with ``MOVE_``. That covers directional
emulator input and future keyboard or controller locomotion without treating
the abstraction as a D-pad.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256

from memnara.perception.context import PerceptionContext

# Opaque adapter facts. Values are compared, never interpreted as coordinates.
NAVIGATION_FACT_KEYS = ("location_token", "navigation_token", "position_token")

_MAX_SHIFT = 32
_SHIFT_ERROR_MAX = 6
_SHIFT_GAIN = 8


class MovementOutcome(str, Enum):
    MOVED = "MOVED"
    BLOCKED = "BLOCKED"
    UNCERTAIN = "UNCERTAIN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class SceneSignature:
    """Coarse scene structure from one framebuffer. Not a sprite or tile map.

    The digest covers the surrounding scene only. The central window is omitted
    so an in-place animation does not look like a scene change.
    """

    border_digest: str
    horizontal: tuple[int, ...]
    vertical: tuple[int, ...]


def is_locomotion(action: str | None) -> bool:
    return bool(action) and action.startswith("MOVE_")


def read_navigation_token(context: PerceptionContext) -> str | None:
    """Join generic navigation facts when an adapter supplied them."""
    state = context.game_state
    if state is None:
        return None
    parts: list[str] = []
    for fact in state.facts:
        if fact.key not in NAVIGATION_FACT_KEYS:
            continue
        if fact.value is None:
            continue
        text = str(fact.value).strip()
        if not text:
            continue
        parts.append(f"{fact.key}={text}")
    if not parts:
        return None
    return "|".join(sorted(parts))


def frame_signature(pixels: bytes, width: int, height: int, pixel_format: str) -> SceneSignature | None:
    """Reduce one already-captured frame. Returns None when the buffer is unusable."""
    bpp = _bytes_per_pixel(pixels, width, height, pixel_format)
    if bpp == 0 or width < 8 or height < 8:
        return None
    luminance = _luminance(pixels, width, height, bpp)
    x0 = width // 4
    x1 = width - x0
    y0 = height // 4
    y1 = height - y0
    if x1 <= x0 or y1 <= y0:
        return None
    border = bytearray()
    center_count = 0
    columns = [0] * width
    column_counts = [0] * width
    rows = [0] * height
    row_counts = [0] * height
    for y in range(height):
        row = luminance[y]
        for x in range(width):
            value = row[x]
            in_center = x0 <= x < x1 and y0 <= y < y1
            if in_center:
                center_count += 1
                continue
            border.append(value)
            # Top and bottom bands: surrounding scene, full width, actor window excluded.
            if y < y0 or y >= y1:
                columns[x] += value
                column_counts[x] += 1
            # Side bands: surrounding scene, full height.
            if x < x0 or x >= x1:
                rows[y] += value
                row_counts[y] += 1
    if not border or center_count == 0 or 0 in column_counts or 0 in row_counts:
        return None
    return SceneSignature(
        border_digest=_digest(border),
        horizontal=tuple(columns[i] // column_counts[i] for i in range(width)),
        vertical=tuple(rows[i] // row_counts[i] for i in range(height)),
    )


def classify_movement(
    *,
    action: str | None,
    executed: bool,
    navigation_before: str | None,
    navigation_after: str | None,
    scene_before: SceneSignature | None,
    scene_after: SceneSignature | None,
) -> MovementOutcome:
    """Classify one attempted locomotion step.

    Structured navigation tokens, when both sides have them, are stronger than
    pixels. Otherwise a stable surrounding scene is BLOCKED, a clear scene
    shift is MOVED, and everything else is UNCERTAIN.
    """
    if not executed or not is_locomotion(action):
        return MovementOutcome.NOT_APPLICABLE
    token_outcome = _from_navigation_tokens(navigation_before, navigation_after)
    if token_outcome is not None:
        return token_outcome
    return _from_scenes(scene_before, scene_after)


def _from_navigation_tokens(before: str | None, after: str | None) -> MovementOutcome | None:
    if before is None and after is None:
        return None
    if before is None or after is None:
        return MovementOutcome.UNCERTAIN
    if before == after:
        return MovementOutcome.BLOCKED
    return MovementOutcome.MOVED


def _from_scenes(before: SceneSignature | None, after: SceneSignature | None) -> MovementOutcome:
    if before is None or after is None:
        return MovementOutcome.UNCERTAIN
    if before.border_digest and before.border_digest == after.border_digest:
        return MovementOutcome.BLOCKED
    if _axis_shifted(before.horizontal, after.horizontal) or _axis_shifted(before.vertical, after.vertical):
        return MovementOutcome.MOVED
    return MovementOutcome.UNCERTAIN


def _axis_shifted(before: tuple[int, ...], after: tuple[int, ...]) -> bool:
    if len(before) != len(after) or len(before) < 8:
        return False
    limit = min(_MAX_SHIFT, (len(before) - 1) // 2)
    if limit < 1:
        return False
    identity = _shift_error(before, after, 0)
    best = min(_shift_error(before, after, shift) for shift in range(-limit, limit + 1) if shift)
    return best <= _SHIFT_ERROR_MAX and identity >= best + _SHIFT_GAIN


def _shift_error(before: tuple[int, ...], after: tuple[int, ...], shift: int) -> int:
    if shift > 0:
        pairs = zip(before[: len(before) - shift], after[shift:])
    elif shift < 0:
        pairs = zip(before[-shift:], after[: len(after) + shift])
    else:
        pairs = zip(before, after)
    total = 0
    count = 0
    for left, right in pairs:
        total += abs(left - right)
        count += 1
    if count == 0:
        return 10_000
    return total // count


def _luminance(pixels: bytes, width: int, height: int, bpp: int) -> list[list[int]]:
    rows: list[list[int]] = []
    for y in range(height):
        row: list[int] = []
        base = y * width * bpp
        for x in range(width):
            i = base + x * bpp
            if bpp == 1:
                row.append(pixels[i])
            else:
                row.append((pixels[i] + pixels[i + 1] + pixels[i + 2]) // 3)
        rows.append(row)
    return rows


def _bytes_per_pixel(pixels: bytes, width: int, height: int, pixel_format: str) -> int:
    if width < 1 or height < 1:
        return 0
    expected = width * height
    size = len(pixels)
    if size == expected:
        return 1
    if size == expected * 3:
        return 3
    if size == expected * 4:
        return 4
    label = (pixel_format or "").upper()
    if label in {"RGB"} and size >= expected * 3:
        return 3
    if label in {"RGBA", "BGRA"} and size >= expected * 4:
        return 4
    return 0


def _digest(values: bytearray) -> str:
    return sha256(values).hexdigest()[:16]
