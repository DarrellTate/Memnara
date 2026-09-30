# ADR-008 — AI Memory, Knowledge, and User-Control Architecture

**Status:** ACCEPTED  
**Date:** 2026-09-30  
**Accepted:** 2026-09-30

This ADR extends, and does not replace, ADR-004 (SQLite, no vector DB in v1). It records product-owner requirements for memory ownership, hierarchy, user control, and Game Knowledge Packs. **It does not authorize implementation.** M7+ remain unauthorized until ChatGPT green-lights them.

## Context

M0–M5 are complete and approved. Persistent memory, RAG, UI, and M6 battle handling are not implemented. ADR-004 already chose SQLite as the local system of record. The product owner requires:

- memory owned by the AI profile, not by the model;
- hierarchical live / short-term / long-term memory;
- consolidation rather than persisting every event;
- first-class user CRUD, bulk reset, and blind new-run workflows;
- Game Knowledge Packs as a separate concept from personal memory.

## Decision

### A. Memory belongs to the AI profile

Persistent identity is keyed by `ai_profile_id`, never by model.

```text
AI profile owns memory.
Model is a replaceable reasoning engine.
```

Two personalities may temporarily use the same model and retain completely separate memories. A personality may change models without losing, resetting, or changing ownership of its existing memories.

Record model provenance separately, for example `model_id_at_creation`. That field is metadata only, not ownership.

### B. Hierarchical memory

Memnara will use at least three memory/context layers:

```text
1. LIVE CONTEXT / RECENT STEP HISTORY
2. SHORT-TERM SESSION / WORKING MEMORY
3. LONG-TERM PROFILE MEMORY
```

**Live context.** High-frequency immediate control history (pressed UP, screen unchanged, dialogue advanced, recent action failures). Tiny, bounded, disposable. Not normal user-facing long-term memory. M5 in-memory `RecentStep` history is this class of data.

**Short-term session / working memory.** Tactical information for the active game/session (already checked this corner, east door appears blocked, currently trying to find the exit). Available during reasoning. It should normally **not** become permanent memory directly. Optional crash recovery/checkpointing is allowed, but it remains logically distinct from permanent profile memory.

**Long-term profile memory.** Durable information worth carrying across sessions (evolutions, completed quests, major objectives, explored maps, preferences). Stored under the owning `ai_profile_id`.

### C. Memory consolidation

Do not persist every gameplay event directly as long-term memory.

```text
gameplay experience
→ short-term/session memory
→ reflection/consolidation
→ selected durable memories
→ SQLite long-term store
```

Consolidation may occur at major events, periodic session checkpoints, session end, and optional idle/reflection time. Exact scheduling is future implementation work.

A high-volume sequence such as checked room / walked east / hit wall / found stairs may later consolidate into a single durable summary of the useful route.

### D. Memory types

Schema should support categories equivalent to at least:

```text
EPISODIC / EVENT
SEMANTIC / STATE
PREFERENCE / OPINION
NAVIGATION / WORLD
GOAL / OBJECTIVE
RELATIONSHIP
LESSON
USER_CREATED
CONSOLIDATED_SUMMARY
```

Exact enum names are not frozen by this ADR.

### E. Memory scopes

Memory must support filtering/scoping equivalent to:

```text
GLOBAL
GAME
RUN
SESSION
```

Useful identifiers: `ai_profile_id`, `game_id`, `run_id`, `session_id`.

Examples: global personality preference; title-specific knowledge; a specific playthrough; current session working memory.

### F. Provenance / lineage

Records need enough metadata for retrieval and user management. Plan for fields equivalent to:

```text
memory_id
ai_profile_id
scope
game_id
run_id
session_id
memory_type
content
importance
confidence
provenance
model_id_at_creation
created_at
updated_at
last_reinforced_at
tags
source_memory_ids
source_game_ids
```

Exact schema is designed at M7.

Derived/consolidated memories must retain lineage. Example: “I dislike maze-like areas” may derive from experiences across multiple games. Deleting one game’s memories should not necessarily erase a global memory also supported by other titles. The architecture must make this reconciliation possible.

### G. User memory control / CRUD

Memory management is a first-class product feature. The final application must allow the user to browse, search, filter, create, edit, delete, bulk-select, bulk-delete, pin/protect, inspect provenance, and inspect related/source memories.

User-created or user-edited memories must be clearly provenance-labeled. Do not pretend manually created memories were organically learned.

### H. Required filters / reset operations

