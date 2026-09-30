"""Deterministic source-aware fusion. No model calls. No gameplay actions."""

from __future__ import annotations

from memnara.perception.conflicts import PerceptionConflict
from memnara.perception.context import (
    PerceptionContext,
    PerceptionMetadata,
    StructuredFact,
    StructuredGameState,
    WindowState,
)
from memnara.perception.exceptions import PerceptionFusionError
from memnara.perception.vision.models import VisualObservation


def fuse(
    *,
    visual: VisualObservation | None = None,
    game_state: StructuredGameState | None = None,
    window_state: WindowState | None = None,
) -> PerceptionContext:
    """Combine available observations. Absence of RAM/window is normal. Does not mutate inputs."""
    if visual is not None and not isinstance(visual, VisualObservation):
        raise PerceptionFusionError("visual must be VisualObservation or None")
    if game_state is not None and not isinstance(game_state, StructuredGameState):
        raise PerceptionFusionError("game_state must be StructuredGameState or None")
    if window_state is not None and not isinstance(window_state, WindowState):
        raise PerceptionFusionError("window_state must be WindowState or None")
    if visual is None and game_state is None and window_state is None:
        raise PerceptionFusionError("at least one of visual, game_state, or window_state is required")

    sources: list[str] = []
    if visual is not None:
        sources.append(visual.source or "VISUAL")
    if game_state is not None:
        sources.append(game_state.source or "RAM")
    if window_state is not None:
        sources.append(window_state.source or "WINDOW")

    conflicts = _battle_conflicts(visual, game_state)
    return PerceptionContext(
        visual=visual,
        game_state=game_state,
        window_state=window_state,
        conflicts=conflicts,
        metadata=PerceptionMetadata(sources=tuple(sources)),
    )


def compact_summary(context: PerceptionContext) -> str:
    """Deterministic, source-labeled text for later reasoning. Not an LLM summary."""
    lines: list[str] = []
    visual = context.visual
    if visual is None:
        lines.append("VISUAL: absent")
    else:
        lines.append(
            f"VISUAL: {visual.description}; scene={visual.scene_type.value}; "
            f"menu={visual.menu_visible}; dialogue={visual.dialogue_visible}; "
            f"battle_visible={visual.battle_visible}; confidence={visual.confidence:.2f}; "
            f"source={visual.source}"
        )
        if visual.visible_text:
            lines.append("VISUAL_TEXT: " + "; ".join(visual.visible_text))
        if visual.notable_changes:
            lines.append(f"VISUAL_NOTABLE_CHANGES: {visual.notable_changes}")

    state = context.game_state
    if state is None:
        lines.append("GAME_STATE: absent")
    else:
        battle = "unknown" if state.is_in_battle is None else str(state.is_in_battle).lower()
        conf = state.is_in_battle_confidence or "unspecified"
        adapter = state.adapter_id or "generic"
        lines.append(
            f"GAME_STATE: adapter={adapter}; battle={battle} [{conf}]; source={state.source}"
        )
        lines.extend(_fact_summary_lines(state.facts))

    if context.window_state is None:
        lines.append("WINDOW_STATE: absent")
    else:
        lines.append(f"WINDOW_STATE: source={context.window_state.source}")

    if context.conflicts:
        lines.append("CONFLICTS:")
        for item in context.conflicts:
            lines.append(
                f"- {item.concept}: {item.left_source}={item.left_value} vs "
                f"{item.right_source}={item.right_value} ({item.category})"
            )
    else:
        lines.append("CONFLICTS: none")
    return "\n".join(lines)


def _battle_conflicts(
    visual: VisualObservation | None,
    game_state: StructuredGameState | None,
) -> tuple[PerceptionConflict, ...]:
    if visual is None or game_state is None:
        return ()
    if game_state.is_in_battle is None:
        return ()
    visual_battle = visual.battle_visible
    ram_battle = game_state.is_in_battle
    if visual_battle == ram_battle:
        return ()
    return (
        PerceptionConflict(
            concept="battle",
            left_source=visual.source or "VISUAL",
            left_value=str(visual_battle).lower(),
            right_source=game_state.source or "RAM",
            right_value=str(ram_battle).lower(),
        ),
    )


def _fact_summary_lines(facts: tuple[StructuredFact, ...]) -> list[str]:
    """Render adapter-supplied facts. Keys are opaque; this layer does not select them."""
    lines: list[str] = []
    for fact in facts:
        conf_text = fact.confidence or "unspecified"
        src_text = fact.source or "RAM"
        lines.append(f"GAME_STATE_{fact.key.upper()}: {fact.value} [{conf_text}] source={src_text}")
    return lines
