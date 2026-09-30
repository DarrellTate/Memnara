# ADR-006 — UI architecture

**Status:** ACCEPTED  
**Date:** 2026-09-30

## Choice

Desktop **PySide6** dashboard: game view, identity/mood, goal, commentary, plan, recent memory, RAM/vision summary, chat, control-mode actions.

## Alternatives

Local web UI; immediate overlay-only.

## Evidence

Need framebuffer + buttons + chat in one local process. `docs/research/ui-concurrency-storage.md`.

## Tradeoffs

Qt distribution size. LGPL/GPL compliance when packaging.

## Consequences

No UI implementation in M0. UI milestone after harness exists (not M1).