The memory interface must support filtering and bulk operations by at least: AI profile, game, run, session, memory type, scope, date/date range, model used when memory was created, importance, provenance, tags.

Required workflows include: delete all memories for one game for a named profile; delete memories from one run; delete memories created during a date range; delete memories created while using Model X; delete selected categories; reset a game’s memories without deleting the AI profile.

### I. Blind new run

The product must support a first-class blind-run workflow. Conceptually:

```text
Start New Run
AI Profile: Misty
Game: (local title)

Prior Personal Memory:

○ Keep all game memories
○ Keep general memories, forget run details
● Blind — forget all experience for that game
○ Custom
```

Resetting game memory must **not** reset profile identity, personality, memories from unrelated games, or user relationship memories unless explicitly selected.

### J. Memory UI organization

The user must not be presented with an overwhelming raw database table. Normal Memory Manager UX should organize information semantically (Overview / Games / Timeline / Search / Filters). Raw telemetry/step history should not pollute the normal memory browser. An advanced/debug view may expose session internals later.

### K. Memory storage technology

Preserve ADR-004:

```text
SQLite
```

Long-term source of truth remains local. Initial retrieval:

```text
SQLite metadata filtering
+ SQLite FTS5
+ importance
+ recency
+ scope
```

No separate vector DB is required for v1. Architecture may later support local embeddings/hybrid retrieval without replacing profile ownership semantics. No cloud memory.

### L. Game knowledge is not personal memory

Add a separate first-class concept: **Game Knowledge Pack**.

This represents documents intentionally supplied to the AI (manual, lore, story recap, mechanics guide, beginner guide, strategy guide, walkthrough).

Hard distinction:

```text
PERSONAL MEMORY     "What I experienced."
GAME KNOWLEDGE      "What I was given to read."
MODEL PRIOR         "What the base model already knows."
CURRENT PERCEPTION  "What I observe now."
```

Do not silently turn Game Knowledge chunks into personal memories. Game knowledge and personality memory must remain logically and physically separable.

### M. Game Knowledge Packs / local RAG

Plan a new roadmap milestone **M8A — Game Knowledge Packs + Local RAG** between M8 and M9. Do not renumber M0–M22.

Initial planned capabilities: TXT / Markdown / PDF ingestion, local chunking/indexing, game-scoped packs, activate/deactivate packs, document-level enable/disable, category metadata, source/provenance, bounded retrieval, local-only operation, no cloud dependency. HTML/ePub may remain future extensions.

### N. Knowledge policies

Plan configurable knowledge levels equivalent to:

```text
BLIND    No provided knowledge.
LORE     Background/story/world information.
MANUAL   Lore + controls/mechanics/manual-level knowledge.
GUIDED   Manual + beginner tips/guides.
FULL     Strategy guides/walkthroughs allowed.
```

Names may be refined later. The requirement is explicit user control over what prior information the AI may use.

### O. Knowledge pack ownership

Knowledge packs belong to the game/session configuration, not to an AI profile. Profiles may share the same supplied source documents while keeping separate personal memories.

Knowledge retrieval must be scoped by `game_id`, `knowledge_pack_id`, `document_id` (or equivalent). No cross-game retrieval contamination.

### P. Future reasoning context

Desired future bounded reasoning context (every section provenance-labeled; do not collapse into an unlabeled blob):

```text
CURRENT PERCEPTION
CURRENT GOAL
LIVE/RECENT CONTEXT
SHORT-TERM SESSION MEMORY
LONG-TERM PROFILE MEMORY
GAME KNOWLEDGE
RECENT ACTION HISTORY
```

## Alternatives

- Model-keyed memory: rejected; swapping models would orphan or merge personalities.
- Persist every step as long-term memory: rejected; volume and UX would be unusable.
- Vector DB as v1 source of truth: rejected by ADR-004.
- Mixing walkthrough chunks into personal memory: rejected; provenance and blind-run would be dishonest.

## Consequences

- M7 owns schema, ownership, session/working memory, CRUD and reset primitives. Not authorized by this ADR.
- M8 owns consolidation and FTS5 retrieval. Not authorized by this ADR.
- M8A owns Game Knowledge Packs and local RAG. Not authorized by this ADR.
- M9 remains personality/affect; it does not take ownership of memory rows.
- M10 owns Memory Manager and Knowledge Manager UX in addition to existing selectors.
- No application code, SQLite schema, RAG pipeline, or UI is implemented in this documentation task.

## Status

**ACCEPTED** on 2026-09-30. This ADR does not authorize M6, M7, M8, M8A, M9, M10, or other implementation.
