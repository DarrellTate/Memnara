"""Is a proposal still aimed at the state it was reasoned from?

A continuous runtime keeps moving while a model thinks, so "the frame changed"
cannot mean "the decision is stale": an idle menu animates. This module records
the decision-relevant state of the observation that was reasoned on, then judges
a later probe against it using evidence available without a second model call.

Nothing here reads free-form model prose, and nothing here assigns meaning to a
button.
"""

from __future__ import annotations

from dataclasses import dataclass

from memnara.agent.interaction import interaction_signature
from memnara.agent.observe import ObservedState
from memnara.agent.readiness import frames_meaningfully_changed
from memnara.agent.transition import SceneStability

FRESH = ""


@dataclass(frozen=True)
class DecisionSignature:
    """Immutable decision-relevant state of the observation that was reasoned on.

    `observation_id` names the observation. Every other field is compared by
    `staleness_reason`. Nothing is stored that cannot be re-read cheaply: the
    freshness check makes no second vision call, so perception flags are not
    kept here. Timestamps and frame counters live on `ObservedState`, where they
    are diagnostics.
    """

    observation_id: str
    owner: str
    interaction_mode: str
    scene_stability: str
    progress_token: str
    screen_digest: str


def signature_of(state: ObservedState, *, owner: str, interaction_mode: str) -> DecisionSignature:
    _flags, token = interaction_signature(state)
    return DecisionSignature(
        observation_id=state.observation_id,
        owner=owner,
        interaction_mode=interaction_mode,
        scene_stability=state.scene_stability,
        progress_token=token,
        screen_digest=state.screen_digest,
    )


def staleness_reason(
    *,
    signature: DecisionSignature,
    owner_now: str,
    mode_now: str | None = None,
    stability_now: str | None = None,
    digest_now: str = "",
    frame_before=None,
    frame_now=None,
    token_now: str | None = None,
) -> str:
    """Empty string when the proposal still targets an equivalent state.

    Ownership is authoritative. An interaction-mode change or a scene that has
    started transitioning is stale. A structured token that moved on is stale. An
    identical framebuffer is trivially fresh. Otherwise the pixels decide: idle
    animation stays equivalent, and a material change is stale.
    """
    if owner_now != signature.owner:
        return f"ownership changed from {signature.owner} to {owner_now}"
    if mode_now is not None and mode_now != signature.interaction_mode:
        return f"interaction mode changed from {signature.interaction_mode} to {mode_now}"
    if stability_now is not None and stability_now != signature.scene_stability:
        return f"scene stability changed from {signature.scene_stability} to {stability_now}"
    if token_now is not None and signature.progress_token and token_now != signature.progress_token:
        return "structured state advanced"
    if digest_now and digest_now == signature.screen_digest:
        return FRESH
    if frame_before is not None and frame_now is not None:
        if frames_meaningfully_changed(frame_before, frame_now):
            return "the scene changed materially while the decision was pending"
    return FRESH


def transition_started(signature: DecisionSignature, stability_now: str) -> bool:
    """True when a settled decision frame has become a transition."""
    return (
        signature.scene_stability == SceneStability.STABLE.value
        and stability_now == SceneStability.TRANSIENT.value
    )
