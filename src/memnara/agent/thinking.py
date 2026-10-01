"""Thinking depth is an execution setting, not an AI identity.

Future M10 can expose a Thinking selector next to Model. Changing FAST to
BALANCED does not mint a new profile, swap a model, or change voice/runtime.
Providers consume these numeric/text budgets; they should not branch on UI names.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

DEFAULT_KEEP_ALIVE = "30m"


class ThinkingProfile(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    DELIBERATE = "deliberate"


DEFAULT_THINKING_PROFILE = ThinkingProfile.BALANCED

# In-run recent-step history only. Not M7 memory.
_FAST_HISTORY_MAXLEN = 8
_BALANCED_HISTORY_MAXLEN = 16
_DELIBERATE_HISTORY_MAXLEN = 24

# Prompt window. FAST keeps the same four outcome lines so BLOCKED/NO_EFFECT survive.
_FAST_HISTORY_PROMPT_LINES = 4
_BALANCED_HISTORY_PROMPT_LINES = 4
_DELIBERATE_HISTORY_PROMPT_LINES = 8

REUSE_EXACT = "exact"
REUSE_SIMILAR = "similar"


@dataclass(frozen=True)
class ThinkingSettings:
    """Resolved latency/depth budgets. Construct via `resolve_thinking`, not ad-hoc ifs."""

    name: str
    history_maxlen: int
    history_prompt_lines: int
    vision_num_predict: int
    reasoner_num_predict: int
    vision_description_limit: int
    vision_compact_prompt: bool
    reasoner_compact_prompt: bool
    perception_reuse: str
    vision_scale: int = 3
    reason_limit: int = 160
    keep_alive: str = DEFAULT_KEEP_ALIVE
    think: bool = False

    @property
    def profile(self) -> ThinkingProfile:
        return ThinkingProfile(self.name)


def parse_thinking_profile(value: str | ThinkingProfile | None) -> ThinkingProfile:
    """Map CLI/config text onto a profile. Unknown names fail closed."""
    if value is None or value == "":
        return DEFAULT_THINKING_PROFILE
    if isinstance(value, ThinkingProfile):
        return value
    key = str(value).strip().lower()
    try:
        return ThinkingProfile(key)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ThinkingProfile)
        raise ValueError(f"unknown thinking profile {value!r}; expected {allowed}") from exc


def resolve_thinking(value: str | ThinkingProfile | None = None) -> ThinkingSettings:
    profile = parse_thinking_profile(value)
    if profile is ThinkingProfile.FAST:
        return ThinkingSettings(
            name=profile.value,
            history_maxlen=_FAST_HISTORY_MAXLEN,
            history_prompt_lines=_FAST_HISTORY_PROMPT_LINES,
            vision_num_predict=128,
            reasoner_num_predict=96,
            vision_description_limit=120,
            vision_compact_prompt=True,
            reasoner_compact_prompt=True,
            perception_reuse=REUSE_SIMILAR,
            vision_scale=2,
            reason_limit=80,
        )
    if profile is ThinkingProfile.DELIBERATE:
        return ThinkingSettings(
            name=profile.value,
            history_maxlen=_DELIBERATE_HISTORY_MAXLEN,
            history_prompt_lines=_DELIBERATE_HISTORY_PROMPT_LINES,
            vision_num_predict=320,
            reasoner_num_predict=256,
            vision_description_limit=400,
            vision_compact_prompt=False,
            reasoner_compact_prompt=False,
            perception_reuse=REUSE_EXACT,
            vision_scale=3,
            reason_limit=200,
        )
    return ThinkingSettings(
        name=ThinkingProfile.BALANCED.value,
        history_maxlen=_BALANCED_HISTORY_MAXLEN,
        history_prompt_lines=_BALANCED_HISTORY_PROMPT_LINES,
        vision_num_predict=192,
        reasoner_num_predict=160,
        vision_description_limit=180,
        vision_compact_prompt=True,
        reasoner_compact_prompt=True,
        perception_reuse=REUSE_SIMILAR,
        vision_scale=2,
        reason_limit=120,
    )


def prompt_size_report(system: str, user: str) -> dict[str, int]:
    """Character counts. Approximate tokens as chars/4 when the provider has none."""
    system_chars = len(system or "")
    user_chars = len(user or "")
    return {
        "system_chars": system_chars,
        "user_chars": user_chars,
        "total_chars": system_chars + user_chars,
        "approx_tokens": (system_chars + user_chars + 3) // 4,
    }


def clip_text(text: str, limit: int) -> str:
    """Trim on a word boundary when possible. Empty input stays empty."""
    stripped = (text or "").strip()
    if limit < 1 or len(stripped) <= limit:
        return stripped
    clipped = stripped[:limit].rstrip()
    pivot = max(0, limit // 2)
    if " " in clipped[pivot:]:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped or stripped[:limit]
