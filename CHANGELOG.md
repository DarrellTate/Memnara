# Changelog

## Unreleased

- Post-M6 movement-outcome patch, implemented and awaiting ChatGPT review. Locomotion steps record `MOVED`, `BLOCKED`, `UNCERTAIN`, or `NOT_APPLICABLE` from the observations already collected. An unchanged whole frame or an equal navigation token is `BLOCKED`. A center-only change with a stable border is `UNCERTAIN` and is not progress. Repeated uncertain attempts still feed the existing stuck detector. Not a new milestone. M7 remains unauthorized.
- Post-M6 hands-on validation improvement **COMPLETE / APPROVED**. `--show-window` displays the same in-process PyBoy instance the loop controls. Unchanged-frame description rephrasing is no longer progress. Encounter goals prefer movement over waiting with no visible reason. Not a new milestone. M7 remains unauthorized.
- M6 generic battle handling **COMPLETE / APPROVED**. Interaction mode is derived from labeled perception. Ownership still blocks input. A stale mode drops one proposal. No new actions. Live battle proof remains deferred and accepted.
- Project renamed from GameAI to Memnara before the first public Memnara release.
- Public package is `memnara`. Demo: `python -m memnara.demo.autonomy`. Environment variables use the `MEMNARA_*` prefix.
- Canonical source is `D:\Memnara`. Runtime data is `D:\Memnara-Data`. Operator ROM directory is `D:\Memnara_Roms`.
- [ADR-008](docs/adr/ADR-008-ai-memory-knowledge-architecture.md) **ACCEPTED** 2026-09-30. No memory, RAG, UI, or M6 implementation.
- Public core separated from commercial-title integration packs. Enhanced structured-state adapters live under `D:\Memnara-Integrations` (not Git). Public tests use synthetic state. Public demo is VISION + INPUT.

## Documentation checkpoint (after M5)

- Reorganized tracked `/docs` (`adr/`, `architecture/`, `milestones/`, `games/`, `research/`).
- Proposed ADR-008 (memory / knowledge / user-control); accepted in the Unreleased rename pass above.

## Milestone 5 — COMPLETE / APPROVED

- Bounded `AgentLoop`: M4 `PerceptionContext` → one structured action → validator → ownership gate → emulator adapter.
- Meaningful progress is semantic (structured token + visual flags/`visible_text`, or a bounded dialogue/menu caption when `visible_text` is empty; visual-only still uses description). Raw pixel digest is `screen_changed` only.
- Model action JSON allows only `action` / `parameters` / `reason` / `confidence`. Metadata is application-owned.
- Local `qwen3-vl:8b` reasoning; malformed/unknown actions cannot execute; no PyBoy import in generic agent core.
- Stuck v1 (`NORMAL` → `SUSPECTED_STUCK` → `CHANGE_STRATEGY` → `EXPLORE` → halt). Coordinates optional.
- Developer demo: `python -m memnara.demo.autonomy`. Dry-run never sends input.
- Battle strategy, persistent memory, UI, voice, and conversation remain out of scope.

## Milestone 4 — COMPLETE / APPROVED

- Generic `PerceptionContext` fuses optional `VisualObservation` and `StructuredGameState` without unlabeled flattening.
- Conservative battle conflict only; RAM absence is normal; no Ollama call in fusion.
- Optional local structured-state mapping lives outside the public core; generic fusion has no PyBoy/address imports.
- Generic `StructuredFact` list is chosen at the game edge; fusion/summarizer no longer names `map_id` / `party_count` / `mode`.
- `battle_visible` remains explicit independently of `scene_type=UNKNOWN`.
- ADR-007 recorded **ACCEPTED**.

## Milestone 3 — COMPLETE / APPROVED

- Generic `VisionProvider` and loopback-only `OllamaVisionProvider` for `qwen3-vl:8b`.
- Structured `VisualObservation` with `source=VISUAL`; no RAM in the vision prompt; action keys ignored.
- Integer nearest-neighbor scale (default 3×); in-memory PNG; frame-change suppression.
- `/api/tags` + `/api/show` distinguishes installed models from vision-capable models.
- Live boot/title/room captures assessed for visual accuracy, not only JSON parse.
- Validation docs aligned to recorded `m3_live_vision.json` (boot `MENU` misclassification; START **UNUSABLE AS MENU VALIDATION**).
- Mocked provider error-path tests: timeout, unavailable, empty content/thinking, malformed structured JSON.

## Milestone 2 — COMPLETE / APPROVED

- Runtime `map_id` confidence aligned to `VERIFIED`; party subfields expose provenance on structured party fields (`SOURCE_DOCUMENTED`). Coordinates/facing/party/money/badges/mode were not promoted.

- Generic `GameAdapter` contract with a hash-pinned local structured-state implementation (maps not in public core).
- Read-only `EmulatorAdapter.read_byte` / `read_bytes`; no gameplay RAM writes.
- Title-specific identity helpers stay out of generic `rom_identity.py`.
- Live: after intro skip, starting indoor map id recorded. Party empty. Walk experiment did not move coordinates.
- Battery-save path design documented (`ram_file` is file-like in PyBoy 2.7.0).
- Unit + live tests. Historical live validation evidence is retained in the private development archive.

## Milestone 1 — COMPLETE / APPROVED

Verified emulator harness:

- Isolated project virtual environment and `pyboy==2.7.0`.
- Generic `EmulatorAdapter` with isolated `PyBoyAdapter`.
- Operator-provided GB ROM loaded from a path outside Git (not copied, not committed).
- Native 160×144 RGBA framebuffer capture, frame stepping, button input, speed control.
- Save-state write and meaningful save/load roundtrip (framebuffer changed after save; load restored saved pixels).
- Clean shutdown with `stop(save=False)`.
- Non-destructive ROM identity (header + hashes); dump hashes recorded locally and not published.
- Operator `prompts/` gitignored and removed from Git history.
- ChatGPT approved Milestone 1.

## Milestone 0 — COMPLETE / APPROVED

- Authorized research and architecture documentation.
- Git initialized locally (no remote at M0 close).
- `.gitignore`, `.env.example`, durable markdown + ADRs + research notes.
- Limited local qualification of already-installed `qwen3-vl:8b`.
- ADR-001 through ADR-006 accepted after ChatGPT review.
- Stale research/spec wording aligned with accepted ADRs (Ollama HTTP client, `pyboy==2.7.0` pin, piper1-gpl / piper-tts).
- No application implementation during M0.
