# Qwen3-TTS Pause Control Research

**Date:** 2026-01-30
**Status:** No native pause parameter exists

## Summary

Qwen3-TTS has **no documented pause parameter, no SSML support, and no special text markup** for inserting pauses between words or phrases. The official repo, technical report (arXiv 2601.15621), GitHub issues, and discussions are all silent on this topic.

## What Exists

### Natural Language Instruction Field

Only works with **1.7B CustomVoice/VoiceDesign models** (not 0.6B Base):

- Vague pacing: `"slow pace"`, `"very fast speaking rate"`, `"do not rush"` — these work
- Precise timing: `"finish in 5 seconds"` — completely ignored ([Issue #23](https://github.com/QwenLM/Qwen3-TTS/issues/23))
- The instruction is prepended to input sequences during generation

### Punctuation Effects (Undocumented, Empirical)

| Technique | Expected Effect | Reliability |
|---|---|---|
| Comma `,` | Short pause | Moderate |
| Period `.` | Longer pause (end-of-sentence) | Moderate |
| Ellipsis `...` | Extended/hesitant pause | Model-dependent |
| Em-dash `—` | Medium pause | Model-dependent |
| Extra spaces | Minor pause | Unreliable |
| Stacked punctuation (`... —`) | Unknown | Untested |

**None of these are documented by Qwen.** The model uses "contextual understanding" for prosody, meaning it does whatever it infers from the text semantics.

### Third-Party Wrapper Solutions

These are **not native Qwen3-TTS features** — they inject silence at the audio level:

- **[TTS-Audio-Suite](https://github.com/diodiogod/TTS-Audio-Suite):** Supports `[pause:1s]` tags in dialogue mode. Inserts silence audio between segments.
- **[ComfyUI-Qwen-TTS](https://github.com/flybirdxx/ComfyUI-Qwen-TTS):** `pause_seconds` parameter between dialogue segments. Audio-level silence injection.

## Current DTFHN Approach

`prepare_text_for_tts()` in `src/tts.py` wraps all segment text with em-dashes (`—`) before sending to the API. This creates some breathing room at segment boundaries. Between-segment silence is handled by `stitch_wavs()` with configurable `silence_duration` (default 1s).

## Options for Improvement

1. **Punctuation experiments** — Empirically test comma, ellipsis, em-dash, and combinations to measure actual pause duration in generated audio. No documentation exists, so this requires A/B testing.

2. **Instruction field** — If quato server exposes the instruction parameter (CustomVoice/VoiceDesign models only), try instructions like `"slow pace, with natural pauses between phrases"`.

3. **Sub-segment splitting** — Split text at sentence boundaries, generate separate WAVs, stitch with controlled silence gaps. Trades naturalness (cross-sentence prosody) for timing control.

4. **Post-processing** — Detect silence regions in generated audio and stretch them. More complex but preserves natural prosody.

## Sources

- [Qwen3-TTS GitHub](https://github.com/QwenLM/Qwen3-TTS)
- [Qwen3-TTS Technical Report](https://arxiv.org/html/2601.15621v1)
- [Qwen3-TTS Blog](https://qwen.ai/blog?id=qwen3tts-0115)
- [Issue #23: Time frame control](https://github.com/QwenLM/Qwen3-TTS/issues/23)
- [TTS-Audio-Suite](https://github.com/diodiogod/TTS-Audio-Suite)
- [ComfyUI-Qwen-TTS](https://github.com/flybirdxx/ComfyUI-Qwen-TTS)
- [HN Discussion](https://news.ycombinator.com/item?id=46719229)
- [HuggingFace Model Card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base)
