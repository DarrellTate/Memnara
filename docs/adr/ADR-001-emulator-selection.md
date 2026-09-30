# ADR-001 — Emulator selection

**Status:** ACCEPTED  
**Date:** 2026-09-30

## Choice

Use **PyBoy** as the first `EmulatorAdapter` implementation (Milestone 1). Keep mGBA as a later adapter for GBA, not v1.

## Alternatives considered

- **mGBA / libmgba Python bindings:** capable framebuffer, frames, memory, save states; Windows Python packaging and upstream binding stability are weaker than PyBoy for GB-first work.
- **External process (BizHawk Lua, RetroArch):** poor in-process Python control and testing.

## Evidence

Official PyBoy docs: `tick`, `button`, `memory[]`, `screen.image`, `save_state`/`load_state`, GB/GBC ROMs. See `docs/research/emulator-candidates.md`.

## Tradeoffs

- PyBoy is GB/GBC, not GBA. Acceptable for the first locally supplied Game Boy reference title.
- Save-state format is PyBoy-specific.
- License must be confirmed at install (`LICENSE.md`).

## Milestone 1 dependency pin

Recommend **`pyboy==2.7.0`**. Do not install an unpinned/latest PyBoy for Milestone 1 until a newer suitable release has been explicitly reviewed.

Reason:

- PyBoy **2.7.1** is currently yanked.
- The published yank reason is a documented GB dialogue/window bug that can make some titles unplayable.

Re-evaluate this pin immediately before any authorized install, in case upstream releases change.

**Do not install PyBoy under this ADR.**

## Consequences

Milestone 1 implements only a PyBoy-backed adapter behind `EmulatorAdapter`, using the pinned version above once installation is separately authorized. Agent core must not import PyBoy types.

## Clarification (2026-09-30)

This ADR selected PyBoy as the **first** `EmulatorAdapter`, not as the universal Memnara runtime. Memnara’s long-term product includes additional emulator platforms and a native PC runtime (ADR-007). Those backends are **not implemented**. Do not read this ADR as forbidding other runtimes or as claiming they already exist.
