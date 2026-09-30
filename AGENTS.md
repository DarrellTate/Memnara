# Agents

Memnara is a local multi-runtime companion (see [ADR-007](docs/adr/ADR-007-multi-runtime.md) and [ARCHITECTURE.md](ARCHITECTURE.md)). **Current public code** is PyBoy + generic VISION + INPUT + M3 vision + M4 fusion + M5 bounded autonomy. Enhanced structured-state maps live in private local integrations, not in this repository.

## Roles

- **User:** owner, operator, tester.
- **ChatGPT:** project manager, architect, green-light.
- **Cursor (primary):** integrator, docs, tests when authorized.

## Specialists (project `.cursor/agents`)

Default RESEARCH/REVIEW. `IMPLEMENT` only if the parent task grants it **and** the agent is writable. `readonly: true` agents never implement, including when a parent delegates `IMPLEMENT`. Automatic selection ≠ implementation authority.

### Milestone completion review order

```text
architect-reviewer
 ↓
code-reviewer
 ↓
test-reviewer
 ↓
review-handoff
```

Specialist reviewers still participate where applicable. `review-handoff` is a packaging skill, not a reviewer: it does not judge quality. When ChatGPT requests a review package, include the requested evidence itself (see `.cursor/skills/review-handoff/SKILL.md`).

| Agent | Default | Notes |
|---|---|---|
| architect-reviewer | REVIEW, `readonly: true` | Coupling, boundaries, approved design |
| code-reviewer | REVIEW, `readonly: true` | Implementation/data-flow; never `IMPLEMENT` |
| test-reviewer | REVIEW, `readonly: true` | Tests prove contracts/invariants, not only sample values |
| emulator-specialist | RESEARCH/REVIEW | Emulator backends only; `IMPLEMENT` only if parent grants it. Native PC is a separate future runtime family |
| ram-specialist | RESEARCH/REVIEW | Optional RAM/structured-state policy; never guessed VERIFIED addresses; RAM is optional |
| ai-agent-specialist | RESEARCH/REVIEW | Ollama/VLM |
| memory-specialist | RESEARCH/REVIEW | Memory ADR |
| storage-auditor | REVIEW, `readonly: true` | Disk budget |
