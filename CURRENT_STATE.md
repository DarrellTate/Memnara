# Memnara current state

```text
LAST APPROVED MILESTONE: 5
CURRENT WORK: 6
MILESTONE 5 STATUS: COMPLETE / APPROVED
MILESTONE 6: IMPLEMENTED / AWAITING CHATGPT REVIEW
MILESTONE 6 AUTHORIZED: YES
MILESTONE 7 AUTHORIZED: NO
APPLICATION IMPLEMENTATION: M6 GENERIC BATTLE HANDLING
ADR-001–ADR-008: ACCEPTED
```

```text
M0–M5 COMPLETE / APPROVED
M6 IMPLEMENTED / AWAITING CHATGPT REVIEW
M7 AUTHORIZED NO
```

Milestones 0–5 are complete and approved. Milestone 6 generic battle handling is implemented and awaiting ChatGPT review. It is not approved complete. ADR-008 is accepted architecture and does not authorize memory, RAG, UI, or M7 implementation.

Public core: generic VISION + INPUT + PyBoy + M3 vision + M4 fusion + M5 bounded autonomy. Enhanced structured-state adapters are local/private.

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

## Open debts

1. Coordinate/facing movement not experimentally proven (M2 private integration).
2. Party/HP/money/badges not UI-compared (M2 private integration).
3. Battery RAM playthrough `stop(save=True)` still future work.
4. VLM often returns `scene_type=UNKNOWN` even when description is usable.
5. START capture was **UNUSABLE AS MENU VALIDATION** (menu scene not established). Battle/party screens not reached. Boot sample was `MENU` misclassification, not `UNKNOWN`.
6. `qwen3-vl:8b` places structured JSON in `message.thinking` while `content` is empty (`think: false`).
7. Fusion compares only explicit battle flags (`battle_visible` vs `is_in_battle`), including when `scene_type=UNKNOWN`; no menu/mode/map conflict heuristics.
8. M5 live play is inefficient (walls, accidental menus). Cadence is vision+reasoning per step, typically several seconds.
