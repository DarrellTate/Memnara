# Ollama integration and Qwen3-VL 8B qualification

**No additional models were pulled. Misty store was not modified.**

## How Memnara should talk to Ollama

**Choice (architecture only):** local HTTP API at `http://127.0.0.1:11434` (`/api/chat`, later `/api/embed` if an embedding model is authorized).

**Sources:** https://docs.ollama.com/api/chat , https://docs.ollama.com/capabilities/vision , https://docs.ollama.com/capabilities/structured-outputs

A Python SDK (`ollama` package) is optional later; Milestone 0 does not install it. The `ModelProvider` interface must not import SDK types.

Conceptual interface (not implemented):

```text
class ModelProvider:
    complete_text(messages, schema=None, timeout=...) -> StructuredResult
    complete_vision(messages, images, schema=None, timeout=...) -> StructuredResult
    cancel()
```

Required behaviors: timeouts, retries with cap, cancellation on conversation/takeover, no cloud fallback, configurable model name (`qwen3-vl:8b` now).

Memnara is an HTTP client of the already-running local Ollama server at `http://127.0.0.1:11434`. The Memnara application does **not** set, override, or depend on `OLLAMA_MODELS` for normal HTTP-client operation. Model storage belongs to the Ollama **server** process. Memnara should query the active server for required-model availability and fail clearly when the model is unavailable. A separate Memnara-owned Ollama server process is **deferred** and requires a future ADR.

**Machine observation (verified this session, not a client design):** this shell had `OLLAMA_MODELS=E:\AI\.ollama\models` (Misty). Memnara must not modify the user's Misty environment or the E: model store. The active Ollama server currently exposes `qwen3-vl:8b` (6.1 GB). Qualification used `127.0.0.1:11434` and did not change user/system environment files.

## Limited local qualification (`qwen3-vl:8b`)

Hardware context: Ryzen 7 7800X3D, ~63 GB RAM, RX 7700 XT (VRAM **inferred** 12 GB; Windows AdapterRAM unreliable).

Fixture: a synthetic 160×144 PNG (not a game screenshot). The qualification artifact is retained in the private development archive.

### Test A — structured JSON (text only)

| Metric | Value | Label |
|---|---|---|
| Wall time | 54097 ms | **measured** (includes cold load) |
| `load_duration` | 19.56 s | **measured** |
| `eval_count` | 1551 | **measured** (suspected thinking tokens) |
| `eval_duration` | 34.16 s | **measured** |
| `prompt_eval_count` | 49 | **measured** |
| Output | valid JSON: observation, action `press_up`, confidence 0.8 | **measured** |

Schema `format` object was honored. Token count is **too high** for per-event control if “thinking” is left on. Follow-up: pass Ollama think-disable if the model supports it (not tested in this run).

### Test B — vision on synthetic fixture (model already warm)

| Metric | Value | Label |
|---|---|---|
| Wall time | 6119 ms | **measured** |
| `load_duration` | 1.6 ms | **measured** (already loaded) |
| `eval_count` | 193 | **measured** |
| `eval_duration` | 4.27 s | **measured** |
| `prompt_eval_count` | 1097 | **measured** (image tokens) |
| Description | green background, yellow circle upper-right, orange/brown bar | **measured**; matches fixture |

### Answers to Milestone 0 questions

1. Accept images locally? **Yes** (synthetic PNG via `/api/chat` `images` base64). Real GB screenshots **pending** (no ROM).
2. Describe simple visuals? **Yes on this synthetic fixture.** Simple **game** states: **pending** (no ROM screenshot).
3. Structured output? **Yes** with `format` JSON schema; validate in app anyway.
4. Viable for routine decisions? **Conditional.** Warm vision ~6 s is usable for event-driven (not per-frame). Cold start ~20 s. Structured action call spent ~34 s generating 1551 tokens — **not viable** as-is for frequent actions. Must constrain thinking/max tokens before M5.
5. Latency: see tables.
6. Resources: disk ~6.1 GB model; RAM/VRAM during infer **not instrumented** (would need GPU tools). **Not measured.**
7. Limits: thinking bloat; no game-screen test; AMD GPU path for Ollama **not measured** (CPU vs GPU unknown this run).

**Do not treat this as a production bake-off.** Do not pull a larger model without authorization.
