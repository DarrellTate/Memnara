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

## Performance

No live `perception_ms` / `reasoning_ms` / `execution_ms` sample was captured for a battle. The M5 baseline remains: several seconds per action after warmup, with a slower first visual call. M6 does not add a second vision call per step.
