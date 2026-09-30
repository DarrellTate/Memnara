# Decisions

ADR-001 through ADR-008 are **ACCEPTED**.

```text
M0–M6 COMPLETE / APPROVED
POST-M6 PATCH #1 COMPLETE / APPROVED
POST-M6 PATCH #2 COMPLETE / APPROVED
M7 AUTHORIZED NO
```

Milestone 6 is **COMPLETE / APPROVED**. The first post-M6 validation patch is **COMPLETE / APPROVED**. The second post-M6 movement patch is **COMPLETE / APPROVED**. Neither is a new milestone. ADR-008 is accepted architecture; it does not authorize memory, RAG, UI, or M7 implementation.

| ID | Title | Status |
|---|---|---|
| ADR-001 | First emulator adapter = PyBoy; M1 pin `pyboy==2.7.0` (not the universal runtime) | ACCEPTED |
| ADR-002 | First enhanced game = hash-pinned local Game Boy title; private maps; not the sole long-term game | ACCEPTED |
| ADR-003 | Local Ollama HTTP client + qwen3-vl:8b | ACCEPTED |
| ADR-004 | SQLite memory, no vector DB in v1 | ACCEPTED |
| ADR-005 | piper1-gpl / piper-tts; whisper.cpp STT later | ACCEPTED |
| ADR-006 | PySide6 UI | ACCEPTED |
| ADR-007 | Multi-runtime + capability architecture (emulator families + native PC; VISION+INPUT generic path) | ACCEPTED |
| ADR-008 | AI memory, knowledge, and user-control architecture | ACCEPTED |

Files: `docs/adr/`.
