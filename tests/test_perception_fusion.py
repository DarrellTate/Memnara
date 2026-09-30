from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from memnara.perception.context import (
    PerceptionContext,
    StructuredFact,
    StructuredGameState,
    WindowState,
)
from memnara.perception.exceptions import PerceptionFusionError
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.models import SceneType, VisualObservation
from tests.support.synthetic import SyntheticSnapshot, wrap_snapshot


def _visual(**overrides) -> VisualObservation:
    data = dict(
        scene_type=SceneType.OVERWORLD,
        description="A room with furniture.",
        visible_text=(),
        entities=(),
        menu_visible=False,
        dialogue_visible=False,
        battle_visible=False,
        confidence=0.9,
        notable_changes="",
        source="VISUAL",
        model="qwen3-vl:8b",
    )
    data.update(overrides)
    return VisualObservation(**data)


def _snap(*, battle: int = 0) -> SyntheticSnapshot:
    return SyntheticSnapshot(is_in_battle=battle)


def test_fuse_visual_and_game_state() -> None:
    visual = _visual()
    state = wrap_snapshot(_snap())
    ctx = fuse(visual=visual, game_state=state)
    assert isinstance(ctx, PerceptionContext)
    assert ctx.visual is visual
    assert ctx.game_state is state
    assert ctx.window_state is None
    assert ctx.conflicts == ()
    assert "VISUAL" in ctx.metadata.sources
    assert "RAM" in ctx.metadata.sources


def test_visual_only() -> None:
    ctx = fuse(visual=_visual())
    assert ctx.visual is not None
    assert ctx.game_state is None
    assert ctx.conflicts == ()


def test_game_state_only() -> None:
    ctx = fuse(game_state=wrap_snapshot(_snap()))
    assert ctx.visual is None
    assert ctx.game_state is not None
    assert ctx.conflicts == ()


def test_visual_provenance_preserved() -> None:
    visual = _visual(source="VISUAL", confidence=0.42, notable_changes="", model="qwen3-vl:8b")
    ram = wrap_snapshot(_snap())
    ctx = fuse(visual=visual, game_state=ram)
    assert ctx.visual is visual
    assert ctx.visual.source == "VISUAL"
    assert ctx.visual.confidence == 0.42
    assert ctx.visual.model == "qwen3-vl:8b"
    assert ctx.visual.scene_type == SceneType.OVERWORLD


def test_ram_provenance_not_promoted() -> None:
    snap = _snap()
    wrapped = wrap_snapshot(snap)
    ctx = fuse(game_state=wrapped)
    assert ctx.game_state is not None
    assert ctx.game_state.is_in_battle_confidence == "SOURCE_DOCUMENTED"
    assert ctx.game_state.payload is snap
    assert snap.map_id_confidence == "VERIFIED"
    assert snap.is_in_battle_confidence == "SOURCE_DOCUMENTED"
    assert snap.mode_confidence == "INFERRED"
    assert snap.player_x_confidence == "SOURCE_DOCUMENTED"


def test_synthetic_edge_supplies_generic_facts() -> None:
    snap = _snap()
    wrapped = wrap_snapshot(snap)
    assert wrapped.payload is snap
    by_key = {fact.key: fact for fact in wrapped.facts}
    assert set(by_key) == {"map_id", "party_count", "mode"}
    assert by_key["map_id"].value == 12
    assert by_key["map_id"].confidence == "VERIFIED"
    assert by_key["map_id"].source == "RAM"
    assert by_key["map_id"].fairness == "PLAYER_AVAILABLE"
    assert by_key["party_count"].value == 0
    assert by_key["party_count"].confidence == "SOURCE_DOCUMENTED"
    assert by_key["mode"].value == "OVERWORLD"
    assert by_key["mode"].confidence == "INFERRED"


def test_fact_confidence_is_copied_not_replaced() -> None:
    snap = replace(
        _snap(),
        map_id_confidence="INFERRED",
        party_count_confidence="UNVERIFIED",
        mode_confidence="SOURCE_DOCUMENTED",
    )
    wrapped = wrap_snapshot(snap)
    by_key = {fact.key: fact for fact in wrapped.facts}
    assert by_key["map_id"].confidence == "INFERRED"
    assert by_key["party_count"].confidence == "UNVERIFIED"
    assert by_key["mode"].confidence == "SOURCE_DOCUMENTED"


