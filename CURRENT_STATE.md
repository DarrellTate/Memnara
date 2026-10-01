# Memnara current state

```text
LAST APPROVED MILESTONE: 6
CURRENT WORK: none
MILESTONE 6: COMPLETE / APPROVED
POST-M6 PATCH #1: COMPLETE / APPROVED
POST-M6 PATCH #2: COMPLETE / APPROVED
POST-M6 PATCH #3: COMPLETE / APPROVED
POST-M6 PATCH #4: COMPLETE / APPROVED
POST-M6 PATCH #5: COMPLETE / APPROVED
POST-M6 PATCH #6: COMPLETE / APPROVED
MILESTONE 7 AUTHORIZED: NO
APPLICATION IMPLEMENTATION: M6 GENERIC BATTLE HANDLING
ADR-001–ADR-008: ACCEPTED
```

```text
M0–M6 COMPLETE / APPROVED
POST-M6 PATCH #1 COMPLETE / APPROVED
POST-M6 PATCH #2 COMPLETE / APPROVED
POST-M6 PATCH #3 COMPLETE / APPROVED
POST-M6 PATCH #4 COMPLETE / APPROVED
POST-M6 PATCH #5 COMPLETE / APPROVED
POST-M6 PATCH #6 COMPLETE / APPROVED
M7 AUTHORIZED NO
```

Milestones 0–6 are complete and approved. Milestone 6 is generic battle handling on the bounded VISION + INPUT loop. Live battle proof was deferred and accepted. The first post-M6 validation patch is complete and approved. The second post-M6 patch, movement outcome and stuck recovery, is complete and approved. The third post-M6 patch, transition-state recovery, is complete and approved. The fourth post-M6 patch, interaction outcome and decision latency, is complete and approved. The fifth post-M6 patch, passive runtime progression, is complete and approved. The sixth post-M6 patch, continuous runtime with asynchronous decisions, is complete and approved. None of these patches is a new milestone. ADR-008 is accepted architecture and does not authorize memory, RAG, UI, or M7 implementation.

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

Post-M6 Patch #3 is complete and approved. It does not replace the scorecards above. A near-black or near-uniform frame is `TRANSIENT`. A dark scene that still has structure stays `STABLE`. Black is not treated as a battle. While the scene stays transient, and Memnara has gameplay ownership, the same emulator advances a bounded number of frames with no button held, then one vision call runs on the resulting frame. The default budget is 120 frames, re-checked every 8. A stable frame clears that budget. After it is spent, the existing stuck detector runs again. A proposal other than `WAIT` is not executed on a frame that is still transient. Those advanced frames are not `MOVE`, `PRESS`, or `WAIT`. A scene-wide change after a move is `UNCERTAIN`, not `MOVED`. `--show-window` still shows that same instance, and passive ticks render it.

```text
POST-M6 HANDS-ON FINDING

Battle activation and transition recovery now work live.

Battle-menu perception is good, but Memnara repeatedly invented button semantics and treated unchanged menu interactions as progress.

Interaction speed remains the largest UX problem, with stable AI action cadence still commonly measured in several seconds.
```

That finding does not replace the scorecards above. An unchanged stable menu press is now `interaction=NO_EFFECT` and `progress=False`. Recent history shows that outcome. The same stuck detector can escalate repeated no-effect presses. A later change that advances the menu clears that escalation. Button names are not given fixed meanings.

A stable framebuffer that matches the previous stable reading reuses that vision result. A different framebuffer calls the vision model again. Reasoning still runs on a stable step, because another safe action may still be available. `--timing-details` prints the per-step split. The default CLI adds `interaction=` and does not print the timing split.

```text
POST-M6 HANDS-ON FINDING

The visible emulator still advanced in chunks after model-call optimization.

Root cause:
the PyBoy runtime remains frozen during normal perception and reasoning and only advances during executor/runtime tick paths.

Patch #3 improved transient scenes only; stable automatic animation remained coupled to the AI decision loop.
```

That finding does not replace the scorecards above. `DecisionReadiness` is separate from scene stability. A stable frame whose pixels keep changing with no button held is `PASSIVE_PROGRESS`. The same runtime then advances in bounded chunks, comparing framebuffers and not calling the vision model per frame. When the picture settles, readiness is `INPUT_REQUIRED` and the normal decision runs once. A frame that is still changing when the budget ends is still shown to the reasoner. `PAUSED`, `USER_CONTROL`, `CONVERSATION`, and dry-run do not take those ticks. If the live frame changes after a proposal and before execute, the proposal is dropped. `--timing-details` adds model-wait time, passive-runtime time, progression frames, and emulated-frame throughput. A decision that still needs a model can take several seconds. This patch does not make gameplay real-time.

```text
POST-M6 HANDS-ON FINDING

Multiple hands-on recordings showed multi-second complete runtime freezes during model inference in both battle and overworld play.

Patch #5 reduced unnecessary model calls but did not solve decision-time runtime starvation.

Patch #6 decouples runtime progression/rendering from model inference while using snapshot/version freshness checks to prevent stale actions.
```

