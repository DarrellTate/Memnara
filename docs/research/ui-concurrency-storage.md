# UI, concurrency, and Version 1 storage budget

## UI recommendation

**Choice:** **PySide6 (Qt)** for the desktop dashboard.

| Option | Pros | Cons |
|---|---|---|
| PySide6 | Native window, easy image widget for framebuffer, buttons for takeover, local-only, mature | Qt packaging size; GPL/LGPL awareness for distribution |
| Local web UI | Fast to iterate chat | Extra process, browser chrome, weaker “sitting beside the TV” feel |
| Dear ImGui / custom GL | Fast overlay | More work for chat/accessibility |

Emulator view = QLabel/QGraphicsView of the 160×144 (or integer-scaled) RGB frame. Chat, mood, goal, plan, control mode buttons on the side. Do not embed a second emulator window.

**Do not implement UI in Milestone 0.** ADR-006.

## Concurrency recommendation

**Hybrid:**

- **Emulator thread** (or dedicated loop): `tick()` must not wait on the VLM.
- **Asyncio** in the agent/UI process for Ollama HTTP, TTS queue, and chat.
- **One inference slot** (mutex): no overlapping VLM calls.
- TTS on a worker so speech does not block ticks.
- SQLite writes on a single writer thread.

Avoid a process-per-subsystem in v1 (save RAM). Risks: GIL vs PyBoy C extensions (usually OK); never block the emulator on 6–30 s inference.

## Version 1 storage budget (estimates)

Starting D: free **64.11 GB** (measured). Reserve **10–15 GB**.

| Item | Estimate | Notes |
|---|---|---|
| `qwen3-vl:8b` | ~6.1 GB | already present |
| Git source + docs | < 50 MB | |
| PyBoy + venv (later) | ~0.2–0.5 GB | not installed |
| Piper voice(s) | ~0.05–0.4 GB | not installed |
| Whisper small | ~0.2–0.5 GB | not installed |
| Optional nomic-embed | ~0.27 GB | not installed |
| SQLite memory DB | grow with caps; target < 1 GB year-one with compression | design, not measured |
| Captures / audio | **rotate**; budget 2 GB cap | |
| PyBoy states | small; gitignore | |
| **Working total (v1)** | **~10–12 GB** used by Memnara-related files if all optionals installed | **estimate** |
| **Headroom vs 64 GB free** | ample if captures bounded | **estimate** |

Plans that would add another 8B+ model without deleting anything **threaten** the reserve. Flagged for `storage-auditor`.

## Disk-space pressure

If D: free < 15 GB: stop capture retention, skip TTS wav archive, refuse new model pulls.
