# Memnara current state

```text
LAST APPROVED MILESTONE: 6
CURRENT WORK: Post-M6 Patch #3 awaiting ChatGPT review
MILESTONE 6: COMPLETE / APPROVED
POST-M6 PATCH #1: COMPLETE / APPROVED
POST-M6 PATCH #2: COMPLETE / APPROVED
POST-M6 PATCH #3: IMPLEMENTED / AWAITING CHATGPT REVIEW
MILESTONE 7 AUTHORIZED: NO
APPLICATION IMPLEMENTATION: M6 GENERIC BATTLE HANDLING
ADR-001–ADR-008: ACCEPTED
```

```text
M0–M6 COMPLETE / APPROVED
POST-M6 PATCH #1 COMPLETE / APPROVED
POST-M6 PATCH #2 COMPLETE / APPROVED
POST-M6 PATCH #3 IMPLEMENTED / AWAITING CHATGPT REVIEW
M7 AUTHORIZED NO
```

Milestones 0–6 are complete and approved. Milestone 6 is generic battle handling on the bounded VISION + INPUT loop. Live battle proof was deferred and accepted. The first post-M6 validation patch is complete and approved. The second post-M6 patch, movement outcome and stuck recovery, is complete and approved. The third post-M6 patch, transition-state recovery, is implemented and awaiting ChatGPT review. None of these patches is a new milestone. ADR-008 is accepted architecture and does not authorize memory, RAG, UI, or M7 implementation.

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

Progress awareness: that `progress=True` result was a bug. With no structured token, the visual-only fingerprint included the model's free-form description, so rephrasing an unchanged framebuffer counted as progress. The first patch no longer treats that wording change as progress. Spatial scene understanding remains product-quality debt. That patch does not add mapping, pathfinding, or working memory.

A later hands-on run showed a second failure. Directional movement bumped into obstacles. The framebuffer changed because of the walking or collision animation, and the loop recorded `screen_changed=True` with `progress=True` and `stuck_state=NORMAL`.

```text
Screen-level visual change was insufficient to determine navigation success.
Repeated collision animations caused false progress and prevented stuck recovery.
```

The second patch keeps `screen_changed` separate from a movement outcome (`MOVED`, `BLOCKED`, `UNCERTAIN`, `NOT_APPLICABLE`) derived from the before/after observations already collected. A clear scene shift is `MOVED`. An unchanged whole frame, or an equal structured navigation token, is `BLOCKED`. A stable border with a center-only change is `UNCERTAIN` and is not progress. Repeated uncertain attempts still feed the existing stuck detector. This patch is complete and approved. It does not add a map, pathfinding, or working memory.

A later hands-on run lost a battle entry during the fade. The finding stands:

```text
Temporary scene-transition frames caused false stuck escalation.
A battle-entry fade reached INTERVENTION_REQUIRED before the battle scene stabilized.
```

The same run showed the controlled emulator lagging while the model was thinking, including during fades where no gameplay input was required. Traced in the public loop: a frame advances only inside `GameBoyActionExecutor.execute` (button delay plus settle ticks, or `WAIT` ticks). `observe` and `propose` do not tick, so the in-process PyBoy stays frozen for the whole vision and reasoning call.

Post-M6 Patch #3 is implemented and awaiting review. It does not replace the scorecards above. A near-black or near-uniform frame is `TRANSIENT`. A dark scene that still has structure stays `STABLE`. Black is not treated as a battle. While the scene stays transient, and Memnara has gameplay ownership, the same emulator advances a bounded number of frames with no button held, then one vision call runs on the resulting frame. The default budget is 120 frames, re-checked every 8. A stable frame clears that budget. After it is spent, the existing stuck detector runs again. A proposal other than `WAIT` is not executed on a frame that is still transient. Those advanced frames are not `MOVE`, `PRESS`, or `WAIT`. A scene-wide change after a move is `UNCERTAIN`, not `MOVED`. `--show-window` still shows that same instance, and passive ticks render it.

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
13. A fixed-camera step that stays inside the central window is `UNCERTAIN`. It is not called `BLOCKED`, and it is not called a successful move, until a scene shift or a structured navigation token is available. No map was added.
