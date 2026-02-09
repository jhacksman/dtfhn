# Qwen3-TTS API Explainer (Default + Cloned Voices)

## Overview

This API supports two kinds of voices:

1. **Default voices:** Built-in speakers from the CustomVoice model (e.g. aiden, vivian). These are not files in `voices/`.
2. **Cloned voices:** Custom profiles under `voices/<name>/` with a `prompt.pkl` built from reference audio.

**Key difference:**
- Default voices use `generate_custom_voice` and support style control via `instruct`.
- Cloned voices use `generate_voice_clone` and do **not** use `instruct`.

---

## Endpoints

1. **GET /** — Returns service status plus lists of voices.
2. **GET /voices** — Returns combined list of cloned + default voices.
3. **POST /speak** — Generates audio.

---

## Default Voices

Available (from model):
- `aiden`, `ryan`, `vivian`, `serena`, `uncle_fu`, `dylan`, `eric`, `ono_anna`, `sohee`

```bash
curl -X POST http://localhost:7849/speak \
  -H 'Content-Type: application/json' \
  -d '{
    "text":"Hello there.",
    "voice":"aiden",
    "language":"English",
    "instruct":"Calm, reassuring, low energy."
  }' --output out.wav
```

Notes:
- `instruct` is optional. If omitted, default style is used.
- Speaker names are case-insensitive.

---

## Cloned Voices

Cloned voices are any folder under `voices/` with a `prompt.pkl` (built from ref audio + transcript).

```bash
curl -X POST http://localhost:7849/speak \
  -H 'Content-Type: application/json' \
  -d '{
    "text":"Testing a cloned voice.",
    "voice":"george_carlin",
    "language":"English"
  }' --output out.wav
```

Notes:
- `instruct` is **ignored** for cloned voices.

---

## Supported Request Fields

**Required:**
- `text`
- `voice`

**Optional:**
- `language` (default: English)
- `filename` (default: output.wav)
- `timeout` (seconds, overrides TTS_TIMEOUT)
- `instruct` (style control for default voices only)
- `non_streaming_mode` (default: true)

**Generation controls:**
- `do_sample`
- `top_k`
- `top_p`
- `temperature`
- `repetition_penalty`
- `subtalker_dosample`
- `subtalker_top_k`
- `subtalker_top_p`
- `subtalker_temperature`
- `max_new_tokens`

Example with generation controls:

```bash
curl -X POST http://localhost:7849/speak \
  -H 'Content-Type: application/json' \
  -d '{
    "text":"More expressive.",
    "voice":"aiden",
    "language":"English",
    "instruct":"Excited, fast pace.",
    "temperature":0.9,
    "top_p":0.95,
    "max_new_tokens":2048
  }' --output out.wav
```

---

## Voice Resolution Rules

When you call `/speak`, the API resolves the voice in this order:

1. If `voices/<name>/prompt.pkl` exists → treated as a **cloned voice**.
2. Else, if `<name>` is a CustomVoice speaker ID → treated as a **default voice**.
3. Otherwise → 404 error.

---

## Environment Options

- `TTS_CUSTOM_VOICE_MODEL_PATH`: path to CustomVoice checkpoint.
- `TTS_CUSTOM_VOICE_ENABLED=0`: disables default voices.
- `TTS_TIMEOUT`: global timeout seconds (default 120).