That finding does not replace the scorecards above. One runtime owner thread now performs every emulator call: open, tick, capture, press, release, and close. It publishes immutable snapshots with an observation id, a digest, and a runtime frame count. Perception and reasoning read those snapshots on the agent thread, so a slow local model no longer stops the clock. The agent submits at most one validated action to a one-slot command queue, and the owner thread applies it. Every advanced frame is paced toward a target cadence, 60 emulated frames per second by default, so input application does not sprint ahead of normal game time.

Before executing, the loop checks ownership and then semantic freshness against the observation it reasoned from. An idle animation on an equivalent scene still executes. An ownership change, a started transition, an unreadable frame, or a material scene change drops the proposal and records it as stale. Headless stays the default, `--show-window` still shows that same instance, and `--step-runtime` keeps the Patch #5 frame-stepped path available. `--timing-details` adds the observation id, proposal age, frames elapsed since the observation, and dropped stale proposals.

Synthetic measurement with three seconds of model latency on one decision: the longest runtime freeze fell from 3004 ms to 47 ms, emulated frames advanced during inference rose from 24 to 294, and effective cadence went from 5.3 to 60.3 emulated frames per second with identical vision and reasoning call counts. That harness is local and not committed. The live equivalent is committed as integration tests that skip without the operator ROM: against real headless PyBoy, three seconds of latency advanced 180 frames at 60.0 effective emulated frames per second with a 34 ms longest freeze, every emulator call came from the owner thread, one action emulated exactly the 24 settle frames PyBoy itself counted, and shutdown released every button while the adapter was still open. A visible SDL2 window showed the same ownership and published new frames. This patch does not make model decisions fast. It stops them from stopping the game.

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
14. Transition near-black and near-uniform thresholds, and the 120-frame / 8-frame grace budget, are accepted implementation-level tuning for future runtimes. They are not a blocker and do not authorize a loading-screen system.
15. The visual fingerprint still includes the free-form caption and scene type. A rephrased quote on an unchanged frame is `NO_EFFECT` and is not progress. The unchanged-fingerprint stuck counter may not see that rephrase. The same-action counter still escalates a repeated no-effect press.
16. Passive progression uses a pixel-change threshold and a 180-frame / 8-frame budget with a 5-second hang guard. Motion under the threshold does not keep the clock running. Motion above it can consume the budget before the next decision, including a small repeating animation on an otherwise actionable scene. That tuning is not a second stuck detector and does not authorize a background emulator thread. The runtime owner thread added later came from a separate Patch #6 authorization.
17. Semantic freshness uses the same pixel-change threshold as passive progression. An animation above that threshold drops a proposal that a person would still consider valid, and a scene change below it is treated as equivalent. Generic VISION does not re-read the scene during the freshness check, so a battle starting or ending is caught as a material frame change rather than as a battle-mode change. Structured-state observers that implement `confirm_execution` still trip the mode check.
18. Snapshot granularity is the 2-frame runtime chunk, so the shortest observable publish gap is about 33 ms plus OS scheduling jitter.
19. Exact-digest perception reuse hits less often while the runtime keeps moving, because a live scene changes pixels. Per-observation model-call counts are unchanged, and no extra call per step was added.
20. The continuous runtime paces frames with sleeps because the PyBoy adapter runs unthrottled. Cadence is approximate, not frame-locked, and a loaded machine falls behind the target rather than catching up.
21. `from memnara.config import ...` as the first import in a process hits a pre-existing package import cycle through `memnara.perception`. Importing `memnara.agent` first avoids it. This predates Patch #6 and is not fixed here.
22. `CONTINUOUS` is used in code as a capability-like name and is not in the ADR-007 catalog. ChatGPT left this non-blocking: do not amend ADR-007 for Patch #6. Continuous progression may be a runtime scheduling/property concern rather than a capability equivalent to FRAME_STEPPING, INPUT, or VISION. That is a later architecture decision.
23. The owner thread repeats the ownership check before moving a button, but it cannot judge semantic freshness. Semantic validation stays on the agent side, before submit.
24. `stale_proposals_dropped` is a run-long running total, so it climbs across steps rather than reporting one step. The evidence key is named `stale_proposals_dropped_total` and the CLI field matches.
25. `RuntimeActionExecutor.release_all` is a no-op, because input release belongs to the owner thread inside the command. The agent loop's own release in its `finally` therefore does nothing in continuous mode. Release still happens, on runtime shutdown and on a failed command.
26. `should_advance` and `can_apply_input` are independent predicates. A frozen runtime still accepts input unless the caller also refuses it through `can_apply_input`. The demo wires PAUSED to both; another caller must do so deliberately.
27. Cancelling a timed-out command is best effort. If the owner thread passes the cancel check in the instant before the flag is set, the action applies while the caller already reported a timeout. The window is microseconds and the action is still ownership-checked.
28. Abandoning a command does not clear the one-slot queue early, so the next submit can be refused until the owner thread finishes the one it holds.
29. The demo records runtime evidence after `stop()` so a close failure is captured. That ordering is asserted at the runtime layer and not through `main`, which needs a ROM.
30. The freshness check re-hashes the peeked frame even though the owner thread already published a digest for it. One extra hash per decision, no behavior change.
