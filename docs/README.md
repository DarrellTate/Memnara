# Documentation

Tracked engineering and project knowledge lives under `/docs`. It is **not** runtime application data (`D:\Memnara-Data`) and is **not** model storage (`D:\Ollama\models`).

```text
tracked in source repository
≠ shipped with final application distribution
```

Git tracks these files so architecture, ADRs, milestone writeups, and research stay reviewable. Packaging a user-facing Memnara application is future work; tracking docs here does not mean they ship inside the installed app.

## Tree

```text
docs/
├── README.md                 this file
├── adr/                      ADRs (ADR-001–ADR-008 accepted)
├── architecture/             extra architecture notes (root ARCHITECTURE.md stays at repo root)
├── milestones/               milestone-specific implementation writeups
├── games/                    reserved; title packs are not in public Git
└── research/                 Milestone 0 research
```

Root project-control files stay at the repository root:

```text
README.md
ARCHITECTURE.md
ROADMAP.md
CURRENT_STATE.md
DECISIONS.md
PROJECT.md
CHANGELOG.md
AGENTS.md
```
