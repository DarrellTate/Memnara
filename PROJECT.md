# Memnara

Local, multi-runtime AI gaming companion: observe, reason, control, remember, and comment across **emulator-backed** and **native PC** game runtimes. Persistent identity, vision, optional approved RAM, voice, conversation, and validated input. Not a hard-coded bot.

**Current implementation:** PyBoy, optional local GameAdapter (private), M3 local VLM vision, M4 perception fusion, M5 bounded autonomy, M6 generic battle handling. The post-M6 validation patch is approved and is not a new milestone. SNES, PS1, DuckStation, and native Windows gameplay are **not** built.

**First reference / testbed:** a locally supplied Game Boy title via PyBoy. Enhanced structured-state maps are private, not public core.

Full architecture: [ARCHITECTURE.md](ARCHITECTURE.md). Roadmap: [ROADMAP.md](ROADMAP.md). State: [CURRENT_STATE.md](CURRENT_STATE.md). Multi-runtime ADR: [docs/adr/ADR-007-multi-runtime.md](docs/adr/ADR-007-multi-runtime.md). Memory/knowledge architecture: [docs/adr/ADR-008-ai-memory-knowledge-architecture.md](docs/adr/ADR-008-ai-memory-knowledge-architecture.md) (**ACCEPTED**; not implementation authority). Engineering docs index: [docs/README.md](docs/README.md). Public face: [README.md](README.md). Canonical repository URL: https://github.com/DarrellTate/Memnara

## Directory boundaries

- Source: `D:\Memnara`
- Runtime data: `D:\Memnara-Data`
- Models: `D:\Ollama\models`
- Private integrations: `D:\Memnara-Integrations`
- Off-limits: `E:\AI\.ollama\models` (Misty)

## Runtime AI

No cloud inference for screenshots, RAM, memories, chats, or voice. Internet may be used for development research only.

## Runtime families (product)

| Family | Role today | Role later |
|---|---|---|
| Emulator | PyBoy GB/GBC only | Additional platforms (SNES, PS1, GBA, …) |
| Native PC | Not implemented | Screen capture + keyboard/mouse; RAM optional |

Generic play path: **VISION + INPUT**. RAM is an enhancement.

## Requirements to milestones

| Requirement | Subsystem | Implement | Verify |
|---|---|---|---|
| Vision | perception/vision | M3 | Fixture + live screenshots |
| RAM (fair) | games adapter | M2 | Parser tests vs dump hash |
| Perception fusion | state builder | M4 | Labeled context tests |
| Basic control | control + loop | M5 | Navigate a known area (emulator reference) |
| Generic battle handling | agent loop | M6 | Recognize a battle from labeled perception and take bounded actions. Approved. Not title-expert play. |
| Memory persist | memory | M7 | Restart recall; profile-aware; session memory; CRUD/reset primitives |
| Compression / retrieval | memory | M8 | Consolidation; FTS5; lineage |
| Game knowledge packs | knowledge | M8A | Local RAG; packs not personal memory |
| AI profile / personality / affect | agent | M9 | Commentary consistency |
| Desktop app shell / selectors / memory UX | UI | M10 | Selectors + input mapping + Memory/Knowledge Manager |
| Voice | voice | M11 | Spoken commentary |
| Conversation pause/resume | conversation | M12 | Same identity + re-observe |
| Manual takeover | control ownership | M13 | Single owner, re-observe |
| Autonomous reference-title progression | local adapter + loop | M14 | Progression with stuck handling |
| Stuck recovery | stuck detector | M5–M14 | Escalation log |
| New-run learning | memory scopes | M15 | New save, old lessons |
| Second game / GameAdapter | GameAdapter | M16 | Incremental second-game proof; **not** the finished cross-runtime proof |
| Multi-profile / model-swap | identity + models | M17 | Profile and model replaceability |
| Runtime abstraction | GameRuntime | M18 | Capabilities advertised |
| Second emulator family | runtime backend | M19 | New platform, same core |
| Native Windows runtime | capture + input | M20 | No RAM required |
| Vision-only native play | VISION + INPUT | M21 | Generic path proof |
| Cross-runtime profile | memory + identity | M22 | Same profile architecture across runtime families |
| Local-only | ModelProvider | M0+ | No cloud deps |
