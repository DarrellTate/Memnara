# Milestone 3 — Vision

**Status:** COMPLETE / APPROVED  
**Model:** `qwen3-vl:8b` via local Ollama HTTP `http://127.0.0.1:11434`  
**Default image scale:** 3× nearest-neighbor (160×144 → 480×432)

M3 is observation only. The vision provider does not choose or execute gameplay actions and does not receive RAM state.

## Architecture

```text
Framebuffer (M1)
    → integer nearest-neighbor PNG (in memory)
    → OllamaVisionProvider (/api/chat, format JSON schema, think=false)
    → VisualObservation (source=VISUAL)
```

| Piece | Location |
|---|---|
| Generic provider | `src/memnara/perception/vision/base.py` |
| Ollama HTTP | `src/memnara/perception/vision/ollama.py` |
| Schema/parse | `models.py`, `parse.py`, `prompts.py` |
| Scale/PNG | `images.py` |
| Frame-change gate | `change.py` |
| Installed vs vision-capable | `discovery.py` (`/api/tags` + `/api/show` `capabilities`) |

PyBoy types stay in the emulator adapter. Title-specific RAM stays in a local GameAdapter (private). The vision prompt forbids RAM knowledge and actions.

## Ollama provider

- Endpoint must be loopback (`127.0.0.1`, `localhost`, `::1`).
- `OLLAMA_HOST=0.0.0.0:11434` (server bind) is ignored; client default remains `http://127.0.0.1:11434`.
- `MEMNARA_OLLAMA_HOST` / explicit config still rejected if remote.
- Availability: `GET /api/tags` then `POST /api/show`. Memnara-compatible vision requires `"vision"` in `capabilities`.
- `qwen3-vl:8b` on this machine: `completion`, `vision`, `tools`, `thinking` (**verified** `/api/show`).
- Timeouts and HTTP/parse failures raise; they are not turned into fake observations.
- Malformed JSON → `VisionParseError`.
- Keys such as `press_button` / `action` are dropped if the model emits them.

### Thinking-field quirk (**verified**)

Request sets `"think": false`. For `qwen3-vl:8b`, `message.content` is often empty and the JSON object is in `message.thinking`. The provider accepts that fallback and records it in `notes`. Eval counts on this evidence file were **97–140** (not the 1500-token thinking bloat from M0 text structured calls).

## Prompt / schema

`source` is **not** taken from the model. Parse always stamps `source=VISUAL`.

Scene types: `BOOT_OR_TITLE`, `OVERWORLD`, `DIALOGUE`, `MENU`, `BATTLE`, `STATUS_OR_PARTY`, `UNKNOWN`. Unknown enum values become `UNKNOWN`.

## Scaling

Integer factors 1–4, PIL `NEAREST`. Default **3×**: large enough for VLM tokens without 4× payload. Generic APIs take `Framebuffer` width/height; they do not assume 160×144.

## Frame-change trigger

`FrameChangeDetector`: first frame always observed; later frames observed when RGB changed-pixel ratio ≥ 0.015 (configurable). Identical frames are suppressed (**unit + live proven** on the detector). Callers must consult the detector **before** `observe()`; the provider itself always calls Ollama.

Known weaknesses: cursor blink, NPC animation, and dialogue text ticks can exceed the threshold; a still menu might not if START never opened.

## Scene validation (live ROM, no RAM in prompt)

The authoritative recorded run is retained in the private development archive and is not in Git. Values below match that run; they were **not** regenerated for this correction pass.

| Scene | Expected | Recorded | Quality | Latency |
|---|---|---|---|---|
| Early boot (~600 ticks) | boot logos | Reads boot-logo text; `scene_type=MENU`, `menu_visible=true`, confidence 0.98 | **PARTIALLY_CORRECT** (text/logo recognition useful; MENU classification and menu flag wrong) | ≈ 2.53 s |
| Later intro / title (~1500 ticks) | Title or intro | title or copyright-like text in description; `visible_text` empty; `scene_type=UNKNOWN`, `menu_visible=false`, confidence 0.95 | **PARTIALLY_CORRECT** (conservative `UNKNOWN` instead of `BOOT_OR_TITLE`) | ≈ 3.59 s |
| After intro A-mash | Indoor overworld | Room/furniture (monitor, plant) described; `scene_type=UNKNOWN`, confidence 0.90 | **PARTIALLY_CORRECT** (`UNKNOWN` not `OVERWORLD`) | ≈ 3.33 s |
| START press | Start menu if it opened | Still a room; `scene_type=UNKNOWN`, `menu_visible=false`, confidence 0.95 | **UNUSABLE AS MENU VALIDATION** (no proof the menu was on screen; not evidence the VLM cannot recognize menus) | ≈ 3.47 s |

Battle and party/status screens were **not** reached. Dialogue-only capture was **not** isolated. Do not treat JSON validity as visual accuracy.

Common failures: conservative `UNKNOWN` scene labels on title/room; boot **MENU** misclassification; empty `entities`; incomplete `visible_text`; START/menu scene not established.

## Performance

Recorded four-call mean **≈ 3.23 s**. First call (`first_call_coldish`) **≈ 2.53 s**. Warm calls **≈ 3.59 s**, **≈ 3.33 s**, **≈ 3.47 s**. That first call is **not** a true cold load; true cold load was **not** re-measured in M3. M0 still reports ~20 s `load_duration` on first structured call.

`eval_count` **97–140** with `think: false` (**measured** in this evidence file).

## Model compatibility

Installed Ollama models are listed via `/api/tags`. Vision fitness is **not** “any installed name”: `/api/show` `capabilities` must include `vision`. M3 does not build a desktop selector.

## Storage

Runtime vision evidence from live validation is retained in the private development archive. It is not committed. No new model pull.
