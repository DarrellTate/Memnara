# Emulator harness (Milestone 1)

**Status:** COMPLETE / APPROVED  
**Backend:** `pyboy==2.7.0` behind `EmulatorAdapter`  
**Python:** 3.12.10 in the project virtual environment (`D:\Memnara\.venv`)  
**ROM:** operator-supplied file outside Git. Canonical ROM directory: `D:\Memnara_Roms`.

## Layout

- `src/memnara/emulators/base.py` — generic adapter (no PyBoy types)
- `src/memnara/emulators/pyboy_adapter.py` — PyBoy-only
- `src/memnara/config.py` — `MEMNARA_ROM_PATH` / `MEMNARA_DATA`
- `src/memnara/rom_identity.py` — GB header + hashes only; no RAM maps

## Headless operation

`window="null"`, `sound_emulated=False`, `stop(save=False)` so `{rom}.ram` is not written beside the operator dump.

## Verified live results (this operator dump)

| Item | Result |
|---|---|
| File size | operator dump (not published) |
| SHA-1 / SHA-256 | recorded locally; not published |
| Header title | operator dump title |
| Cartridge type | recorded locally |
| Header checksum | valid |
| Community hash match | informational only; not a Milestone 2 RAM verdict |
| Native framebuffer | 160×144 RGBA |
| Proof capture | boot screen after 600 ticks; artifact retained in the private development archive |
| Save state | roundtrip artifact retained in the private development archive |
| Tests | 19 passed (`pytest`) |

Do not commit captures, states, or ROM bytes.
