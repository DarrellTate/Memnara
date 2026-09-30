# Milestone 5 — Basic autonomous control + stuck recovery v1

**Status:** COMPLETE / APPROVED

M5 is a bounded, safe observe → fuse → reason → validate → execute → re-observe loop. It is not reference-title progression, battle strategy, UI, voice, conversation, or persistent memory.

## What the product owner can do

```text
python -m memnara.demo.autonomy --rom D:\Memnara_Roms\reference.gb --max-steps 5
```

Optional flags: `--dry-run`, `--goal "..."`, `--model qwen3-vl:8b`, `--no-skip-intro`, `--owner AI_CONTROL|PAUSED|...`

`--skip-intro` (default on) mashes A so a typical boot sequence advances. That mash is **operator setup**, not a scripted route.

## Architecture

```text
PerceptionContext (M4)
      ↓
AgentLoop (generic)
      ↓
ActionProposal (one action)
      ↓
ActionValidator / ActionRegistry
      ↓
ControlGate (AI_CONTROL only)
      ↓
GameBoyActionExecutor → EmulatorAdapter
      ↓
PyBoy (adapter only)
```

Generic agent code lives in `src/memnara/agent/`. It does not import PyBoy or title-specific RAM addresses.

| Piece | Location |
|---|---|
| Proposal / registry | `agent/actions.py` |
| Validator | `agent/validator.py` |
| Ownership | `agent/ownership.py` |
| Stuck v1 | `agent/stuck.py` |
| History | `agent/history.py` |
| Loop | `agent/loop.py` |
| Ollama reasoner | `agent/ollama.py` |
| GB execution edge | `emulators/gameplay.py` |
| Visual-only observer | `agent/observe.py` (`VisualOnlyObserver`) |
| Demo CLI | `demo/autonomy.py` |

## Action contract

```text
ActionProposal
├── action          (required, allowlisted name)
├── parameters      (WAIT may set frames: 1–180)
├── reason          (short, explicit)
├── confidence      (optional 0–1)
└── metadata        (non-executable extras; thinking fallback flag only)
```

Allowlist for the current emulator demo:

```text
MOVE_UP MOVE_DOWN MOVE_LEFT MOVE_RIGHT
PRESS_A PRESS_B PRESS_START PRESS_SELECT
WAIT
```

Rejected: unknown names, `actions` lists, action arrays, malformed JSON, forbidden keys (`shell`, `code`, …), parameters on non-WAIT actions, battle-specific names (`USE_MOVE_1`, …).

Invalid output does **not** become a guessed button. The step is recorded as a diagnosable failure; repeated failures halt (`max_consecutive_failures`).

## Validator

`ActionValidator.parse_and_validate` is the only path from model text/JSON to `ActionProposal`. Names are normalized to `A-Z0-9_`. One decision → one `action` field.

Model JSON may contain only `action`, `parameters`, `reason`, and `confidence`. Unknown top-level fields are rejected. Duplicate object keys in raw JSON are rejected. Non-finite confidence (`NaN`, `Infinity`) is rejected.

`ActionProposal.metadata` is application-owned. The model cannot populate it. After validation, Memnara may attach `json_in_message.thinking=true` when structured JSON was taken from `message.thinking`. The raw thinking string is discarded; surrounding non-JSON prefix/suffix is not stored.

## Ownership

```text
AI_CONTROL     gameplay input allowed
USER_CONTROL   no gameplay input
CONVERSATION   no gameplay input
PAUSED         no gameplay input (does not require emulator pause)
```

M13 UX is not built. This is a programmatic gate only.

## Execution mapping

`GameBoyActionExecutor` maps validated names to `EmulatorAdapter.press_button` / `tick`. No RAM writes. Buttons are released after each action. WAIT ticks frames only.

Tap default: 8 frames hold via adapter `press_button`, then 24 settle ticks.

## Reasoning

`OllamaReasoningProvider` posts loopback-only `/api/chat` (`think: false`) with a JSON schema. Prompt consumes `compact_summary(PerceptionContext)` plus goal, stuck state, discouraged actions, and recent step lines.

If `message.content` is empty, JSON in `message.thinking` may be parsed (M3 compatibility). The thinking text is **not** stored as gameplay state. Metadata may record `json_in_message.thinking=true`.

Model: `qwen3-vl:8b`. Endpoint: `http://127.0.0.1:11434`.

## Stuck v1

```text
NORMAL → SUSPECTED_STUCK → CHANGE_STRATEGY → EXPLORE → INTERVENTION_REQUIRED
```

Signals:

* unchanged **meaningful-progress fingerprint** (semantic visual flags + `visible_text` when present + optional structured `progress_token`; when a dialogue/menu is active and `visible_text` is empty, quoted/caption text from the description is used; visual-only also includes description);
* repeated identical action without meaningful progress.

`screen_changed` is recorded separately from the raw framebuffer digest and does **not** by itself reset stuck detection.

Coordinates are an optional structured `progress_token` from a local GameAdapter. Visual-only still works (description/flags/text), without requiring RAM.

Meaningful progress examples:

* token change (map / coordinates / mode / battle);
* `visible_text` change with a stable token;
* dialogue/menu caption change when `visible_text` is empty (quoted text, not full VLM prose);
* visual-only description or flag change when no token exists.

Not meaningful progress: same token + idle animation (pixel digest only); same token + free-form overworld description jitter.

Defaults: 3 unchanged fingerprints or 3 identical no-progress actions → suspected; then change strategy / explore; then halt. ASK_USER / manual takeover UX are not implemented.

## History

In-memory `RecentStep` only (before summary, action, execution, after summary, progress, stuck, timings). Not SQLite. Not cross-session.

## Loop bounds

Loop bounds: `max_steps` and `max_consecutive_failures` on `AgentLoop`. Stuck recovery uses `StuckConfig.max_recovery_attempts` (default 3). `WAIT` without `parameters.frames` ticks 30 frames.

`--dry-run` validates and reports but never calls the executor. A valid dry-run step records `executed=False` and `execution_ok=True`. That `execution_ok` value means the no-execution policy completed successfully, not that gameplay input occurred.

## Battle

M4 may label battle. M5 may press generic buttons. M5 itself has no battle strategy. M6 generic battle mode on this loop is **COMPLETE / APPROVED**.

## User demo / feedback questions

After ChatGPT approval, run the CLI and note:

* Does it feel like an AI trying to play?
* Is each step too slow?
* Are decisions understandable?
* Does cadence feel right?
* Did stuck recovery appear, and did it make sense?
* What should a later UI show?

## Known limitations

* Finite VLM confidence values outside 0–1 are clamped and noted (`confidence_clamped_from=...`); they are not turned into a fake scene description. Non-finite confidence, wrong types, malformed JSON, and invalid schema still raise `VisionParseError`.
* Qwen may walk into walls, open menus, or mash A inefficiently. That is acceptable for M5.
* Intro skip is a convenience mash, not learned play.
* Opening START reliably is still weak (M3 debt).
* No persistent memory, personality, voice, or desktop UI.

## Live validation procedure

1. Operator ROM at `D:\Memnara_Roms\reference.gb`.
2. Local Ollama with `qwen3-vl:8b`.
3. Approved live evidence is retained in the private development archive. New runs: `python -m memnara.demo.autonomy` writing under `D:\Memnara-Data\autonomy\`.
4. Do not overwrite approved evidence retained in that archive.
5. Process must stop after `max_steps` or a halt reason; adapter `stop()` in `finally`.