def test_generic_fusion_has_no_emulator_or_payload_inspection() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "memnara" / "perception"
    forbidden = (
        "pyboy",
        'getattr(payload',
    )
    for name in ("fusion.py", "context.py", "conflicts.py", "exceptions.py"):
        text = (root / name).read_text(encoding="utf-8")
        lowered = text.lower()
        for token in forbidden:
            assert token not in lowered, f"{name} must not contain {token!r}"
        assert '"map_id"' not in text
        assert '"party_count"' not in text
        assert '"mode"' not in text


def test_agreeing_battle_no_conflict() -> None:
    visual = _visual(battle_visible=False)
    state = wrap_snapshot(_snap(battle=0))
    ctx = fuse(visual=visual, game_state=state)
    assert ctx.conflicts == ()
    visual_in = _visual(battle_visible=True, scene_type=SceneType.BATTLE, description="A battle.")
    ctx_in = fuse(visual=visual_in, game_state=wrap_snapshot(_snap(battle=1)))
    assert ctx_in.conflicts == ()
    assert ctx_in.game_state is not None and ctx_in.game_state.is_in_battle is True


def test_disagreeing_battle_records_conflict() -> None:
    visual = _visual(battle_visible=True, scene_type=SceneType.BATTLE, description="A battle screen.")
    snap = _snap(battle=0)
    state = wrap_snapshot(snap)
    ctx = fuse(visual=visual, game_state=state)
    assert len(ctx.conflicts) == 1
    item = ctx.conflicts[0]
    assert item.concept == "battle"
    assert item.left_source == "VISUAL"
    assert item.left_value == "true"
    assert item.right_source == "RAM"
    assert item.right_value == "false"
    assert ctx.visual is visual
    assert ctx.game_state is state
    assert ctx.visual.battle_visible is True
    assert ctx.game_state.is_in_battle is False
    assert snap.is_in_battle == 0

    visual_out = _visual(battle_visible=False)
    snap_in = _snap(battle=1)
    ctx_rev = fuse(visual=visual_out, game_state=wrap_snapshot(snap_in))
    assert len(ctx_rev.conflicts) == 1
    assert ctx_rev.conflicts[0].left_value == "false"
    assert ctx_rev.conflicts[0].right_value == "true"
    text = compact_summary(ctx_rev)
    assert "CONFLICTS:" in text
    assert "battle:" in text
    assert "VISUAL=false" in text
    assert "RAM=true" in text


def test_unknown_scene_does_not_fabricate_map_conflict() -> None:
    visual = _visual(scene_type=SceneType.UNKNOWN, battle_visible=False, description="A room.")
    snap = _snap(battle=0)
    ctx = fuse(visual=visual, game_state=wrap_snapshot(snap))
    assert ctx.conflicts == ()
    assert snap.map_id_confidence == "VERIFIED"
    assert snap.mode_confidence == "INFERRED"


def test_unknown_scene_explicit_battle_disagreement_is_conflict() -> None:
    visual = _visual(scene_type=SceneType.UNKNOWN, battle_visible=False, description="A room.")
    snap = _snap(battle=1)
    ctx = fuse(visual=visual, game_state=wrap_snapshot(snap))
    assert visual.scene_type is SceneType.UNKNOWN
    assert visual.battle_visible is False
    assert ctx.game_state is not None and ctx.game_state.is_in_battle is True
    assert len(ctx.conflicts) == 1
    item = ctx.conflicts[0]
    assert item.concept == "battle"
    assert item.left_source == "VISUAL"
    assert item.left_value == "false"
    assert item.right_source == "RAM"
    assert item.right_value == "true"
    assert ctx.visual is visual
    assert snap.is_in_battle == 1


def test_absent_battle_signal_no_conflict() -> None:
    visual = _visual(battle_visible=True)
    opaque = StructuredGameState(source="RAM", adapter_id="x", is_in_battle=None, payload=None)
    ctx = fuse(visual=visual, game_state=opaque)
    assert ctx.conflicts == ()
    ctx_visual_only = fuse(visual=visual)
    assert ctx_visual_only.conflicts == ()
    assert compact_summary(ctx_visual_only).startswith("VISUAL:")
    assert "GAME_STATE: absent" in compact_summary(ctx_visual_only)


