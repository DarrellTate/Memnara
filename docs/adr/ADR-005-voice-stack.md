# ADR-005 — Voice stack

**Status:** ACCEPTED  
**Date:** 2026-09-30

## Choice

- **TTS v1:** the actively maintained Piper successor **`OHF-Voice/piper1-gpl`** (Python package **`piper-tts`**) behind `VoiceProvider`. Selectable voices; generated audio under `D:\Memnara-Data` with rotation.
- **Engine license (as identified during review):** **`GPL-3.0-or-later`**.
- **STT (post-text):** **whisper.cpp** (AMD/Vulkan-friendly), not faster-whisper (CUDA).

Archived `rhasspy/piper` is **not** the current candidate.

## Engine vs voice-model licensing

- The TTS **engine** license and individual **voice-model** licenses are separate concerns.
- Every selectable or bundled voice must have its license reviewed before redistribution or bundling.
- Do **not** assume that all available Piper voices may automatically be redistributed with Memnara.
- Voice acquisition and packaging policy will be finalized during the voice milestone.

## Alternatives

Kokoro (quality, heavier setup), XTTS (clone/size), cloud TTS/STT (forbidden).

## Evidence

`docs/research/tts-stt-embeddings.md` (engine family). Successor project identity and GPL-3.0-or-later recorded here after ChatGPT review. Not installed.

## Tradeoffs

piper1-gpl / piper-tts is less “studio” than Kokoro. whisper.cpp small models miss words; acceptable for later M11. GPL-3.0-or-later on the engine affects packaging/distribution of Memnara itself and must be respected at the voice milestone.

## Consequences

No TTS/STT install in Milestone 0. Text chat first. Do not install TTS or STT under this ADR.
