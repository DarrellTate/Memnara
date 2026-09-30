---
name: milestone-execution
description: Canonical Memnara workflow for one authorized milestone. Use when implementing, testing, documenting, or closing an approved milestone, or when the user relays a ChatGPT milestone authorization.
---

# Milestone Execution

Apply this skill only when ChatGPT has authorized a specific milestone or equivalent scoped task. This skill does not itself authorize implementation.

## Inspect

- The exact authorization text (scope and acceptance criteria).
- Current project state documentation, if it exists and is in scope.
- Only the components required for this milestone.

## Workflow

1. Read the exact authorization.
2. Read current project state.
3. Confirm scope and acceptance criteria. Stop and report if they are missing or conflicting.
4. Inspect only relevant components.
5. Implement only approved scope.
6. Test.
7. Verify acceptance criteria with evidence.
8. For milestone completion reviews, invoke in order: `architect-reviewer` → `code-reviewer` → `test-reviewer`, plus applicable specialists. `code-reviewer` is read-only and cannot inherit `IMPLEMENT`.
9. Update authorized project documentation if the authorization requires it.
10. Produce the required user response and ChatGPT handoff.
11. When the milestone reaches `COMPLETE / AWAITING CHATGPT REVIEW` (or ChatGPT requests a review package), follow `review-handoff`. That skill packages requested evidence; it is not a reviewer.
12. Stop.

## Verify

- Acceptance criteria were demonstrated, not assumed.
- Results are labeled verified, mocked, inferred, or unverified.
- No files or systems outside the authorized scope were changed.

## Do not assume

- That completing this milestone authorizes the next one.
- That "continue" means start the next milestone.
- That undocumented architecture changes are allowed.

## Expected outputs

- Working changes limited to the authorized milestone.
- Test evidence against acceptance criteria.
- Response for User and Handoff for ChatGPT.
- If ChatGPT requests a review package, an evidence-complete handoff per `review-handoff` (verbatim material, not a summary of files read).

Conceptual close-out:

```text
implementation
    ↓
architect-reviewer
    ↓
code-reviewer
    ↓
test-reviewer
    ↓
review-handoff
    ↓
ChatGPT approval
```

## Stop

Stop when the authorized milestone is complete or blocked. Do not roll into the next milestone without a new explicit authorization.
