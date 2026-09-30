# Roadmap

M0–M6 numbering is unchanged. **M8A** is inserted between M8 and M9 without renumbering M0–M22. M7–M17 follow the durable sequence below (exactly one new-run-learning milestone: **M15**). M18–M22 are the appended multi-runtime sequence. The first emulator-backed local reference title remains the private validation testbed through initial autonomy, profile, memory, and UI work.

```text
M0   Research + Architecture
M1   Emulator harness (PyBoy)
M2   RAM / state reader (local GameAdapter, fair-RAM)
M3   Vision (screenshot → VLM)
M4   Perception fusion
M5   Basic autonomous control + stuck v1 (emulator-backed reference; includes stuck v0)
M6   Battle handling
M7   Profile-aware persistent + session memory foundation
M8   Memory compression / retrieval / consolidation
M8A  Game Knowledge Packs + Local RAG
M9   AI profile / personality / affect system
M10  Desktop app shell + selectors + memory/knowledge management UX
M11  Local voice system
M12  User conversation
M13  Manual takeover UX
M14  Autonomous reference-title progression
M15  New-run learning
M16  Second-game / second-GameAdapter proof
M17  Multi-profile / model-swap proof
M18  Runtime abstraction hardening
M19  Second emulator/platform proof
M20  Native Windows capture/input runtime
M21  Vision-only native game proof
M22  Cross-runtime profile continuity proof
```

```text
M0–M6 COMPLETE / APPROVED
POST-M6 PATCH #1 COMPLETE / APPROVED
POST-M6 PATCH #2 COMPLETE / APPROVED
POST-M6 PATCH #3 COMPLETE / APPROVED
M7 AUTHORIZED NO
```

## Notes on later milestones

- **M4** remains perception fusion. **COMPLETE / APPROVED.**
- **M5** remains first autonomous-control proof on an emulator-backed local reference title. Milestone title keeps historical **stuck v1**; it **includes stuck v0** (coord/screen loop) so navigation is testable before M14. **COMPLETE / APPROVED.**
- **M6** generic battle handling on the bounded loop. **COMPLETE / APPROVED.** No new action names. VISION + INPUT remains sufficient. Live battle proof was deferred and accepted.
- **Post-M6 validation patch** adds a developer-visible controlled emulator window and corrects visual-only progress semantics. **COMPLETE / APPROVED.** Not a numbered milestone. M7 remains unauthorized.
- **Post-M6 movement patch** distinguishes a scene change from a successful locomotion attempt and feeds that result to the existing stuck history. **COMPLETE / APPROVED.** Not a numbered milestone. M7 remains unauthorized.
- **Post-M6 transition patch** treats a short scene fade as transient, advances the runtime without a gameplay action, and keeps that gap from escalating the existing stuck detector. **COMPLETE / APPROVED.** Not a numbered milestone. M7 remains unauthorized.
- **M7** profile-aware persistent + session memory foundation. Requirements include: `ai_profile_id` ownership (never model ownership); session/working memory distinct from long-term store; SQLite schema; memory types/scopes; timestamps; model provenance (`model_id_at_creation` is metadata only); lineage (`source_memory_ids` / `source_game_ids`); CRUD primitives; bulk filtering/reset primitives. See [ADR-008](docs/adr/ADR-008-ai-memory-knowledge-architecture.md) (**ACCEPTED**). **Not authorized.**
- **M8** memory compression / retrieval / consolidation. Requirements include: short-term → long-term consolidation; SQLite FTS5 retrieval; bounded top-K retrieval; importance / recency / scope filters; derived-memory lineage/reconciliation. **Not authorized.**
- **M8A** Game Knowledge Packs + local RAG. Game-scoped document packs (TXT / Markdown / PDF initially), activate/deactivate, document enable/disable, category/provenance metadata, bounded local retrieval, knowledge policies (BLIND / LORE / MANUAL / GUIDED / FULL). Packs belong to game/session configuration, not to an AI profile. Do not merge pack chunks into personal memory. **Not authorized.**
- **M9** AI profile / personality / affect system.
- **M10** desktop **PySide6** shell (ADR-006). Conceptual selectors: Runtime Type, Platform, Runtime/Emulator, Game/ROM/Window, AI Profile, Model, Voice, Control Preset, plus input mapping. Model list from Ollama discovery, not a hard-coded menu. **Also** Memory Manager and Knowledge Manager: search/filter, create/edit/delete, bulk operations, per-game reset, per-run reset, date-range filtering/reset, model-provenance filtering/reset, blind-new-run workflow. **Not implemented now.**
- **M11** local voice system.
- **M12** user conversation.
- **M13** manual takeover UX.
- **M14** autonomous progression on the local reference title.
- **M15** new-run / cross-run learning. **Only** new-run-learning milestone.
- **M16** second **GameAdapter** / second-game integration (may still be GB/GBC). Incremental proof. **Not** the finished cross-runtime platform proof.
- **M17** multi-profile / model-swap proof (same product, identity and model replaceability).
- **M18** hardens generic `GameRuntime` / advertised capabilities. Current `EmulatorAdapter` may migrate here; do not speculative-refactor M1–M3 before this is authorized.
- **M19** second emulator family (e.g. SNES or PS1 class). Optional state capabilities. A new game on that backend must not rewrite the AI core.
- **M20** native PC: window/screen capture + keyboard/mouse (and controller if applicable). No RAM required. Native title is **not** fixed.
- **M21** generic **VISION + INPUT** play on a native game.
- **M22** same profile architecture (`ai_profile_id`) operating across materially different runtime families (emulator with RAM vs native without).

## Cross-runtime proof (M22), stronger than a second ROM

```text
Reference path:
locally supplied Game Boy title (private integration)
→ emulator
→ VISUAL + optional RAM_STATE + controller

Second emulator/platform:
SNES or PS1 class runtime
→ VISUAL + controller
→ optional state capabilities

Native path:
a native PC game (title not fixed)
→ window capture
→ VISUAL
→ keyboard/mouse/controller
→ no RAM requirement
```

The native game itself is not fixed yet. Named commercial titles are private validation examples only, not public product claims.

## Numbering

M0–M22 preserved as listed. **M8A is inserted between M8 and M9** and does not renumber later milestones. SNES, PS1, DuckStation, and native Windows gameplay **do not exist** in application code.

## Still proposed, not silent product changes

1. **M5 includes stuck v0** so navigation is testable before M14. **M5 is COMPLETE / APPROVED.**
2. **No UI in M1** (ADR-006). Desktop app shell is **M10**.
3. A later same-series handheld revision remains a later adapter, not M2.
4. **ADR-008** (memory / knowledge / user-control architecture) is **ACCEPTED**. It does not authorize M7, M8, M8A, M9, or M10 implementation.

Do not execute any unauthorized milestone. M7 and later are not authorized.
