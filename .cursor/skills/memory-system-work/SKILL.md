---
name: memory-system-work
description: Memnara workflow for multi-scope memory, retrieval, hierarchical compression, persistence, and cross-game contamination prevention. Use when designing, implementing, or reviewing the memory subsystem.
---

# Memory System Work

Memory is a high-risk architectural subsystem. Do not implement it as one giant transcript.

## Inspect

- Memory scopes and storage location (`D:\Memnara-Data` for databases and generated memory artifacts).
- Scope tags, importance scores, and retrieval query path.
- Compression/summarization pipeline.
- Restart/reload persistence path.

## Workflow

1. Keep these scopes distinct: working, session, run, game, series/genre, cross-game, personal.
2. Tag knowledge with scope (for example universal, genre, series, game, run) or an approved equivalent.
3. Assign explicit importance. Defining memories must survive compression.
4. Retrieve only relevant memories (semantic, game, run, location, goal, entities, importance, recency, emotional significance, scope).
5. Compress hierarchically: raw events → episode → session → run → game knowledge → cross-game lessons.
6. Verify summaries preserve important facts; do not silently drop high-importance items.
7. Prevent cross-game contamination (title-specific mechanics must not be applied as facts to unrelated games).
8. Persist identity, knowledge, and run context so a restart restores continuity. Memory is profile-keyed (`ai_profile_id`); changing runtime or model does not create a new identity.

## Verify

- Restart recovers persisted memories.
- Retrieval does not dump the entire store into every prompt.
- Compression preserves high-importance events.
- Scope tags prevent unjustified transfer.

## Do not assume

- That more context is always better.
- That a new run should forget prior game knowledge.
- That lessons from one game automatically apply to another.

## Expected outputs

- Scoped memory writes and retrieval behavior.
- Compression evidence with preserved important facts.
- Persistence/recovery test notes.

## Stop

Stop when the authorized memory scope is complete or when a design choice would mix scopes or drop defining memories. Do not redesign unrelated subsystems.
