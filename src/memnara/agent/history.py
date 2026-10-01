"""In-memory recent-step history. Not persistent memory."""

from __future__ import annotations

from dataclasses import dataclass

from memnara.agent.actions import ActionProposal


@dataclass(frozen=True)
class RecentStep:
    step: int
    before_summary: str
    before_fingerprint: str
    proposal: ActionProposal | None
    validation_ok: bool
    executed: bool
    execution_ok: bool
    after_summary: str
    after_fingerprint: str
    screen_changed: bool
    state_changed: bool
    stuck_state: str
    progress: bool
    error: str = ""
    perception_ms: float | None = None
    reasoning_ms: float | None = None
    execution_ms: float | None = None
    total_ms: float | None = None
    interaction_mode: str = "NON_BATTLE"
    movement_outcome: str = "NOT_APPLICABLE"
    scene_stability: str = "STABLE"
    transition_state: str = "STABLE"
    transition_grace_remaining: int = 0
    passive_frames: int = 0
    interaction_outcome: str = "NOT_APPLICABLE"
    perception_reused: bool = False
    confirmation_ms: float | None = None
    # confirmation_ms is the post-action observation's perception_ms, not the
    # cheap confirm_execution probe. post_acquire_ms is the full after-action
    # acquire wall time, including passive waits.
    vision_ms: float | None = None
    decision_readiness: str = "UNKNOWN"
    progression_frames: int = 0
    progression_chunks: int = 0
    passive_runtime_ms: float | None = None
    model_wait_ms: float | None = None
    observation_id: str = ""
    proposal_age_ms: float | None = None
    frames_since_observation: int = 0
    # Running total for the whole run, not a per-step count.
    stale_proposals_dropped: int = 0
    execution_frames: int = 0
    applied_observation_id: str = ""
    thinking_profile: str = "balanced"
    acquire_ms: float | None = None
    freshness_ms: float | None = None
    post_acquire_ms: float | None = None
    classification_ms: float | None = None
    unaccounted_ms: float | None = None
    prompt_system_chars: int | None = None
    prompt_user_chars: int | None = None
    perception_tier: str = "normal"
    post_vision_skipped: bool = False
    vision_call_count: int = 0
    vision_png_bytes: int | None = None
    vision_eval_count: int | None = None
    vision_encode_ms: float | None = None
    vision_http_ms: float | None = None
    vision_parse_ms: float | None = None
    vision_prompt_chars: int | None = None
    vision_generation_chars: int | None = None


class StepHistory:
    def __init__(self, *, maxlen: int = 16) -> None:
        self.maxlen = maxlen
        self._items: list[RecentStep] = []

    def append(self, step: RecentStep) -> None:
        self._items.append(step)
        if len(self._items) > self.maxlen:
            del self._items[0 : len(self._items) - self.maxlen]

    @property
    def items(self) -> tuple[RecentStep, ...]:
        return tuple(self._items)

    def action_lines(self, *, limit: int = 4) -> tuple[str, ...]:
        lines: list[str] = []
        for item in self._items[-limit:]:
            action = item.proposal.action if item.proposal else "NONE"
            outcome = item.movement_outcome
            if outcome == "NOT_APPLICABLE" and item.interaction_outcome != "NOT_APPLICABLE":
                outcome = item.interaction_outcome
            lines.append(f"{action} → {outcome}")
        return tuple(lines)
