# Milestone 6 — Generic battle handling

**Status:** COMPLETE / APPROVED

ChatGPT approved M6 on 2026-09-30. The deferred live battle proof was accepted. Hands-on battle validation will happen separately. M7 is not authorized.

M6 teaches the existing bounded loop to notice a battle and reason for that interaction. It does not add title-specific strategy, new action names, persistent memory, or a desktop UI.

## Goal

```text
recognize battle/combat interaction
→ reason with the visible evidence
→ one allowlisted action
→ re-observe
→ continue until the battle changes or ends
```

VISION + INPUT is sufficient. Structured `is_in_battle` is optional.

## Architecture

M4 `fuse()` is unchanged. It still records a battle `PerceptionConflict` when visual `battle_visible` and structured `is_in_battle` disagree, and it does not pick a winner.

`src/memnara/agent/battle.py` derives a `BattleView` from that context:

```text
InteractionMode
├── NON_BATTLE
└── BATTLE_ACTIVE

BattleView
├── mode
├── visual_battle_visible     (None if visual is absent)
├── structured_in_battle      (None if the flag is absent)
└── conflict_present          (True only if M4 already recorded a battle conflict)
```

`BATTLE_ACTIVE` when either affirmative signal is true. `scene_type` is not an input. OR-activation is agent policy. It does not erase the conflict.

The loop is still observe → reason → validate → ownership → optional cheap confirm → one action → re-observe. `StuckDetector` and `fingerprint_context` are unchanged. There is no second stuck engine and no battle memory store.

## Reasoning

When the mode is `BATTLE_ACTIVE`, the user prompt starts with a short generic block: one allowlisted action, visible menu or text, no invented mechanics, and neither source wins a disagreement. When the mode is `NON_BATTLE`, that block is absent. The system prompt is unchanged. Evidence remains the M4 `compact_summary`.

## Ownership and stale actions

Ownership is checked first. Battle mode never overrides it.

```text
battle + USER_CONTROL | CONVERSATION | PAUSED → no gameplay input
battle + AI_CONTROL → one validated action may run
```

After ownership allows, `confirm_execution(prior)` may return a new observation. The default, including `VisualOnlyObserver`, returns `prior`. It does not capture a frame or call the VLM. If the derived mode differs, the proposal is not executed and the step records `StaleModeError`. The loop does not reason again in that step. The next iteration observes.

## Progress

Meaningful progress is still the semantic fingerprint: `battle_visible`, menu, dialogue, visible text, a bounded caption, description on the visual-only path, and an optional progress token. A raw pixel digest sets `screen_changed` only. Battle sprite animation with a stable fingerprint does not reset stuck detection. A menu or text change, a battle exit, or a token change does.

## Public / private boundary

Public tests use synthetic observations. No commercial title, move table, menu coordinate, RAM map, or ROM hash is part of this milestone. A private adapter may still supply generic `is_in_battle` from outside this repository. It is not imported here.

## CLI

`format_step` prints `MODE BATTLE` or `MODE NON_BATTLE`. `TRANSITION entry` or `TRANSITION exit` appears only when the previous step's reasoned mode differs. Evidence JSON for a new run defaults to `D:\Memnara-Data\autonomy\m6_live_autonomy.json`.

## Tests

`tests/test_battle.py` covers detection, prompt shape, ownership, stale mode, transitions, semantic progress, stuck recovery, and fail-closed validation. `python -m pytest -m "not integration"` is the public suite. Live ROM and Ollama gameplay are not required for that suite.

## Live validation

Live battle proof is **deferred**. A short bounded run from boot is not a reasonable way to reach combat, and M6 does not hard-code a route. Synthetic battle tests passed.

Operator hands-on, when a battle is already on screen or can be reached by ordinary play:

```text
D:\Memnara\.venv\Scripts\python.exe -m memnara.demo.autonomy --rom D:\Memnara_Roms\reference.gb --max-steps 8
```

Watch for `MODE BATTLE`, the chosen action, the reason, `progress`, `stuck_state`, and `TRANSITION entry` / `exit`. Do not treat a run that never enters battle as a failed synthetic suite.

## UX comparison

The first hands-on scorecard in `CURRENT_STATE.md` stays the baseline and is not overwritten.

M6 adds CLI mode and transition lines, so user observability of battle state is better than that baseline. Interaction speed was not re-measured. No optimization is claimed. Visual classification still must not be the only battle switch: `scene_type=BATTLE` with `battle_visible=False` stays non-battle.

