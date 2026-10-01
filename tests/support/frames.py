"""Shared synthetic frame helpers. No ROM, no emulator, no model."""

from __future__ import annotations

from memnara.emulators.base import Framebuffer

# Large enough that a few moving pixels stay under the 1.5% change threshold:
# 1.5% of 1600 pixels is 24, so four moving pixels read as idle animation and a
# repainted frame reads as a material change.
FRAME_WIDTH = 40
FRAME_HEIGHT = 40
FRAME_PIXELS = FRAME_WIDTH * FRAME_HEIGHT
IDLE_PIXELS = 4


def paint(mark: int, *, idle: int = 0) -> bytes:
    """A gradient so the frame is never near-uniform, plus optional idle pixels."""
    body = bytearray()
    for index in range(FRAME_PIXELS):
        value = (index * 7 + mark * 29) % 200 + 20
        body += bytes((value, value, value))
    for index in range(idle):
        offset = index * 3
        body[offset] = (idle * 37 + index) % 256
    return bytes(body)


def frame(pixels: bytes) -> Framebuffer:
    return Framebuffer(
        width=FRAME_WIDTH,
        height=FRAME_HEIGHT,
        pixel_format="RGB",
        pixels=pixels,
        source="test.runtime",
    )
