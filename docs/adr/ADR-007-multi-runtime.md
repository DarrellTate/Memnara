# ADR-007 — Multi-runtime capability architecture

**Status:** ACCEPTED  
**Date:** 2026-09-30  
**Accepted:** 2026-09-30 (ChatGPT review)

This ADR extends, and does not replace, ADR-001 through ADR-006.

## Context

Milestone 0 selected PyBoy as the first `EmulatorAdapter` (ADR-001) and a hash-pinned local Game Boy title as the first enhanced game (ADR-002). Those decisions remain valid for the **current implementation**. They must not be read as “Memnara is a Game Boy / ROM-only system” or “PyBoy is the universal Memnara runtime.”

The product owner and ChatGPT authorized a long-term product rebaseline: emulator-backed **and** native PC game runtimes, with capability-driven perception and input. This ADR records that scope. Implementation of later milestones (including M4 fusion) requires a separate ChatGPT authorization; this document is the architecture, not a blanket green-light for every future backend.

## Decision

### North star

Memnara is a local, multi-runtime AI gaming companion framework capable of observing, reasoning about, controlling, remembering, and commenting on games across emulator-backed and native PC game runtimes.

A locally supplied Game Boy title + PyBoy remains the first reference implementation and current development testbed. Existing local integration work is preserved privately; it is not in the public core.

### Core principle

The AI core must not assume:

```text
game == ROM
game == Game Boy
game == emulator
game always has RAM access
```

Instead:

```text
Memnara Core
    ↓
Runtime capabilities
    ↓
available perception/input/state providers
```

Different runtimes expose different capabilities. A runtime **advertises** capabilities; the core does not infer them from runtime type.

### Runtime families

**Emulator runtime** (examples; none beyond PyBoy exist in code today):

```text
Game Boy / Game Boy Color → PyBoy (current)
SNES → future emulator backend
PlayStation 1 → future DuckStation or equivalent
GBA → future backend
```

Possible capabilities (not all backends provide all of these): visual framebuffer, controller input, RAM/state, save states, pause, frame stepping, game metadata.

**Native PC runtime** (future; not implemented): ordinary installed Windows games (native title not fixed). Typical capabilities: window/screen capture, keyboard, mouse, controller where applicable, window/process metadata. Typical **unavailable** capability: semantic game RAM.

Memnara must operate when RAM/state integration is absent.

### Generic play does not require RAM

A game-specific RAM adapter is an **enhancement**, not a prerequisite for AI play.

Minimum generic gameplay path (future):

```text
VISION + INPUT
```

Enhanced integrations may add RAM_STATE, game-specific visual knowledge, structured game state, save-state features, and game-specific tools.

### Runtime vs game integration

Keep separate:

```text
Runtime Backend  → generic execution environment
Game Integration → optional game-specific knowledge
```

Examples (future, not implemented):

```text
DuckStationRuntime
    ├── example_ps1_title_a integration
    ├── example_ps1_title_b integration
    └── generic PS1 game

SNESRuntime
    ├── example_snes_title_a integration
    └── generic SNES ROM
```

Adding a new game must not require rewriting the emulator/runtime backend. Adding a new runtime backend must not require modifying the AI reasoning core.

### Future abstractions (names not frozen)

Do not implement until a later authorized migration. Exact interface split is decided by architecture review before coding.

Likely concepts: `GameRuntime`, `CaptureProvider`, `InputProvider`, `StateProvider`, `SaveStateProvider`, `RuntimeCapabilities`.

The current `EmulatorAdapter` may remain until that migration milestone. Do not refactor working M1–M3 code merely to match speculative names.

### Input (future)

Validated structured/allowlisted actions, never arbitrary OS execution. Conceptual families: emulator/controller buttons (current path), plus future `key_press` / `key_hold` / `key_release`, `mouse_move` / `mouse_click`, `controller_button` / `controller_stick`. Do not implement keyboard/mouse/gamepad axes now.

### Control ownership

Exactly one owner, runtime-independent:

```text
AI_CONTROL | USER_CONTROL | CONVERSATION | PAUSED
```

