# ADR-003 — Model runtime

**Status:** ACCEPTED  
**Date:** 2026-09-30

## Choice

Local **Ollama HTTP** as the first `ModelProvider`. Development model **`qwen3-vl:8b`**. No cloud providers in v1 runtime.

Memnara is designed primarily as an **HTTP client** of the already-running local Ollama server at:

`http://127.0.0.1:11434`

The Memnara application process must **not** set, override, or depend on the shell-level `OLLAMA_MODELS` variable merely to make HTTP requests.

## Model location and process ownership

- Model-location configuration belongs to the **Ollama SERVER process**, not the Memnara client.
- The currently running desktop Ollama server already exposes `qwen3-vl:8b`.
- Memnara should **query the server** for model availability (e.g. tags/show).
- Memnara must **not** modify the Misty environment/configuration on `E:\`.
- Memnara should **fail clearly** if its required model is unavailable from the active server.
- Managing a **separate Memnara-owned Ollama server/process** is **DEFERRED** and would require a future explicit architecture decision, including separate lifecycle, port, and storage handling.

Do not use client-side `OLLAMA_MODELS=D:\Ollama\models` overrides to “make HTTP work.”

## Alternatives

- llama.cpp server, LM Studio, direct Hugging Face — extra stacks; Ollama is already installed.
- Cloud APIs — forbidden for runtime.

## Evidence

Ollama 0.34.1 present; model listed on the local server; `/api/chat` vision + `format` JSON **measured** in `docs/research/ollama-and-qwen.md`.

## Tradeoffs

- Thinking-token bloat on structured calls must be configured down (request options), not by moving model files.
- If the user’s Ollama service is pointed at Misty storage, Memnara still must not edit that configuration; it only consumes HTTP and fails if `qwen3-vl:8b` is missing.

## Consequences

Replaceable provider interface. Do not pull larger models without authorization. Do not change Ollama settings as part of Memnara runtime.