def test_does_not_mutate_sources() -> None:
    visual = _visual(battle_visible=True, description="A battle screen.")
    snap = _snap(battle=0)
    wrapped = wrap_snapshot(snap)
    ctx = fuse(visual=visual, game_state=wrapped)
    assert ctx.visual is visual
    assert ctx.game_state is wrapped
    assert ctx.game_state.payload is snap
    assert visual.battle_visible is True
    assert snap.is_in_battle == 0
    assert snap.is_in_battle_confidence == "SOURCE_DOCUMENTED"


def test_compact_summary_is_source_labeled() -> None:
    visual = _visual(description="Indoor room; no dialogue.")
    snap = _snap()
    wrapped = wrap_snapshot(snap)
    ctx = fuse(visual=visual, game_state=wrapped)
    text = compact_summary(ctx)
    assert text == compact_summary(ctx)
    assert "VISUAL:" in text
    assert "source=VISUAL" in text
    assert "GAME_STATE:" in text
    assert "source=RAM" in text
    assert "CONFLICTS: none" in text
    assert "GAME_STATE_MAP_ID: 12 [VERIFIED] source=RAM" in text
    assert "GAME_STATE_PARTY_COUNT: 0 [SOURCE_DOCUMENTED] source=RAM" in text
    assert "GAME_STATE_MODE: OVERWORLD [INFERRED] source=RAM" in text
    assert ctx.game_state is not None and ctx.game_state.payload is snap
    assert ctx.metadata.fusion == "deterministic"


def test_compact_summary_renders_opaque_facts() -> None:
    facts = (
        StructuredFact(key="window_title", value="Demo", source="WINDOW", confidence="INFERRED"),
    )
    marker = object()
    state = StructuredGameState(
        source="WINDOW",
        adapter_id="demo",
        facts=facts,
        payload=marker,
    )
    text = compact_summary(fuse(game_state=state))
    assert "GAME_STATE_WINDOW_TITLE: Demo [INFERRED] source=WINDOW" in text
    assert "GAME_STATE_MAP_ID" not in text
    fused = fuse(game_state=state)
    assert fused.game_state is not None and fused.game_state.payload is marker


def test_compact_summary_does_not_inspect_payload() -> None:
    snap = _snap()
    state = StructuredGameState(
        source="RAM",
        adapter_id="x",
        is_in_battle=False,
        is_in_battle_confidence="SOURCE_DOCUMENTED",
        facts=(),
        payload=snap,
    )
    fused = fuse(game_state=state)
    text = compact_summary(fused)
    assert fused.game_state is not None and fused.game_state.payload is snap
    assert "GAME_STATE_MAP_ID" not in text
    assert "GAME_STATE_PARTY_COUNT" not in text
    assert "GAME_STATE_MODE" not in text


def test_non_zero_battle_bytes() -> None:
    for raw in (1, 2, 0xFF):
        wrapped = wrap_snapshot(_snap(battle=raw))
        assert wrapped.is_in_battle is True
        assert wrapped.is_in_battle_confidence == "SOURCE_DOCUMENTED"


def test_rejects_malformed_and_empty_input() -> None:
    with pytest.raises(PerceptionFusionError):
        fuse()
    with pytest.raises(PerceptionFusionError):
        fuse(visual=None, game_state=None, window_state=None)
    with pytest.raises(PerceptionFusionError):
        fuse(visual=object())  # type: ignore[arg-type]
    with pytest.raises(PerceptionFusionError):
        fuse(game_state=_snap())  # type: ignore[arg-type]
    with pytest.raises(PerceptionFusionError):
        fuse(visual=_visual(), window_state=object())  # type: ignore[arg-type]


def test_window_state_slot_exists_but_unused() -> None:
    ctx = fuse(visual=_visual(), window_state=None)
    assert ctx.window_state is None
    reserved = WindowState()
    ctx2 = fuse(visual=_visual(), window_state=reserved)
    assert ctx2.window_state is reserved
    assert ctx2.window_state.source == "WINDOW"
