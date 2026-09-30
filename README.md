# Memnara

**Persistent AI for interactive worlds.**

**A local, multi-runtime AI gaming companion framework for persistent AI identities across interactive worlds.**

**Created by Darrell Tate.**

Repository: [https://github.com/DarrellTate/Memnara](https://github.com/DarrellTate/Memnara)

## What Memnara Is

Memnara is a local-first AI agent framework for games. It is not limited to one platform and it is not limited to emulation.

Two primary runtime families are in the product design:

```text
Emulator runtimes
Native PC runtimes
```

The generic minimum gameplay path is:

```text
VISION + INPUT
```

RAM / structured state is an optional enhancement, not a universal requirement. A runtime that cannot expose RAM is still a valid Memnara runtime if it can show pixels and accept input.

Enhanced structured-state adapters for specific commercial titles are **local/private integrations**, not part of the public core.

## Current Reference Implementation

The first emulator-backed reference validation used a locally supplied Game Boy title with PyBoy, local Ollama inference, and a vision-language model.

```text
PyBoy 2.7.0
local Ollama
qwen3-vl:8b
Python 3.12
```

That title is a private validation target, not the product boundary.

## Current Capabilities

Implemented through Milestone 5 (public core):

* PyBoy launch and control behind an emulator adapter
* framebuffer capture
* optional structured state via a **locally installed** GameAdapter (not shipped in this repository)
* local VLM interpretation of screenshots
* M4 source-aware perception fusion
* bounded action proposal from a local reasoning model
* strict action validation
* ownership gate
* execution of allowlisted Game Boy buttons
* re-observation after each step
* meaningful-progress detection (semantic; pixel digest is not progress)
* stuck v1 escalation
* safe bounded termination (`max_steps` / failure / stuck halt)

The public demo path is **VISION + INPUT**. Memnara does **not** claim autonomous completion of any commercial game. M5 is a small, bounded control-loop proof.

## Current Autonomous Loop

```text
PerceptionContext
        ↓
Local reasoning model
        ↓
ActionProposal
        ↓
ActionValidator
        ↓
Control ownership gate
        ↓
GameBoyActionExecutor
        ↓
EmulatorAdapter
        ↓
PyBoy
        ↓
fresh observation
```

Current bounded actions:

```text
MOVE_UP
MOVE_DOWN
MOVE_LEFT
MOVE_RIGHT
PRESS_A
PRESS_B
PRESS_START
PRESS_SELECT
WAIT
```

Developer demo:

```text
python -m memnara.demo.autonomy --rom D:\Memnara_Roms\reference.gb --max-steps 5
```

## First Live Autonomous Proof

During a bounded validation run, the agent recognized that an in-game dialogue sequence was progressing, repeatedly selected a controller-confirm action, remained out of the stuck state, and halted at the configured step limit.

That is a small proof of a safe observe → reason → validate → execute → re-observe loop. It is not a claim of game completion. Historical live validation evidence is retained in the private development archive.

## Perception / Provenance

Vision and optional RAM stay labeled as separate sources. Fusion may combine them; it must not hide where a fact came from. Missing RAM is normal.

Structured values carry confidence concepts such as:

```text
VERIFIED
SOURCE_DOCUMENTED
INFERRED
```

## Safe Action Boundary

The model does not receive arbitrary:

```text
shell
Python execution
RAM writes
filesystem execution authority
arbitrary emulator APIs
```

Only allowlisted gameplay actions can execute, and only after validation and an ownership check.

## Ownership

```text
AI_CONTROL
USER_CONTROL
CONVERSATION
PAUSED
```

Gameplay input is allowed only in `AI_CONTROL`. Milestone 13 UX is not built; this is a programmatic gate.

## AI Profiles

```text
Models are interchangeable reasoning engines.
AI profiles are persistent identities.
```

Memory ownership is keyed by `ai_profile_id`, not by the model. Swapping models must not redefine who owns memories. Profile memory itself is **planned** (M7+); the identity rule is accepted architecture (ADR-008).

## Planned Memory Architecture

This section is **planned**. It is not implemented.

```text
LIVE CONTEXT / RECENT STEPS
        ↓
SHORT-TERM SESSION MEMORY
        ↓
reflection / consolidation
        ↓
LONG-TERM PROFILE MEMORY
```

Live context is tiny, disposable step history.

Short-term session memory is tactical. It should not become permanent memory automatically.

Long-term profile memory is durable knowledge worth keeping across sessions, stored under the owning `ai_profile_id`.

Intended store: local SQLite + FTS5. No cloud memory. No separate vector database required for v1.

## User-Controlled Memory

This section is **planned**.

The intended Memory Manager lets the user browse, search, filter, create, edit, delete, bulk-select, bulk-delete, pin/protect, and inspect provenance and related/source memories.

## Game Knowledge Packs

This section is **planned** (roadmap M8A).

```text
PERSONAL MEMORY     What I experienced.
GAME KNOWLEDGE      What I was given to read.
MODEL PRIOR         What the model already knows.
CURRENT PERCEPTION  What I observe now.
```

Planned knowledge policies:

```text
BLIND
LORE
MANUAL
GUIDED
FULL
```

Knowledge packs belong to the game/session configuration, not to an AI profile.

## Local-First

Current design direction:

* local Ollama
* local emulator
* local memory (**planned**)
* local document retrieval (**planned**)
* no required cloud service
* no cloud fallback for gameplay reasoning

Ollama model files live at `D:\Ollama\models`. Misty models at `E:\AI\.ollama\models` are off-limits.

## Project Status

```text
M0 Research + Architecture                 COMPLETE
M1 Emulator Harness                        COMPLETE
M2 RAM / State Reader                      COMPLETE
M3 Vision                                  COMPLETE
M4 Perception Fusion                       COMPLETE
M5 Basic Autonomous Control + Stuck v1     COMPLETE
```

Upcoming (not authorized until ChatGPT green-lights each one):

```text
M6   Battle handling
M7   Profile-aware persistent + session memory
M8   Memory compression / retrieval / consolidation
M8A  Game Knowledge Packs + Local RAG
M9   AI profile / personality / affect
M10  Desktop app shell + management UX
```

See [ROADMAP.md](ROADMAP.md) for the complete roadmap through M22.

## Long-Term Direction

**What happens when a persistent AI identity can actually experience games over time?**

The intended product is not a scripted bot. It is a local companion that can explore, fail, form preferences, remember, hold opinions, learn routes, use supplied knowledge under explicit user policy, talk about what it has seen, and continue across different games and runtime families without collapsing those sources into an unlabeled blob.

## Repository Structure

```text
src/memnara/      Application source (generic public core)
tests/            Automated tests (synthetic adapters; no commercial-title packs)
docs/             Versioned engineering/design documentation
.cursor/          Project development/governance tooling
```

Commercial-game-specific adapters, RAM maps, hashes, and reverse-engineering notes are **not** in this repository. They may exist only as operator-local integrations under `D:\Memnara-Integrations`.

Root project-control files stay at the repository root. Tracked `/docs` is engineering knowledge in Git; it is not runtime data and is not a shipped application bundle.

## ROMs and Game Assets

Memnara does not distribute games, ROMs, firmware, proprietary game data, copyrighted game assets, or commercial-game integration packs.

Users are responsible for supplying software/content they are legally permitted to use.

Canonical operator ROM directory: `D:\Memnara_Roms`.

## Development Philosophy

1. Local first.
2. Models do not directly execute arbitrary actions.
3. Perception sources retain provenance.
4. Missing structured game state is normal.
5. Runtime-specific code stays at the edges.
6. AI identity is separate from the reasoning model.
7. Personal memory is separate from supplied game knowledge.
8. Short-term experience is not automatically long-term memory.
9. Users retain control over memory and supplied knowledge.
10. Working behavior is validated before the roadmap advances.
11. Commercial-title integrations stay local/private, not in the public core.

## Author

Darrell Tate

Memnara is an independent project exploring persistent local AI agents inside interactive game environments.

## Project Stage

Memnara is under active development. Interfaces, paths, and package names may change. Milestone 6 and later work is not authorized by this README.
