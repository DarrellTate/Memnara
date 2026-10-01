"""Semantic freshness of a pending decision. Synthetic frames only."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from memnara.agent.freshness import (
    FRESH,
    DecisionSignature,
    signature_of,
    staleness_reason,
    transition_started,
)
from memnara.agent.observe import ObservedState
from memnara.agent.transition import SceneStability
from memnara.perception.fusion import fuse
from memnara.perception.vision.models import SceneType, VisualObservation
from tests.support.frames import IDLE_PIXELS, frame as _frame, paint as _paint

OWNER = "AI_CONTROL"
MODE = "NON_BATTLE"


def _visual(*, battle: bool = False, text: tuple[str, ...] = ("FIGHT",)) -> VisualObservation:
    return VisualObservation(
        scene_type=SceneType.MENU,
        description="a menu is open",
        visible_text=text,
        entities=(),
        menu_visible=True,
        dialogue_visible=False,
        battle_visible=battle,
        confidence=0.9,
        notable_changes="",
        source="VISUAL",
        model="test-vision",
    )


def _state(
    *,
    digest: str = "aaaa",
    token: str = "",
    stability: str = SceneStability.STABLE.value,
    battle: bool = False,
    text: tuple[str, ...] = ("FIGHT",),
) -> ObservedState:
    return ObservedState(
        context=fuse(visual=_visual(battle=battle, text=text)),
        fingerprint="fp",
        progress_token=token,
        screen_digest=digest,
        perception_ms=1.0,
        summary="a menu is open",
        scene_stability=stability,
        observation_id="obs-1",
        observed_at=1000.0,
        runtime_frame=120,
    )


def _signature(**kwargs) -> DecisionSignature:
    return signature_of(_state(**kwargs), owner=OWNER, interaction_mode=MODE)


def test_the_signature_captures_only_comparable_decision_state() -> None:
    signature = _signature(token="map:1")
    assert signature.observation_id == "obs-1"
    assert signature.owner == OWNER
    assert signature.interaction_mode == MODE
    assert signature.scene_stability == SceneStability.STABLE.value
    assert signature.progress_token == "map:1"
    assert signature.screen_digest == "aaaa"
    # Free-form model prose is never part of the comparison.
    assert "a menu is open" not in repr(signature)
    # Only what a cheap re-read can answer is stored, so nothing is dead weight.
    compared = {"owner", "interaction_mode", "scene_stability", "progress_token", "screen_digest"}
    assert set(vars(signature)) == compared | {"observation_id"}


def test_an_identical_framebuffer_is_fresh_without_a_pixel_comparison() -> None:
    signature = _signature(digest="same")
    reason = staleness_reason(
        signature=signature,
        owner_now=OWNER,
        mode_now=MODE,
        stability_now=SceneStability.STABLE.value,
        digest_now="same",
        frame_before=None,
        frame_now=None,
    )
    assert reason == FRESH


def test_idle_animation_below_the_change_threshold_stays_fresh() -> None:
    before = _frame(_paint(1))
    after = _frame(_paint(1, idle=IDLE_PIXELS))
    assert before.pixels != after.pixels
    reason = staleness_reason(
        signature=_signature(digest="before"),
        owner_now=OWNER,
        mode_now=MODE,
        stability_now=SceneStability.STABLE.value,
        digest_now="after",
        frame_before=before,
        frame_now=after,
    )
    assert reason == FRESH


def test_a_repainted_scene_is_stale() -> None:
    reason = staleness_reason(
        signature=_signature(digest="before"),
        owner_now=OWNER,
        mode_now=MODE,
        stability_now=SceneStability.STABLE.value,
        digest_now="after",
        frame_before=_frame(_paint(1)),
        frame_now=_frame(_paint(9)),
    )
    assert reason == "the scene changed materially while the decision was pending"


def test_ownership_outranks_every_other_check() -> None:
    reason = staleness_reason(
        signature=_signature(digest="same"),
        owner_now="USER_CONTROL",
        mode_now=MODE,
        stability_now=SceneStability.STABLE.value,
        digest_now="same",
    )
    assert reason == "ownership changed from AI_CONTROL to USER_CONTROL"


def test_an_interaction_mode_change_is_stale_even_on_identical_pixels() -> None:
    reason = staleness_reason(
        signature=_signature(digest="same"),
        owner_now=OWNER,
        mode_now="BATTLE_ACTIVE",
        digest_now="same",
    )
    assert reason == "interaction mode changed from NON_BATTLE to BATTLE_ACTIVE"


def test_a_started_transition_is_stale() -> None:
    signature = _signature()
    assert transition_started(signature, SceneStability.TRANSIENT.value) is True
    reason = staleness_reason(
        signature=signature,
        owner_now=OWNER,
        mode_now=MODE,
        stability_now=SceneStability.TRANSIENT.value,
        digest_now="same",
    )
    assert reason == "scene stability changed from STABLE to TRANSIENT"


def test_a_transition_that_was_already_running_is_not_a_new_transition() -> None:
    signature = _signature(stability=SceneStability.TRANSIENT.value)
    assert transition_started(signature, SceneStability.TRANSIENT.value) is False


def test_a_structured_token_that_moved_on_is_stale() -> None:
    reason = staleness_reason(
        signature=_signature(token="map:1", digest="same"),
        owner_now=OWNER,
        mode_now=MODE,
        stability_now=SceneStability.STABLE.value,
        digest_now="same",
        token_now="map:2",
    )
    assert reason == "structured state advanced"


def test_a_missing_structured_token_does_not_invent_staleness() -> None:
    reason = staleness_reason(
        signature=_signature(token="", digest="same"),
        owner_now=OWNER,
        mode_now=MODE,
        digest_now="same",
        token_now="map:2",
    )
    assert reason == FRESH


def test_a_runtime_that_cannot_be_re_read_is_treated_as_fresh() -> None:
    """Permissive by design: a runtime with no peek keeps the pre-Patch-6 path.

    The loop refuses to reach this state with frames available; it short-circuits
    before calling in. Pinning it here keeps that contract explicit.
    """
    reason = staleness_reason(
        signature=_signature(digest="before"),
        owner_now=OWNER,
        mode_now=MODE,
        stability_now=SceneStability.STABLE.value,
        digest_now="after",
        frame_before=None,
        frame_now=None,
    )
    assert reason == FRESH


def test_a_settled_transition_is_also_treated_as_a_changed_scene() -> None:
    """Fail closed both ways: a scene that settled is not the scene reasoned on."""
    reason = staleness_reason(
        signature=_signature(stability=SceneStability.TRANSIENT.value, digest="same"),
        owner_now=OWNER,
        mode_now=MODE,
        stability_now=SceneStability.STABLE.value,
        digest_now="same",
    )
    assert reason == "scene stability changed from TRANSIENT to STABLE"


def test_the_signature_is_immutable() -> None:
    signature = _signature()
    with pytest.raises(FrozenInstanceError):
        signature.owner = "USER_CONTROL"  # type: ignore[misc]
