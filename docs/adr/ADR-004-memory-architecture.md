# ADR-004 — Memory architecture

**Status:** ACCEPTED  
**Date:** 2026-09-30

## Choice

**SQLite** in `D:\Memnara-Data` as the system of record: scoped rows (working/session/run/game/series/cross-game/personal), importance 0–5, FTS5, hierarchical summaries as rows with provenance. **No dedicated vector DB in v1.** Embeddings deferred.

## Alternatives

- JSON files only: poor query/concurrency.
- Vector DB now: extra disk/complexity before lexical+filters are proven.

## Evidence

Local-only, inspectable, backup = copy file, portable, matches storage budget. See memory sections in `ARCHITECTURE.md`.

## Tradeoffs

Semantic recall weaker until embeddings authorized. Compression must not drop importance ≥ 4.

## Consequences

`MemoryStore` API only; no implementation in M0.
