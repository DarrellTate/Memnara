# Legitimate ROM workflow (Milestone 0 — documentation only)

**No ROM was downloaded. No piracy sources are listed.**

Memnara accepts a **user-provided dump** of a cartridge the user owns. The file stays outside Git (`*.gb` / `*.gbc` in `.gitignore`) and should live under a path in `D:\Memnara-Data` or a user-configured `rom_path`, never in the source tree.

## Hardware options (examples, not endorsements of a single vendor)

To dump a physical Game Boy / GBC cartridge:

- **GBxCart RW** (insideGadgets): USB reader/writer for GB, GBC, and GBA carts. Official site: https://www.gbxcart.com/ — backup ROM and saves. Open-source companion software commonly used: **FlashGBX**.
- Other legitimate cart dumpers exist; pick maintained hardware with clear licensing and Windows support at purchase time.

This document does not sell hardware. It records that a **physical cart + USB dumper + official/open dumper software** is the intended path.

## How the file enters Memnara (later milestones)

1. User dumps `reference.gb` (name is an example) to e.g. `D:\Memnara-Data\roms\`.
2. Configuration (`rom_path`) points at that file. No hard-coded machine path in source.
3. On load, Memnara records size, SHA-1, and header title. If they do not match a locally installed adapter’s expected profile, refuse to apply that adapter’s structured map (or run in an explicit “unverified dump” debug mode that does not claim RAM maps are valid).
4. Saves and PyBoy states go to `D:\Memnara-Data`, gitignored.

## Verification

Milestone 2 must compare live RAM against cited community maps **only** after the dump hash is known. Until then, addresses remain **unverified**.

## Git

ROMs, dumps, and save-states that contain ROM-derived data stay out of Git (see repository `.gitignore`).
