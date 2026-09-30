"""Cheap deterministic frame-change gate. Does not call a model."""

from __future__ import annotations

from memnara.emulators.base import Framebuffer

DEFAULT_CHANGE_THRESHOLD = 0.015


def changed_pixel_ratio(previous: bytes, current: bytes, *, width: int, height: int, channels: int = 4) -> float:
    """Fraction of pixels whose RGB differs. Ignores alpha when channels==4."""
    expected = width * height * channels
    if len(previous) != expected or len(current) != expected:
        return 1.0
    if previous == current:
        return 0.0
    step = 3 if channels >= 3 else channels
    changed = 0
    pixels = width * height
    for i in range(pixels):
        offset = i * channels
        if previous[offset : offset + step] != current[offset : offset + step]:
            changed += 1
    return changed / pixels


class FrameChangeDetector:
    """First frame always fires. Later frames fire when RGB change ratio >= threshold."""

    def __init__(self, *, threshold: float = DEFAULT_CHANGE_THRESHOLD) -> None:
        if threshold < 0 or threshold > 1:
            raise ValueError("threshold must be in [0, 1]")
        self.threshold = threshold
        self._last_pixels: bytes | None = None
        self._last_size: tuple[int, int] | None = None

    def reset(self) -> None:
        self._last_pixels = None
        self._last_size = None

    def should_observe(self, frame: Framebuffer) -> bool:
        size = (frame.width, frame.height)
        if self._last_pixels is None or self._last_size != size:
            self._last_pixels = frame.pixels
            self._last_size = size
            return True
        ratio = changed_pixel_ratio(
            self._last_pixels,
            frame.pixels,
            width=frame.width,
            height=frame.height,
            channels=4 if frame.pixel_format.upper() == "RGBA" else 3,
        )
        if ratio >= self.threshold:
            self._last_pixels = frame.pixels
            return True
        return False
