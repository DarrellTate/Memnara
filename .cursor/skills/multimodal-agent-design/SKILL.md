---
name: multimodal-agent-design
description: Memnara workflow for vision, optional RAM, structured model output, event-driven reasoning, and action safety. RAM may be absent (VISION + INPUT generic path). Fusion is M4 and must not be implemented unless authorized. Use when designing or changing perception, decision loops, schemas, or game-control actions.
---

# Multimodal Agent Design

Keep vision and RAM logically separate. RAM may be **absent**; the long-term generic path is VISION + INPUT (ADR-007). The model must never execute arbitrary host commands.

## Inspect

- Vision observation schema and RAM/state schema.
- Perception-fusion / agent-context builder.
- Action registry and output schema.
- Reasoning-trigger conditions.

## Workflow

1. Accept vision and approved RAM as separate labeled inputs. If RAM/state is not a runtime capability, proceed with visual (and later window) observations only.
2. Fuse them into one agent context that still names the source of each fact (M4+; do not implement fusion unless authorized).
3. Require structured model output (observation, reaction, emotion, goal, plan, commentary, action, or the approved schema).
4. Validate the action against a strict registry. Reject unknown actions.
5. Trigger reasoning on events (screen change, RAM change, battle/menu/dialogue transition, goal progress, timer, stuck signal), not once per video frame.
6. Include stuck-state signals in context when present.
7. Route commentary and conversation through the same identity and memory as gameplay.

## Verify

- Schema validation rejects malformed output without crashing the controller.
- Unknown actions are rejected.
- Vision and RAM remain labeled after fusion.
- No path converts model text into shell or arbitrary Python execution.

## Do not assume

- That natural-language parsing is enough to drive controls.
- That the model should be called every frame.
- That hidden RAM should be included by default.
- That RAM exists for every runtime (native PC and unknown emulator games may be vision-only).

## Expected outputs

- Structured observation and action schemas.
- Validated action registry usage.
- Event-driven loop changes only within authorized scope.

## Stop

Stop when the authorized perception/decision scope is complete and unsafe host execution is impossible through the action path.
