# ADR-002 — Initial game target

**Status:** ACCEPTED  
**Date:** 2026-09-30  
**Clarified:** 2026-09-30 (public core: hash-pinned local reference; maps are not in the public repository)

## Choice

The first enhanced GameAdapter is a **hash-pinned local Game Boy title**. ROM identity = region + revision + SHA-1 of the operator’s dump. Same-engine revisions still require their own hash pin. Later series titles are later adapters.

## Alternatives considered

- Another cart of the same engine: valid if the operator’s dump matches that profile — swap adapter profile, don’t mix hashes.
- A later handheld revision: addresses are **not** interchangeable without verification.

## Evidence

Community disassembly maps are corroboration only. Live verification is against the operator dump hash. Title-specific maps live in a **private local integration**, not in the public Memnara core.

## Tradeoffs

- First parser is simpler on a well-documented GB engine.
- The user must own and dump a matching cart they are legally permitted to use.

## Consequences

No title-specific addresses in the agent core. Milestone 2 verifies against the user’s dump hash inside the private integration. Public tests use synthetic structured state.

## Clarification (2026-09-30)

The first local reference title remains the private validation testbed through initial autonomy, profile, memory, and UI work. It is not the only long-term Memnara game. Generic play must not require a RAM adapter (ADR-007). Enhanced structured-state work is preserved locally; it is not shipped in the public repository.
