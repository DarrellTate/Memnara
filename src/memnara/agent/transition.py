"""Generic scene stability for frames the loop has already captured.

This answers whether the current frame looks stable enough for normal
action and stuck interpretation. It does not name the destination
(battle, area, menu, or anything else) and it does not call a model.

Strong evidence is transient. Anything else, including an ordinary dark
scene that still has structure, stays stable.
"""

from __future__ import annotations

from enum import Enum

# At most this many button-free frames are advanced for one transition
# episode. A later stable frame clears the counter. This is not a WAIT action.
DEFAULT_TRANSITION_GRACE_FRAMES = 120

# Re-check pixels after each chunk so a short fade does not run out the budget.
# The check is a framebuffer read, not a vision-model call.
DEFAULT_TRANSITION_CHUNK_FRAMES = 8

# Prepended to the reasoning history only when a decision is still being made
# on a transient frame (the grace budget is already spent).
TRANSITION_GUIDANCE = (
    "SCENE TRANSITIONING. Avoid gameplay inputs until the scene stabilizes. Prefer WAIT."
)

_NEAR_BLACK_LEVEL = 16
_NEAR_BLACK_MEAN = 18
_NEAR_BLACK_FRACTION = 92
_UNIFORM_SPAN = 6
_SAMPLE_LIMIT = 48_000


class SceneStability(str, Enum):
    STABLE = "STABLE"
    TRANSIENT = "TRANSIENT"


def frame_stability(pixels: bytes, width: int, height: int, pixel_format: str) -> SceneStability:
    """Classify one framebuffer. Conservative: weak evidence stays STABLE."""
    samples = _luma_samples(pixels, width, height, pixel_format)
    if len(samples) < 16:
        return SceneStability.STABLE
    low = sum(1 for value in samples if value <= _NEAR_BLACK_LEVEL)
    mean = sum(samples) // len(samples)
    span = max(samples) - min(samples)
    if low * 100 >= _NEAR_BLACK_FRACTION * len(samples) and mean <= _NEAR_BLACK_MEAN:
        return SceneStability.TRANSIENT
    if span <= _UNIFORM_SPAN:
        return SceneStability.TRANSIENT
    return SceneStability.STABLE


def _luma_samples(pixels: bytes, width: int, height: int, pixel_format: str) -> list[int]:
    bpp = _bytes_per_pixel(pixels, width, height, pixel_format)
    if bpp == 0:
        return []
    count = width * height
    stride = 1
    if count > _SAMPLE_LIMIT:
        stride = max(1, int((count / _SAMPLE_LIMIT) ** 0.5))
    samples: list[int] = []
    for y in range(0, height, stride):
        row = y * width * bpp
        for x in range(0, width, stride):
            index = row + x * bpp
            if index + bpp > len(pixels):
                return []
            if bpp == 1:
                samples.append(pixels[index])
            else:
                samples.append((pixels[index] + pixels[index + 1] + pixels[index + 2]) // 3)
    return samples


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
    if label == "RGB" and size >= expected * 3:
        return 3
    if label in {"RGBA", "BGRA"} and size >= expected * 4:
        return 4
    return 0
