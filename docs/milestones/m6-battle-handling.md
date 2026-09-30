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

This is not a new milestone. M6 stays **COMPLETE / APPROVED**. Post-M6 Patch #1 and Patch #2 stay **COMPLETE / APPROVED**. This third patch is **IMPLEMENTED / AWAITING CHATGPT REVIEW**. M7 stays unauthorized.

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

## Performance

No live `perception_ms` / `reasoning_ms` / `execution_ms` sample was captured for a battle. The M5 baseline remains: several seconds per action after warmup, with a slower first visual call. M6 does not add a second vision call per step. Post-M6 Patch #3 does not add a vision call per pumped transition frame.
