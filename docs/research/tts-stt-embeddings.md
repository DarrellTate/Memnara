# Local embeddings, TTS, and STT (no installs)

**None of these models or engines were downloaded or installed in Milestone 0.**

## Embeddings

**Recommendation for Version 1:** start **without** a dedicated embedding model. Use SQLite + FTS5 (lexical) plus structured filters (game, run, location, importance, recency, scope). Add embeddings only if retrieval quality is proven insufficient.

If later authorized: **nomic-embed-text** via Ollama (`/api/embed`), ~274 MB on disk (https://ollama.com/library/nomic-embed-text). Fits local-only and the same `ModelProvider` host. **Do not pull until ChatGPT authorizes.**

Standalone vector DBs (Chroma, Qdrant server) are unnecessary for v1 and cost ops/disk.

## TTS (selectable local voice)

Compare (research only):

| Engine | Notes | Disk (order of magnitude) | Windows/AMD |
|---|---|---|---|
| **OHF-Voice/piper1-gpl** (`piper-tts`) | Current selected implementation; ONNX voices; low latency; many voices. Engine license currently identified as **GPL-3.0-or-later**. Voice-model licenses are independent and must be reviewed individually before bundling or redistribution. Archived **`rhasspy/piper`** is **not** the selected current implementation. | tens–hundreds of MB per voice | Practical; official Windows wheels/binaries exist in the Piper lineage |
| **Kokoro-82M** | Apache weights; higher naturalness than tiny Piper in many reports; Python `kokoro` | ~80M params + voices; hundreds of MB | Windows needs espeak-ng; GPU optional |
| **XTTS / successors** | Voice cloning, heavier VRAM, slower, more disk | multi-GB class | Overkill for v1 commentary |

**Recommendation:** **OHF-Voice/piper1-gpl** (Python package **`piper-tts`**) as default v1 TTS (latency + disk + offline + voice list). Keep `VoiceProvider` swappable so Kokoro can be a possible future quality alternative. **Do not install TTS in M0.**

## STT (after text chat)

This machine is **AMD GPU**, not NVIDIA. **faster-whisper** is CUDA-centric. **whisper.cpp** supports Windows and Vulkan — better AMD alignment.

**Recommendation:** architecture for **whisper.cpp** (small/base English model first, on-demand). Text chat is v1; mic is M11+ extension. **Do not install in M0.**

## Storage note

TTS voices + a small Whisper model might add **0.2–2 GB** depending on quality. Budget under `D:\Memnara-Data` / a Memnara models dir, never Misty E:.
