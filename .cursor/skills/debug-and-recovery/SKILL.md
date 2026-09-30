---
name: debug-and-recovery
description: Reproduction-first Memnara debugging workflow that isolates the smallest failing subsystem and avoids speculative rewrites. Use when diagnosing errors, regressions, emulator failures, or unexpected agent behavior.
---

# Debug and Recovery

Prefer the smallest justified fix. Avoid broad speculative rewrites.

## Inspect

- Reproduction steps.
- Relevant logs and state (bounded; no secret or huge screenshot dumps unless authorized).
- The smallest subsystem that can fail independently.

## Workflow

1. Reproduce.
2. Capture logs/state needed to understand the failure.
3. Reduce to the smallest failing subsystem.
4. Form one specific hypothesis.
5. Make the smallest justified change.
6. Re-test the reproduction.
7. Add regression protection where appropriate.
8. Document the root cause.
9. Report remaining uncertainty as unverified if needed.

## Verify

- The original reproduction no longer fails, or the remaining failure is documented.
- The change stayed inside authorized scope.
- Persistent memory was not corrupted by the failure or the fix.

## Do not assume

- That rewriting a layer will fix an unisolated symptom.
- That a model hallucination is an emulator bug, or the reverse, without evidence.

## Expected outputs

- Root-cause note.
- Minimal fix and re-test evidence.
- Remaining uncertainties labeled.

## Stop

Stop when the authorized defect is fixed or clearly blocked. Do not expand into unrelated refactors.