## Known limitations

- Visual-only `confirm_execution` cannot see a battle start or end that happens during reasoning latency. The next step observes the new mode. One allowlisted action can still run in that gap.
- `scene_type` can still be `UNKNOWN` while other flags are usable. That remains vision debt.
- Repeated ineffective actions use the existing stuck detector. There is no battle-specific tactic memory.
- A stale-mode step does not count as a consecutive failure. It can still feed the stuck detector because the fingerprint did not change, same as an ownership denial.
- Live combat was not demonstrated in this implementation pass. That deferral is accepted.

Non-blocking debt recorded at approval. These are not open M6 work:

- Centralize the duplicated `"battle"` conflict label between fusion and the battle view when a later cleanup is authorized.
- Record `confirm_execution` exceptions on the step instead of aborting the loop.
- Review battle-view fields that are derived and not read by the loop.

## Post-M6 hands-on validation

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. The post-M6 hands-on validation patch is **COMPLETE / APPROVED**. M7 stays unauthorized.

`--show-window` passes PyBoy's in-process `"SDL2"` window to the one `PyBoyAdapter` shared by the observer and the executor. The default remains `"null"`. The flag does not start a second emulator and does not add a vision call.

The first post-M6 run counted `progress=True` while `screen_changed=False` and `state_changed=False` because the public demo has no structured progress token. The visual-only fingerprint included the full model description, so a rephrased description of the same pixels changed the fingerprint. That wording is no longer progress. A description change counts on a non-movement action only when the framebuffer digest also changes. Locomotion uses the movement outcome described below. Dialogue text, menu flags, battle flags, and structured tokens still count without a pixel change.

Generic reasoning now says an exploration or encounter goal should prefer movement, and should not choose `WAIT` only because standing still might cause a movement-triggered encounter. `WAIT` stays allowed when the screen shows a reason to wait. No title-specific encounter rule was added.

## Post-M6 movement outcome

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. The first post-M6 validation patch stays **COMPLETE / APPROVED**. This second patch is **COMPLETE / APPROVED**. M7 stays unauthorized.

A later hands-on run bumped into obstacles while the framebuffer changed from the walking or collision animation. The loop treated that as progress, so stuck recovery stayed at `NORMAL`.

```text
Screen-level visual change was insufficient to determine navigation success.
Repeated collision animations caused false progress and prevented stuck recovery.
```

`MovementOutcome` is `MOVED`, `BLOCKED`, `UNCERTAIN`, or `NOT_APPLICABLE`. It is derived from the before/after observations the loop already has. There is no extra vision call. A clear surrounding-scene shift is `MOVED`. An unchanged whole frame is `BLOCKED`. Equal structured navigation tokens are `BLOCKED`, and different ones are `MOVED`. A stable border with a center-only change is `UNCERTAIN`, not `BLOCKED`, because a fixed camera can move the actor inside that window. `UNCERTAIN` is not navigational progress. Repeated `UNCERTAIN` results with no other progress still feed the existing stuck detector. `PRESS_A`, `PRESS_B`, `PRESS_START`, `PRESS_SELECT`, and `WAIT` are `NOT_APPLICABLE`. Optional generic facts named `position_token`, `navigation_token`, or `location_token` can strengthen the result when both observations carry one. Dialogue, menu, battle, and structured progress tokens still count as progress on their own. Recent outcomes are appended to the existing bounded step history. The existing stuck states are unchanged. `--show-window` is unchanged. No map or pathfinding was added.

## Post-M6 transition-state recovery

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. Post-M6 Patch #1 and Patch #2 stay **COMPLETE / APPROVED**. This third patch is **COMPLETE / APPROVED**. M7 stays unauthorized.

```text
Temporary scene-transition frames caused false stuck escalation.
A battle-entry fade reached INTERVENTION_REQUIRED before the battle scene stabilized.
```

The public loop was also freezing the controlled emulator during vision and reasoning. `AgentLoop` does not tick while it observes or reasons. Frames advanced only inside `GameBoyActionExecutor.execute`.

`SceneStability` is `STABLE` or `TRANSIENT`. It is not an interaction mode and it does not mean battle. A frame is transient when it is nearly black (at least 92% of samples at or below 16 and a mean at or below 18) or nearly uniform (luminance span of 6 or less). Any other frame, including a dark scene that still has lighter structure, is stable. The classifier reads pixels the loop already captured. It does not call the vision model.

