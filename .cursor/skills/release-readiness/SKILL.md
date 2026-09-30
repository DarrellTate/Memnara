---
name: release-readiness
description: Memnara milestone and release gate that checks acceptance criteria, tests, local-only runtime, action safety, storage, and persistence. Use before declaring a milestone, version, or release complete.
---

# Release Readiness

Do not declare a release or milestone ready merely because the program launches.

## Inspect

- Authorized acceptance criteria.
- Test results and fixture coverage.
- Documentation and project-state files that were authorized to exist.
- Action registry, secrets handling, and storage usage.

## Workflow

For milestone completion, the implementation/data-flow gate is `code-reviewer` (read-only; never `IMPLEMENT`), between `architect-reviewer` and `test-reviewer`.

Validate all of the following before any completion claim:

1. Approved acceptance criteria demonstrated.
2. Test state recorded; critical paths not only mocked unless explicitly labeled.
3. Documentation matches the delivered behavior.
4. Local-only runtime requirement intact (no cloud AI runtime dependency).
5. Action safety: unknown actions rejected; no arbitrary host execution.
6. Storage budget respected; 10–15 GB D: reserve not threatened.
7. Persistence and recovery after restart verified if in scope.
8. Known issues and unresolved TODOs listed.
9. Dependency integrity (names and versions verified).
10. Secrets and large artifacts kept out of Git.
11. Project state documentation is consistent with reality.

## Verify

- Each acceptance criterion has evidence.
- Unverified items are labeled unverified, not marked done.
- ROM, model, and credential files are not committed.

## Do not assume

- That a successful launch equals Version 1.0 or milestone completion.
- That undocumented known issues can be omitted.

## Expected outputs

- Ready / not-ready verdict with evidence.
- Open issues list.
- Storage and local-only confirmation.
- If ChatGPT requests the final review package, package it per `review-handoff` (requested evidence itself, not a summary of files read).

## Stop

Stop after the readiness verdict. A "not ready" result is a valid completion of this skill. Do not start the next milestone to "make it ready" without authorization.
