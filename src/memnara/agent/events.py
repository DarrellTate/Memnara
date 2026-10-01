"""Structured gameplay events already produced by the loop.

This is not affect and not voice. It names outcomes the planned affect
prototype can subscribe to without another model call.
"""

from __future__ import annotations

from memnara.agent.battle import mode_transition
from memnara.agent.history import RecentStep

# Stable names. Do not treat these as personality output.
BLOCKED = "BLOCKED"
MOVED = "MOVED"
NO_EFFECT = "NO_EFFECT"
ADVANCED = "ADVANCED"
CHANGED = "CHANGED"
BATTLE_ENTRY = "BATTLE_ENTRY"
BATTLE_EXIT = "BATTLE_EXIT"
STUCK = "STUCK"
PROGRESS = "PROGRESS"
SCENE_CHANGED = "SCENE_CHANGED"
TRANSITION = "TRANSITION"


def structured_step_events(
    step: RecentStep,
    *,
    previous_mode: str | None = None,
) -> tuple[str, ...]:
    """Deterministic event names from one already-recorded step."""
    events: list[str] = []
    movement = step.movement_outcome
    if movement == "BLOCKED":
        events.append(BLOCKED)
    elif movement == "MOVED":
        events.append(MOVED)
    interaction = step.interaction_outcome
    if interaction == "NO_EFFECT":
        events.append(NO_EFFECT)
    elif interaction == "ADVANCED":
        events.append(ADVANCED)
    elif interaction == "CHANGED":
        events.append(CHANGED)
    transition = mode_transition(previous_mode, step.interaction_mode)
    if transition == "entry":
        events.append(BATTLE_ENTRY)
    elif transition == "exit":
        events.append(BATTLE_EXIT)
    if step.stuck_state and step.stuck_state != "NORMAL":
        events.append(STUCK)
    if step.progress:
        events.append(PROGRESS)
    if step.screen_changed or step.state_changed:
        events.append(SCENE_CHANGED)
    if step.transition_state == "TRANSIENT" or step.scene_stability == "TRANSIENT":
        events.append(TRANSITION)
    return tuple(events)
