"""Whether the runtime is waiting for a gameplay decision.

This is not scene stability. A frame can be visually structured and still be
changing on its own (attack motion, text reveal, a camera shift). It is also
not an interaction outcome and not a button meaning.

The loop uses it only to decide whether a bounded, button-free frame advance
is safer than asking the model again. Runtimes that cannot step frames leave
this UNKNOWN and keep the normal decision loop.
"""

from __future__ import annotations

from enum import Enum

from memnara.emulators.base import Framebuffer
from memnara.perception.vision.change import DEFAULT_CHANGE_THRESHOLD, changed_pixel_ratio

# One passive episode. A later settled frame, or this budget, ends it.
# 180 emulated frames is about three seconds at 60 emulated frames per second.
DEFAULT_PASSIVE_BUDGET_FRAMES = 180

# Compare pixels after each chunk. The comparison is a framebuffer read, not a model call.
DEFAULT_PASSIVE_CHUNK_FRAMES = 8

# Checked between chunks. A single tick that never returns is not interrupted.
# Not a display-refresh target.
DEFAULT_PASSIVE_WALL_S = 5.0

# Prepended to the reasoning history only when this observation follows a passive episode.
PASSIVE_GUIDANCE = (
    "RUNTIME ADVANCING. The game has been changing without a new gameplay input. "
    "Decide for the current frame."
)


class DecisionReadiness(str, Enum):
    INPUT_REQUIRED = "INPUT_REQUIRED"
    PASSIVE_PROGRESS = "PASSIVE_PROGRESS"
    UNKNOWN = "UNKNOWN"


def frames_meaningfully_changed(before: Framebuffer, after: Framebuffer) -> bool:
    """True when the framebuffer changed enough to treat the motion as autonomous.

    A few flickering pixels stay under the threshold. The caller still has to
    see the change continue across a chunk before it keeps advancing.
    """
    if before.width != after.width or before.height != after.height:
        return True
    channels = 4 if (after.pixel_format or "").upper() in {"RGBA", "BGRA"} else 3
    ratio = changed_pixel_ratio(
        before.pixels,
        after.pixels,
        width=after.width,
        height=after.height,
        channels=channels,
    )
    return ratio >= DEFAULT_CHANGE_THRESHOLD