Manual takeover must work for PyBoy, future emulators, and native Windows games. Takeover: cancel stale AI actions → `USER_CONTROL`. Handback: clear stale input → re-observe current game state → `AI_CONTROL`.

### Perception

M3 vision is a **universal** Memnara capability, not title-specific. Future `PerceptionContext` may omit sources:

```text
visual              (required for generic play)
game_state          optional
window_state        optional
memory / goals / affect
```

Examples: local GB integration = VISUAL + RAM; native PC title = VISUAL + WINDOW_STATE; unknown emulator game = VISUAL only. Perception fusion remains M4 (unauthorized here).

### AI profiles

Profiles are independent of runtime, game, emulator, model, and voice. Changing runtime or model does not create a new identity. Persistent memory is profile-keyed with stable `ai_profile_id` from the first persistent-memory implementation.

### Commentary

Memnara is not only an optimal-action executor. The companion should eventually play, observe, react, form preferences, remember experiences, comment, and talk with the user, across games, subject to memory scoping. Not implemented in this ADR.

### Support spectrum (labels may be refined)

```text
GENERIC     Vision + generic input
ENHANCED    Game-specific controls / visual hints
INTEGRATED  Vision + structured game state / RAM
FULL        Deeply validated game-specific integration
```

Support is incremental, not binary.

### Second-game / multi-runtime proof

A second Game Boy ROM is **not** the finished architecture proof. **M16** is an incremental second-game / second-GameAdapter proof. The stronger **platform** proof (M22) is that the same profile architecture can operate across materially different runtime families:

```text
Reference path:
locally supplied Game Boy title
→ emulator
→ VISUAL + RAM_STATE + controller

Second emulator/platform:
SNES or PS1 class runtime
→ VISUAL + controller
→ optional state capabilities

Native path:
a native PC game
→ window capture
→ VISUAL
→ keyboard/mouse/controller
→ no RAM requirement
```

The native game itself is not fixed yet. native PC titles remain architectural examples, not committed implementation targets.

### Native PC (example only)

A future native session is conceptually: game window → screen capture → `VisualObservation` → reasoning / goals / profile memory → validated structured input → keyboard/mouse. No direct RAM required for the generic path. **Do not implement a native PC title under this ADR.**

## Capability catalog (initial names)

Exact names may be refined before implementation:

```text
VISION
INPUT
KEYBOARD
MOUSE
CONTROLLER
RAM_STATE
SAVE_STATES
PAUSE
FRAME_STEPPING
WINDOW_STATE
GAME_METADATA
```

Illustrative (not current product claims except PyBoy where already built):

```text
local GB title / PyBoy     VISION, CONTROLLER (hence INPUT), RAM_STATE, SAVE_STATES, FRAME_STEPPING
native PC title / Native   VISION, KEYBOARD, MOUSE (hence INPUT); no RAM_STATE; no SAVE_STATES
Unknown SNES game          VISION, CONTROLLER (hence INPUT); RAM_STATE no initially; SAVE_STATES emulator-dependent
```

**INPUT** is the umbrella capability (can inject validated control). KEYBOARD, MOUSE, and CONTROLLER are modality primitives; advertising any of them implies INPUT. **VISION** is capture/framebuffer; `VisionProvider` interprets that capture.

**PAUSE** (capability) is engine pause. **PAUSED** (ownership) is “Memnara issues no play actions” and must work even without engine pause. Generic allowlisted primitives come from advertised input capabilities via `ActionRegistry` / future `InputProvider`. A `GameAdapter` is optional and only adds title-specific actions.

Exact names and the mapping to providers may be refined before implementation.

## Consequences

- Durable architecture, roadmap, and product docs distinguish current PyBoy + a local Game Boy reference title + M3 vision from the long-term multi-runtime product.
- ADR-001/002 stay ACCEPTED as first-adapter / first-game decisions.
- New runtime backends, native capture/input, fusion, and autonomy remain unauthorized until later milestones.
- Historical M0 text that said “emulator control” as the whole product is superseded for **scope**, not for **implemented code**.

## Out of scope for this ADR (documentation rebaseline)

The original write-up did not implement backends. Native Windows, extra emulators, and autonomy still require their own authorized milestones. M4 perception fusion is separately authorized as the first implementation under this ADR.
