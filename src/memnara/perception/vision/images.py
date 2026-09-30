"""Framebuffer to in-memory PNG. Integer nearest-neighbor scale. No PyBoy types."""

from __future__ import annotations

import io

from memnara.emulators.base import Framebuffer
from memnara.perception.vision.exceptions import VisionError

ALLOWED_SCALES = (1, 2, 3, 4)
DEFAULT_SCALE = 3


def encode_framebuffer_png(frame: Framebuffer, *, scale: int = DEFAULT_SCALE) -> tuple[bytes, int, int]:
    """Return PNG bytes plus scaled width/height. Does not write to disk."""
    if scale not in ALLOWED_SCALES:
        raise VisionError(f"scale must be one of {ALLOWED_SCALES}, got {scale}")
    if frame.width < 1 or frame.height < 1:
        raise VisionError("framebuffer dimensions must be positive")
    expected = frame.width * frame.height * _channels(frame.pixel_format)
    if len(frame.pixels) != expected:
        raise VisionError(
            f"pixel buffer length {len(frame.pixels)} does not match "
            f"{frame.width}x{frame.height} {frame.pixel_format}"
        )
    from PIL import Image

    mode = _pil_mode(frame.pixel_format)
    image = Image.frombytes(mode, (frame.width, frame.height), frame.pixels)
    if image.mode != "RGB":
        image = image.convert("RGB")
    width, height = image.size
    if scale != 1:
        width, height = width * scale, height * scale
        image = image.resize((width, height), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), width, height


def _channels(pixel_format: str) -> int:
    fmt = pixel_format.upper()
    if fmt == "RGBA":
        return 4
    if fmt == "RGB":
        return 3
    raise VisionError(f"unsupported pixel format: {pixel_format}")


def _pil_mode(pixel_format: str) -> str:
    fmt = pixel_format.upper()
    if fmt == "RGBA":
        return "RGBA"
    if fmt == "RGB":
        return "RGB"
    raise VisionError(f"unsupported pixel format: {pixel_format}")
