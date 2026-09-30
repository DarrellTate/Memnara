---
name: local-model-benchmarking
description: Repeatable local-only qualification process for Memnara models, starting with qwen3-vl:8b. Use when benchmarking, comparing, or reporting local vision/reasoning model fitness.
---

# Local Model Benchmarking

Current development model: `qwen3-vl:8b` via Ollama at `D:\Ollama\models`. Do not install or pull another model without explicit authorization.

## Inspect

- Authorized model name only.
- Local hardware notes already in project context.
- Prior benchmark records, if any, under authorized docs or `D:\Memnara-Data`.

## Workflow

1. Confirm the model under test is already authorized and present locally.
2. Measure and record:
   - disk size
   - model load time
   - RAM use
   - VRAM/GPU use when observable
   - latency
   - tokens/sec where measurable
   - screenshot/vision accuracy
   - game-state understanding
   - structured-output reliability
   - instruction following
   - action-selection quality
   - context handling
   - failure rate
3. Use local inference only. Do not send screenshots, game state, or prompts to a cloud AI provider.
4. Label each result measured, inferred, or not observable.
5. Report storage impact, including D: free space and safety-reserve risk.

## Verify

- No new model was downloaded unless authorized.
- Misty models on `E:\AI\.ollama\models` were not used or modified.
- Measurements are not fabricated.
- Architecture remains provider-replaceable.

## Do not assume

- That `qwen3-vl:8b` is the permanent production model.
- That a larger model may be pulled to "check."
- That cloud APIs may be used as a fallback.

## Expected outputs

- Benchmark table with labeled measurements.
- Suitability notes and failure cases.
- Storage impact for ChatGPT review.

## Stop

Stop after the authorized benchmark is recorded. Do not change the default model or download alternatives.
