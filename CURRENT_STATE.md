# Memnara current state

```text
LAST APPROVED MILESTONE: 6
CURRENT WORK: none
MILESTONE 6: COMPLETE / APPROVED
POST-M6 VALIDATION PATCH: COMPLETE / APPROVED
MILESTONE 7 AUTHORIZED: NO
APPLICATION IMPLEMENTATION: M6 GENERIC BATTLE HANDLING
ADR-001–ADR-008: ACCEPTED
```

```text
M0–M6 COMPLETE / APPROVED
POST-M6 VALIDATION PATCH COMPLETE / APPROVED
M7 AUTHORIZED NO
```

Milestones 0–6 are complete and approved. Milestone 6 is generic battle handling on the bounded VISION + INPUT loop. Live battle proof was deferred and accepted. The post-M6 hands-on validation patch is complete and approved. It is not a new milestone. ADR-008 is accepted architecture and does not authorize memory, RAG, UI, or M7 implementation.

Public core: generic VISION + INPUT + PyBoy + M3 vision + M4 fusion + M5 bounded autonomy + M6 generic battle handling. Enhanced structured-state adapters are local/private.

```text
CURRENT IMPLEMENTATION

PyBoy
optional local GameAdapter (not in public repo)
M3 local VLM vision
M4 source-aware perception fusion
M5 bounded autonomous control loop
M6 generic battle interaction mode on that loop
```

```text
FUTURE PRODUCT SCOPE

multiple emulator platforms
native PC runtime
capability-advertised providers
generic vision + input play
optional game-specific integration
cross-runtime profile continuity
```

SNES, PS1, DuckStation, and native Windows gameplay are **not** built.

Public core is separated from commercial-title integration packs.

## Directory locks

Canonical workspace paths:

| Role | Canonical path |
|---|---|
| Source | `D:\Memnara` |
| Runtime / generated data | `D:\Memnara-Data` |
| Operator ROM (read-only, not in Git) | `D:\Memnara_Roms\reference.gb` |
| Private local integrations | `D:\Memnara-Integrations` |
| Ollama models used by Memnara | `D:\Ollama\models` |
| Misty (off-limits) | `E:\AI\.ollama\models` |

Historical live validation evidence is retained in the private development archive. Do not move or delete that archive as part of application work.

Tracked `/docs` in Git is engineering knowledge, not runtime data and not a shipped application bundle.

## Storage

| Item | Value |
|---|---|
| D: free at M5 | ≈ 64.9 GB (verified after live evidence write) |
| Safety reserve | 10–15 GB |
| Autonomy evidence default | `D:\Memnara-Data\autonomy\` |

## Decisions

ADR-001 through ADR-008 are **ACCEPTED**.

## First hands-on UX baseline

Recorded from the first hands-on M5 run on the generic public VISION + INPUT path. Do not overwrite this baseline with later results. That run advanced an in-game dialogue sequence. Observed normal post-warmup cadence was roughly several seconds per action. The first visual inference was substantially slower.

```text
Basic perception           GOOD
Action choice              GOOD
Progress awareness         GOOD
Safety/bounded execution   GOOD
Reason explainability      GOOD

Visual classification      NEEDS WORK
Reasoning efficiency       NEEDS WORK
Interaction speed          BIGGEST PROBLEM
User observability         NEEDS WORK
Agent-like behavior        TOO EARLY TO JUDGE
```

M6 comparison is in [docs/milestones/m6-battle-handling.md](docs/milestones/m6-battle-handling.md). It does not replace this baseline.

## Post-M6 hands-on observations

Recorded from the first real post-M6 run. This section does not replace the baseline above.

```text
POST-M6 HANDS-ON OBSERVATIONS

Basic perception
  GOOD for obvious dialogue
  WEAK for spatial environments

Action choice
  GOOD for obvious interaction
  MIXED for navigation

Progress awareness
  NEEDS INVESTIGATION
  observed screen_changed=False/state_changed=False with progress=True

Safety/bounded execution
  GOOD

Reason explainability
  GOOD

Visual classification
  NEEDS WORK

Reasoning efficiency
  NEEDS WORK

Interaction speed
  BIGGEST PROBLEM

User observability
  BIG PROBLEM
  operator cannot currently watch the controlled game instance

Agent-like behavior
  EARLY / MIXED
```

The operator opened one emulator and Memnara started another. Those were different processes, so the visible window was not the instance receiving actions.

After the post-M6 validation patch, `--show-window` shows the PyBoy window of the same in-process instance Memnara controls. The historical finding stands: before that flag, the operator could not watch the controlled instance. Default runs stay headless.

Progress awareness: that `progress=True` result was a bug. With no structured token, the visual-only fingerprint included the model's free-form description, so rephrasing an unchanged framebuffer counted as progress. The patch no longer treats that wording change as progress. Spatial scene understanding remains product-quality debt. This patch does not add mapping, pathfinding, or working memory.

## Open debts

1. Coordinate/facing movement not experimentally proven (M2 private integration).
2. Party/HP/money/badges not UI-compared (M2 private integration).
3. Battery RAM playthrough `stop(save=True)` still future work.
4. VLM often returns `scene_type=UNKNOWN` even when description is usable.
5. START capture was **UNUSABLE AS MENU VALIDATION** (menu scene not established). Battle/party screens not reached. Boot sample was `MENU` misclassification, not `UNKNOWN`.
6. `qwen3-vl:8b` places structured JSON in `message.thinking` while `content` is empty (`think: false`).
7. Fusion compares only explicit battle flags (`battle_visible` vs `is_in_battle`), including when `scene_type=UNKNOWN`; no menu/mode/map conflict heuristics.
8. M5 live play is inefficient (walls, accidental menus). Cadence is vision+reasoning per step, typically several seconds.

Non-blocking M6 debt. Do not treat these as authorization to broaden Milestone 6:

9. Centralize the duplicated `"battle"` conflict label between fusion and the battle view when a later cleanup is authorized.
10. Record `confirm_execution` exceptions on the step instead of aborting the loop.
11. Review battle-view fields that are derived and not read by the loop.
12. Spatial visual understanding is weak. Mapping, pathfinding, and navigation memory are out of scope until a later authorization.
