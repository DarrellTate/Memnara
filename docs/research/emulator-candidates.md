# Emulator candidates (Milestone 0)

**Status:** research complete for architecture; **no emulator installed**.  
**Recommendation:** PyBoy as the first `EmulatorAdapter` target.  
**Decision record:** `docs/adr/ADR-001-emulator-selection.md` (ACCEPTED).

## Requirements we scored against

Framebuffer/screenshots, button injection, frame stepping, speed control, RAM access, save/save-state, Python embedding, Windows, GB/GBC future titles, testability, maintenance, license.

## PyBoy

**Sources (official):**

- https://github.com/Baekalfen/PyBoy
- https://docs.pyboy.dk/
- https://docs.pyboy.dk/api/screen.html

**Verified from those docs (not from a local install):**

| Capability | Evidence |
|---|---|
| Python-native | `from pyboy import PyBoy`; ROM path is constructor argument |
| Frame stepping | `pyboy.tick(count=1, render=True, sound=True)` |
| Speed | `pyboy.set_emulation_speed(0)` unlimited; otherwise real-time-ish 60 fps |
| Input | `pyboy.button('a')` / `'down'` etc. |
| RAM | `pyboy.memory[addr]` read/write; CGB banked access documented |
| Screen | RGBA buffer; `pyboy.screen.image` (PIL) |
| Save-state | `save_state` / `load_state` on file-like binary objects |
| GB and GBC | Constructor accepts GB/GBC ROMs; `cgb=` can force CGB mode |
| Windows | Documented as a supported platform in project materials |
| AI/bot focus | Explicit bot/AI API, Gym wiki, headless-friendly tick loop |

**License:** PyPI/GitHub metadata: **LGPL-3.0-only** (emulator-specialist review of public LICENSE.md). Confirm SPDX again at Milestone 1 install.

**Gaps / risks:**

- Live Windows + first GB reference title integration is **unverified** until Milestone 1 (install not authorized now).
- Save-states are PyBoy-format, not interchange with mGBA; store under `D:\Memnara-Data`, gitignore `*.state`.
- Rendering every frame is optional (`tick(n, render=False)`), which matches event-driven vision (render last frame only).

## mGBA

**Sources:**

- Official core: https://github.com/mgba-emu/mgba
- Maintainer gist for Python bindings: https://gist.github.com/endrift/752230729cbf2e29192dbe2c4a5e86c2
- Community / fork bindings: https://github.com/hanzi/libmgba-py
- Upstream issue: Python bindings described as fragile / historically slated for deprecation in favor of a unified scripting subsystem (https://github.com/mgba-emu/mgba/issues/3048) — treat as **community+issue-tracker**, not a frozen API contract.

**What it can do (documented examples):** load ROM, `runFrame()`, video buffer → PNG, memory read/write, save states in some binding wrappers.

**Why not first:**

- Python path is a **bindings/build** problem on Windows, not a first-class `pip` product like PyBoy.
- Official Python bindings have been discussed as fragile/deprecated relative to Lua scripting.
- Stronger for GBA later; Memnara v1 is classic GB titles. Keep mGBA as the **future GBA adapter**, not the v1 harness.

## Other candidates

BizHawk/EmuHawk Lua, RetroArch, BGB: useful for humans, weaker as a **Python-in-process** adapter. Not recommended for v1.

## Recommendation

Use **PyBoy** for Milestone 1 (`EmulatorAdapter`). Keep an `EmulatorAdapter` interface so mGBA can be added for GBA without rewriting the agent core.

**Currently approved Milestone 1 pin:** `pyboy==2.7.0`. PyBoy **2.7.1** is yanked because of a documented GB dialogue/window issue that can make some titles unplayable. Re-check upstream immediately before any authorized installation in case a newer suitable non-yanked version has been released. Do not install an unpinned/`latest` version without review.

**Windows install (later, not now):** official project / `pip install pyboy==2.7.0` after ChatGPT authorizes Milestone 1 and the pin is re-verified. User-provided ROM only. Do not install PyBoy during Milestone 0.