While a transient episode is active, Memnara has `AI_CONTROL`, and the run is not a dry run, the observer ticks the same runtime with no button held. The budget is `transition_grace_frames` (default 120), in chunks of `transition_chunk_frames` (default 8). Pixels are re-checked between chunks. A stable frame clears the budget. When the budget is spent, the existing `StuckDetector` runs on the following steps. There is no second stuck machine and no infinite wait. `PAUSED`, `USER_CONTROL`, `CONVERSATION`, and dry-run do not tick.

Those ticks are runtime progression, not a gameplay action. They are not recorded as `MOVE`, `PRESS`, or `WAIT`. One vision call runs on the frame where the pump stops. If that frame is battle-visible, interaction mode is derived then, the same way as any other observation. The fade itself does not set `BATTLE_ACTIVE`.

A locomotion step whose before or after side is transient, or whose re-observation pumped through a transient frame, is `UNCERTAIN` unless both observations carry a navigation token. `screen_changed`, movement outcome, scene stability, and meaningful progress stay separate. A transition does not count as `MOVED`.

If a proposal was made on a stable frame and a probe of the current pixels is transient before execute, the step is `StaleSceneError`. Nothing is executed and the loop does not reason again inside that step. `confirm_execution` still does not capture a frame or call the vision model.

On a frame that is still transient after the budget is spent, the reasoning history gains one line: `SCENE TRANSITIONING. Avoid gameplay inputs until the scene stabilizes. Prefer WAIT.` If the proposal is anything other than `WAIT`, it is not executed (`TransitionInputError`). `WAIT` still goes through the existing 1–180 frame validator. That refusal does not count as a consecutive reasoning failure. The existing stuck detector still sees the step.

A runtime that cannot peek, passively advance, and observe an already captured frame does not get the pump. It spends one grace unit per observation and skips reasoning until that budget is gone, then uses the normal loop. The PyBoy demo observer implements the pump.

CLI lines are `SCENE STABILITY` and, in the result, `transition`, `transition_grace_remaining`, and `passive_frames`. Evidence JSON adds `scene_stability`, `transition_state`, `transition_grace_remaining`, and `passive_frames`. `--show-window` is unchanged: passive ticks use `render=True` on that same adapter.

Synthetic measurement, not a live model run: eight button-free frames, two tick calls, one vision call, one reasoning call, zero button presses. Wall clock was about 0.051s, of which 0.050s was a single reasoning stub sleep. No live speedup number is claimed. The M5 cadence remains the hands-on baseline.

Accepted at approval. The near-black and near-uniform thresholds, and the 120-frame grace budget checked every 8 frames, may be tuned for a future runtime. That tuning is not a blocker and does not authorize a general loading-screen system.

## Post-M6 interaction outcome

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. Post-M6 Patch #4 is **COMPLETE / APPROVED**. M7 stays unauthorized.

`InteractionOutcome` is separate from `MovementOutcome`. A `MOVE_*` action is `NOT_APPLICABLE` for interaction. A `PRESS_*` or `WAIT` action is `NOT_APPLICABLE` for movement. `ADVANCED` means the menu, dialogue, or battle flags, the visible text, or the structured token changed. `CHANGED` means the framebuffer changed without that. `NO_EFFECT` means a stable non-movement action left those fields and the framebuffer the same. A transient side is `UNCERTAIN`.

`NO_EFFECT` is not meaningful progress. The recent-step line reads `PRESS_B → NO_EFFECT`. The reasoning prompt tells the model to use those observed outcomes and not to invent a button meaning from another game. Repeated `NO_EFFECT` on the same action feeds the existing stuck detector. A later `ADVANCED` step resets it. There is no stored control map.

A stable framebuffer whose digest matches the previous stable reading reuses that vision result. A different digest, a transient frame, or an empty digest calls the vision model. The reasoner still runs on a stable step. `--timing-details` prints vision, perception, reasoning, execution, confirmation, and total milliseconds. The default CLI prints `interaction=` only.

## Post-M6 runtime cadence

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. Post-M6 Patch #5 is **COMPLETE / APPROVED**. M7 stays unauthorized.

`DecisionReadiness` is `INPUT_REQUIRED`, `PASSIVE_PROGRESS`, or `UNKNOWN`. It is not `SceneStability`. A near-black or near-uniform frame is still a transition. A structured frame that keeps changing with no button held can be passive progress: battle motion, text reveal, or a camera shift are examples of the kind of motion, and none of those layouts is encoded.

