---
name: emulator-integration
description: Memnara emulator harness workflow for launch, framebuffer, input, frame stepping, timing, saves, and adapter isolation. Use when building or reviewing emulator integration after an emulator is formally selected.
---

# Emulator Integration

Use only for authorized emulator work. The **current** authorized emulator backend is PyBoy (ADR-001). Do not assume mGBA or another emulator is selected until the project formally selects it. This skill also applies to a later selected emulator (e.g. M19). Memnara’s long-term product includes a **native PC** runtime family (ADR-007); this skill covers emulator backends only. Native capture/input is a separate authorized milestone.

## Inspect

- Official emulator documentation and API for the selected emulator only.
- The emulator adapter interface, not the agent core.
- Recorded emulator version and integration-test fixtures, if present.

## Workflow

1. Confirm an emulator has been formally selected. If not, stop and report.
2. Verify documented APIs before relying on them.
3. Implement or review behind an emulator abstraction.
4. Cover launch/connect, ROM load path (user-provided only), framebuffer/screenshot access, input, frame stepping, timing/speed control, and save or save-state behavior where the selected API actually supports it.
5. Add error handling for launch failure, disconnect, and invalid ROM path.
6. Record the emulator version used.
7. Add integration tests or fixtures for the verified behaviors.

## Verify

- Screenshot/framebuffer capture works on the selected emulator.
- Button or input injection works.
- Frames can be advanced as documented.
- Failures do not become arbitrary host command execution.
- Agent core has no emulator-specific imports or addresses.

## Do not assume

- That PyBoy or mGBA is the chosen emulator.
- That an API exists because it would be convenient.
- That save-states are available without verification.
- That ROMs may be downloaded or committed.

## Expected outputs

- Emulator adapter changes only.
- Recorded version and verified capability notes.
- Integration-test evidence labeled verified or unverified.

## Stop

Stop when the authorized emulator scope is complete or when a required API is unverified. Do not start game-adapter or agent-core work unless that was also authorized.
