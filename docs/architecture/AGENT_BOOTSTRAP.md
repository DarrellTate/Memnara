# Agent bootstrap

A fresh Cursor/AI coding agent should read this after opening the Memnara workspace and reconstruct project state **without** prior chat history.

Do not implement or advance milestones while bootstrapping unless a later message explicitly authorizes it.

## Read in this order

1. [AGENTS.md](../../AGENTS.md)
2. [PROJECT.md](../../PROJECT.md)
3. [CURRENT_STATE.md](../../CURRENT_STATE.md)
4. [ROADMAP.md](../../ROADMAP.md)
5. [ARCHITECTURE.md](../../ARCHITECTURE.md)
6. [DECISIONS.md](../../DECISIONS.md)
7. [CHANGELOG.md](../../CHANGELOG.md)
8. [docs/adr/ADR-001-emulator-selection.md](../adr/ADR-001-emulator-selection.md) through [ADR-008](../adr/ADR-008-ai-memory-knowledge-architecture.md)
9. Current relevant milestone documentation under [docs/milestones/](../milestones/)

## Non-negotiable project facts

```text
Product: Memnara

Tagline:
Persistent AI for interactive worlds.

M0–M5:
COMPLETE / APPROVED

M6:
COMPLETE / APPROVED

POST-M6 PATCH #1:
COMPLETE / APPROVED

POST-M6 PATCH #2:
COMPLETE / APPROVED

POST-M6 PATCH #3:
COMPLETE / APPROVED

POST-M6 PATCH #4:
COMPLETE / APPROVED

POST-M6 PATCH #5:
COMPLETE / APPROVED

POST-M6 PATCH #6:
COMPLETE / APPROVED

POST-M6 PATCH #7:
COMPLETE / APPROVED

POST-M6 PATCH #8:
PLANNED / NOT AUTHORIZED

POST-M6 AFFECT PROTOTYPE:
PLANNED / NOT AUTHORIZED

POST-M6 VOICE SPIKE:
PLANNED / NOT AUTHORIZED

M7:
NOT AUTHORIZED

ADR-001–ADR-008:
ACCEPTED

North star:
local, multi-runtime AI gaming companion framework

Generic runtime minimum:
VISION + INPUT

Structured state:
optional enhancement

AI identity:
owned by ai_profile_id

Models:
replaceable reasoning engines

Memory:
profile-owned, hierarchical, provenance-aware

Game knowledge:
separate from personal memory

Commercial-game integrations:
external/private, never public core

Misty:
separate project

E:\AI\.ollama\models:
ABSOLUTELY OFF-LIMITS
```

## Governance

```text
Do not advance milestones without explicit authorization.
Reviewers do not implement unless specifically authorized.
Do not treat "continue" as next-milestone authorization.
Do not silently broaden scope.
```

User is product owner. ChatGPT is project manager / architect / green-light. Cursor implements only authorized scope.

## Canonical paths

```text
D:\Memnara                 public source workspace
D:\Memnara-Data            runtime / generated data
D:\Memnara_Roms            operator-supplied game files
D:\Memnara-Integrations    private local GameAdapter packs
D:\Ollama\models           Ollama model store used by Memnara
E:\AI\.ollama\models       Misty — do not touch
```

```text
tracked in source repository
≠ shipped with final application distribution
```
