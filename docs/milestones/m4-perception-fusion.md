# Milestone 4 — Perception fusion

**Status:** COMPLETE / APPROVED

M4 is deterministic, source-aware fusion. It does not call Ollama, does not execute actions, and does not schedule vision (`FrameChangeDetector` stays outside `observe()`).

## Current vs future

```text
CURRENT PATH
VisualObservation (M3) + optional StructuredGameState (from a local GameAdapter)

GENERIC REQUIREMENT
RAM absence is normal. Future native play is VISION + INPUT (optional WINDOW_STATE later).
```

## Architecture

```text
VisionProvider.observe()     → VisualObservation (source=VISUAL)
GameAdapter.get_state()      → adapter snapshot payload
adapter structured helper    → StructuredGameState + facts
        ↓
fuse()   deterministic, no model
        ↓
PerceptionContext
```

| Piece | Location |
|---|---|
| Context types | `src/memnara/perception/context.py` |
| Conflicts | `src/memnara/perception/conflicts.py` |
| Fusion | `src/memnara/perception/fusion.py` |
| Title-specific mapping | private local GameAdapter (not in this repository) |

Generic fusion does not import PyBoy, title-specific address tables, or a concrete adapter snapshot type. It does not inspect payload attribute names.

## Sources

- **visual:** existing `VisualObservation` retained by reference. `source=VISUAL` is not rewritten.
- **game_state:** optional `StructuredGameState`. The game/runtime edge supplies `facts` (`StructuredFact` key/value/source/confidence, optional fairness). The original adapter payload is retained by identity. Fusion does not inspect payload attributes and does not promote confidence.
- **window_state:** optional `WindowState` slot for M20. M4 does not populate native window metadata.

At least one source is required. Empty `fuse()` raises `PerceptionFusionError`.

## Trust policy

Fusion organizes evidence. It does **not** apply “RAM always wins” or “vision always wins.”

- Exact map identity remains a VERIFIED RAM fact chosen by a local GameAdapter (`facts` + original payload); a VLM room description is complementary, not a map_id overwrite.
- `scene_type=UNKNOWN` does not fabricate a conflict with RAM mode/map.
- `battle_visible` is explicit evidence independently of `scene_type`. `UNKNOWN` plus `battle_visible=False` vs RAM `is_in_battle=True` is a battle conflict. No scene-confidence heuristic.
- Screen-only facts (visible text, layout) stay visual.

## Conflicts (conservative)

Only **battle** is compared when both sides are explicit:

```text
visual.battle_visible  vs  StructuredGameState.is_in_battle
```

Agree → no conflict. Disagree → one `PerceptionConflict`; both original values remain on the context. Missing visual, missing game state, or `is_in_battle is None` → no conflict. `scene_type` is not an input to this comparison.

A local adapter may map a battle-flag byte (`0` → not in battle; any other int → in battle). Confidence stays `SOURCE_DOCUMENTED`. That mapping is not part of generic fusion.

## Compact summary

`compact_summary(context)` is deterministic text, source-labeled, for later M5 reasoning. Not an LLM call. Extra `GAME_STATE_<KEY>` lines are rendered from `StructuredGameState.facts` in order. A local adapter currently may select generic keys such as `map_id`, `party_count`, and `mode`; generic fusion iterates those facts and does not hard-code title-specific names.

## Out of scope

No autonomy, planning, UI, voice, memory, native capture, new RAM, or extra VLM calls.