The pump runs only when Memnara has `AI_CONTROL`, the run is not a dry run, and the observer can peek, advance, and observe a frame. That is the frame-stepping capability. A runtime without those methods keeps the normal loop. There is no background thread. The budget is 180 frames, re-checked every 8, with a 5-second hang guard. Each check is a pixel comparison. One vision call runs when the episode stops. The reasoner runs on that frame, including when the budget ends while the picture is still changing.

`PAUSED`, `USER_CONTROL`, and `CONVERSATION` do not take those ticks. Before execute, a peek that no longer matches the reasoned framebuffer drops the proposal (`StaleObservationError`). Patch #4 reuse still applies to an unchanged stable frame and still misses when the pixels differ. A fade still clears the cache.

The default CLI adds `readiness=`. `--timing-details` adds model-wait time, passive-runtime time, progression frames, and emulated-frame throughput. That throughput is emulated frames per wall-clock second, not a display refresh rate.

## Post-M6 continuous runtime

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. Post-M6 Patch #6 is **COMPLETE / APPROVED**. M7 stays unauthorized.

```text
POST-M6 HANDS-ON FINDING

Multiple hands-on recordings showed multi-second complete runtime freezes during model inference in both battle and overworld play.

Patch #5 reduced unnecessary model calls but did not solve decision-time runtime starvation.

Patch #6 decouples runtime progression/rendering from model inference while using snapshot/version freshness checks to prevent stale actions.
```

### Who owns the emulator

`ThreadedEmulatorRuntime` starts one thread named `memnara-runtime`. That thread is the only caller of `start`, `tick`, `capture_frame`, `press_button`, `release_button`, and `stop`. Opening and closing are passed in as `open_runtime` and `close_runtime` and run on that thread, so a window the emulator creates is created, pumped, and destroyed by one thread. The agent thread reads immutable snapshots and submits commands. The two threads never call the emulator at the same time, so a single-threaded vendor emulator stays safe. `start()` returns only after the owner thread has published its first snapshot. There is one emulator instance and no second process.

If the owner thread will not leave, `stop()` raises `RuntimeShutdownError` and the emulator is deliberately left alone, because freeing it from another thread while the owner is inside a native call is worse than leaking it. A runtime cannot be restarted; a new one is constructed instead.

Only `tick` emulates frames. A button call queues a press and a deferred release and emulates nothing, so it is neither counted nor paced. That was verified against PyBoy 2.7.0 and against the live adapter: one action reports 24 frames applied, which is the settle tick count.

### Snapshots and observation identity

Each published `RuntimeSnapshot` is frozen and carries an observation id, a framebuffer copy, a digest, the runtime frame counter, a wall-clock timestamp, and whether the runtime was advancing. `ObservedState` carries its own `observation_id`, `observed_at`, and `runtime_frame`, so every proposal is traceable to the observation it was reasoned from. Model inference reads a published copy, never a mutating framebuffer.

### Commands

`ActionCommand` carries the action, its parameters, and the source observation id. The queue holds one item. At most one meaningful gameplay action is pending, a second is refused rather than buffered, and there is no speculative lookahead. The owner thread applies the command through the same `GameBoyActionExecutor` logic and returns the frames it cost and the observation it landed on. Those reach the step record, so `--timing-details` shows both the observation a decision was reasoned from and the one its action landed on.

An action the agent stopped waiting for is cancelled rather than applied late: the owner thread checks the cancel flag before it touches a button. A runtime that dies mid-action fails the command it was holding instead of leaving the caller waiting.

### Freshness

Two checks run before execution, in this order. Ownership comes first through the existing `ControlGate`, and the owner thread repeats it before it moves a button. Then semantic freshness compares the live frame against the decision signature: owner, interaction mode, scene stability, structured token, and digest. Perception flags are deliberately absent, because re-reading them would cost another vision call. An ownership change, an interaction-mode change, a `STABLE` frame that became `TRANSIENT`, a structured token that moved on, an unreadable or empty frame, or a material framebuffer change drops the proposal. An identical digest is fresh without a pixel comparison. An idle animation below the change threshold stays valid, so a battle menu that animates while `FIGHT` is still highlighted still executes. The frame number alone never decides. No second model call is made, and no free-form model wording is parsed.

### Cadence and ownership

