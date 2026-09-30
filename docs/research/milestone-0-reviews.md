# Milestone 0 specialist reviews

Reviewers did **not** edit. Primary agent applied only in-scope documentation consistency fixes afterward.

| Specialist | Mode | Outcome |
|---|---|---|
| [architect-reviewer](171a7910-cbdd-4516-86af-75655741481d) | REVIEW | PyBoy-shaped core vocabulary; M1 spec lookalike. Fixes applied in ARCHITECTURE, ROADMAP, M1 spec. |
| [storage-auditor](fda66aa9-0416-4e09-9904-5e471d99215c) | REVIEW | v1 with caps does not threaten 10–15 GB reserve; threats = extra LLMs, Misty-on-D:, unbounded captures. |
| [test-reviewer](8f4653e2-16c7-41dd-b4be-0081db6a0702) | REVIEW | Qualification not fabricated; Q2 over-claimed game states — wording fixed. n=1, no raw transcripts. |
| [emulator-specialist](fc7d4e1a-25b8-49ee-a7e3-7840610cbf51) | RESEARCH/REVIEW | PyBoy justified; PyPI 2.7.1 yanked for a GB dialogue/window bug — pin carefully at M1. LGPL-3.0. |
| [ram-specialist](50c52c70-62da-403d-95f5-efa7a6216568) | RESEARCH/REVIEW | Fair-RAM OK as policy; finer battle/event allowlist deferred to ChatGPT. Community hashes cited as unverified vs user dump. |
| [ai-agent-specialist](5699a642-e0af-4bcb-9c65-7b15c504c5a2) | RESEARCH/REVIEW | Thinking-token latency is M5 blocker; `think: false` untested. |
| [memory-specialist](245237f4-0487-4652-9c37-b163a1c18d46) | RESEARCH/REVIEW | SQLite v1 OK; scope/tag/compression policy tightened in ARCHITECTURE. |

Material disagreements left for ChatGPT (not silently decided): battle HP-bar vs exact HP; event-flag whitelist; whether M5 hard-requires `think: false`; PyBoy version pin vs 2.7.1 yank.
