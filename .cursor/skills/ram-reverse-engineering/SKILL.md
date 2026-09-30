---
name: ram-reverse-engineering
description: High-confidence Memnara process for identifying, validating, documenting, and classifying game RAM values. Use when mapping game memory, writing parsers, or reviewing address claims.
---

# RAM Reverse Engineering

Treat guessed addresses as unverified. Never present them as fact.

## Inspect

- Exact game title and ROM version.
- Authoritative or community memory-map sources, with citation.
- Live or fixture dumps from the same version.
- Fair-RAM policy (player-available vs privileged/hidden).

## Workflow

1. Confirm game and ROM version before any address work.
2. Collect candidate values from cited documentation.
3. Experimentally validate each candidate against expected vs actual values on that version.
4. Document address, size, struct layout, source, and confidence (verified, inferred, or unverified).
5. Classify each value as player-available or privileged/hidden.
6. Put mappings in a private local GameAdapter, not the public agent core.
7. Write parser tests from fixtures for verified fields.
8. Flag version-specific differences explicitly.

## Verify

- Address, meaning, and struct match the target version.
- Tests fail if bytes are wrong.
- Privileged values are not exposed to the agent by default.
- Confidence labels are present.

## Do not assume

- That a published map applies to a different revision.
- That an address is verified because it compiled or "looks right."
- That every readable RAM value should be given to the AI.

## Expected outputs

- Game-adapter memory map with source and confidence.
- Parser tests for verified fields.
- Fair-RAM classification notes.

## Stop

Stop when authorized RAM scope is documented and tested, or when a value cannot be validated. Leave unverified addresses labeled unverified.
