# Milestone 1 specification

**Status:** COMPLETE / APPROVED

## Scope (unchanged)

Emulator harness only. No title-specific RAM parser, VLM loop, memory DB, UI, TTS, or Milestone 2 work.

## Dependency pin

**`pyboy==2.7.0`** installed and recorded. PyPI check immediately before install: 2.7.0 current non-yanked; 2.7.1 yanked.

## Layout

`pyproject.toml`, `src/memnara/emulators/base.py`, `src/memnara/emulators/pyboy_adapter.py`, tests. ROM remains outside Git.

## Acceptance (demonstrated locally)

- Python launches PyBoy with configured operator ROM.
- Screenshot captured outside Git. Historical live validation evidence is retained in the private development archive.
- Button + tick demonstrated.
- Save-state roundtrip: framebuffer changed after save, load restored the saved pixels.
- Adapter interface has no title-specific RAM addresses.

## Tests

Unit tests run without a ROM. Live integration tests skip if the ROM is absent. Local operator run: 19 passed.