The default target is 60 emulated frames per second, configurable with `--target-fps` and not hard-coded in the loop. Every advanced frame is paced, input application included, so game time stays approximately normal. `PAUSED` freezes the runtime. `AI_CONTROL`, `USER_CONTROL`, and `CONVERSATION` keep it advancing, and the ownership gate still blocks AI input in the latter two. The runtime itself is ownership-agnostic: the demo passes a `should_advance` predicate.

### Visibility, dry run, and shutdown

Headless stays the default and the continuous runtime does not require SDL2. `--show-window` shows that same controlled instance. `--step-runtime` keeps the Patch #5 frame-stepped path for comparison. Dry run still performs no gameplay input while the runtime keeps advancing, which matches what a person watching the window would expect. Stop sets a flag, releases every button on the owner thread, fails any pending command, and joins the thread, so there is no orphan window, hung process, or held button.

### Measured

Synthetic benchmark, one decision with three seconds of model latency, identical frames and identical model-call counts on both sides:

| Metric | Decision loop owns the clock | Runtime owner thread |
|---|---|---|
| Longest runtime freeze | 3004 ms | 47 ms |
| Emulated frames advanced once inference began | 24 | 294 |
| Effective emulated frames per second | 5.3 | 60.3 |
| Vision calls | 2 | 2 |
| Reasoning calls | 1 | 1 |
| Stale proposals dropped | 0 | 0 |

Wall clock per step rose from 4.51 s to 4.91 s because settle frames are now paced to real game time instead of being applied instantly. Proposal age reports the full 3002 ms, because an observation is timestamped when its frame was captured rather than after the vision call returns.

That comparison comes from a local synthetic harness that is not committed. The live equivalent is committed and reproducible: `tests/test_continuous_runtime_live.py` is integration-marked and skips without the operator ROM.

Live PyBoy, operator ROM, headless, measured:

| Check | Result |
|---|---|
| Threads that called the emulator | `{memnara-runtime}` only, open and close included |
| Overlapping emulator calls | 0 |
| Three seconds of simulated decision latency | 180 frames advanced, 60.0 effective emulated fps, longest freeze 34 ms |
| One action | 24 emulated frames, matching PyBoy's own `frame_count` |
| Shutdown | every button released while the adapter was still open, then closed |

Live PyBoy with a visible SDL2 window: every call on the owner thread, at least 30 frames in one second, and a changed published digest, so the window Memnara shows is the runtime it controls. A long operator play session with a real local model remains unmeasured.

## Post-M6 thinking profiles

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. Post-M6 Patch #7 is **COMPLETE / APPROVED**. M7 stays unauthorized.

```text
POST-M6 HANDS-ON FINDING

Continuous runtime solved the choppy/frozen-emulator experience.

The remaining UX complaint is AI decision latency: the pause now feels natural but longer than desired.

Product direction:
support configurable thinking depth so users can choose faster responses or more deliberate decisions without changing AI identity.
```

`--thinking fast|balanced|deliberate` maps onto one `ThinkingSettings` object. Default remains balanced until operator testing determines whether FAST should become a future consumer default. FAST shortens the reasoner system prompt, bounds `num_predict`, asks for a short visual description, and may reuse perception across idle animation. All profiles keep the same action JSON schema, ownership, stale-proposal checks, and Patch #4/`NO_EFFECT` history. `--timing-details` now prints acquire, freshness, post-acquire, classification, and unaccounted milliseconds so a step's wall clock can be reconstructed. `confirmation_ms` remains the post-action observation time for evidence compatibility.

## Post-M6 perception efficiency

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. Post-M6 Patch #8 is **IMPLEMENTED / AWAITING CHATGPT REVIEW**. M7 stays unauthorized. Affect and voice were not implemented.

Internal `PerceptionTier` LIGHT/NORMAL/RICH selects vision prompt depth from stuck, transition, UI flags, and pixel change. FAST and BALANCED may reuse a previous overworld reading across idle animation; menu, dialogue, battle, and visible text force a fresh read. After locomotion, or after an identical-frame press, the loop may skip the second VLM and classify from pixels, then reread on the next decision if the scene moved. FAST/BALANCED send scale-2 images unless `MEMNARA_VISION_SCALE` is set. `structured_step_events` lists existing outcomes for a later affect prototype.

## Performance

No live `perception_ms` / `reasoning_ms` / `execution_ms` sample was captured for a battle. The M5 baseline remains: several seconds per action after warmup, with a slower first visual call. M6 does not add a second vision call per step. Post-M6 Patch #3 does not add a vision call per pumped transition frame.
