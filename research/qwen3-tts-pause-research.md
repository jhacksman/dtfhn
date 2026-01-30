# Qwen3-TTS Pause Research

**Date:** 2026-01-29  
**Goal:** Find reliable ways to create pauses/silence in Qwen3-TTS audio output  
**Context:** Using em-dashes (—) for breathing pauses between repeated words, but they're inconsistent

---

## TL;DR

**Qwen3-TTS has no built-in pause control mechanism.** No SSML, no break tokens, no pause parameters. Punctuation has minimal and inconsistent effects on actual silence duration. **The only reliable approach is post-processing: generate segments separately and stitch them with ffmpeg-inserted silence gaps.**

---

## 1. Official Documentation Review

### Repo & Paper
- **GitHub:** https://github.com/QwenLM/Qwen3-TTS (6k stars, released 2026-01-22)
- **Paper:** https://arxiv.org/abs/2601.15621

### What the docs say about pauses
**Nothing.** The README, paper abstract, and API docs make zero mention of:
- SSML support
- Break/pause tokens
- Silence insertion
- Prosody control beyond natural language instructions (e.g., "speak slowly")

The model supports "natural language instruction control" for emotion, tone, and speaking rate via the `instruct` parameter on CustomVoice and VoiceDesign models. However, our server uses the **Base model** (voice clone), which does NOT support instruction control.

### API Parameters (our server at 192.168.0.134:7849)
```
POST /speak
  text: string (required)
  voice: string (default: "george_carlin")
  language: string (default: "English")
  filename: string (default: "output.wav")
  timeout: int (optional)
```
No pause/silence/break parameters exist. Text is passed directly to `model.generate_voice_clone()`.

---

## 2. GitHub Issues & Community

Searched issues for "pause", "silence", "break", "SSML" — **zero relevant results**. The 3 matching issues were about macOS support (#124), a help request (#117), and fine-tuning noise (#39). No discussions about pause control either.

The model is only 8 days old (as of this research), so community knowledge is extremely limited.

---

## 3. SSML Support

**Qwen3-TTS does NOT support SSML.** When SSML tags are passed as text, the model attempts to read them aloud:

| Input | Duration | What happened |
|-------|----------|---------------|
| `Hello. <break time="1s"/> World` | 2.40s | Model spoke "break time one s" |
| `<speak>Hello. <break time="500ms"/> World.</speak>` | 3.12s | Model spoke all the tags |

This confirms the model has zero SSML awareness.

---

## 4. Empirical Punctuation Testing

### Method
Sent `"Hello [punctuation] world"` variants via the API and measured:
1. Total WAV duration
2. Silence segments (via `ffmpeg silencedetect`)

### Round 1 Results (sorted by duration)

| Punctuation | Duration | Notes |
|-------------|----------|-------|
| `Hello... world` (ellipsis) | 0.72s | Shorter than baseline! |
| `Hello world` (baseline) | 0.80s | — |
| `Hello.... world` | 0.80s | Same as baseline |
| `Hello. World` (period) | 0.80s | Same as baseline |
| `Hello; world` | 0.88s | +0.08s |
| `Hello... World` (multi-period-space) | 0.88s | +0.08s |
| `Hello ——— world` (triple em-dash) | 0.88s | +0.08s |
| `Hello. ... World` | 0.88s | +0.08s |
| `Hello: world` | 0.96s | +0.16s |
| `Hello – world` (en-dash) | 0.96s | +0.16s |
| `Hello, world` (comma) | 1.04s | +0.24s |
| `Hello...... world` | 1.04s | +0.24s |
| `Hello. — World` | 1.04s | +0.24s |
| `Hello — world` (em-dash) | 1.20s | +0.40s |
| `Hello —— world` (double em-dash) | 1.20s | +0.40s |
| `Hello.\nWorld` (newline) | 2.00s | +1.20s ⭐ |
| `Hello.\n\nWorld` (double newline) | 1.84s | +1.04s |

### Round 2 Results (reproducibility check)

| Punctuation | R1 Duration | R2 Duration | Delta |
|-------------|-------------|-------------|-------|
| `Hello world` (baseline) | 0.80s | 0.96s | +0.16s |
| `Hello — world` | 1.20s | 1.04s | -0.16s |
| `Hello.\nWorld` | 2.00s | 1.60s | -0.40s |
| `Hello. World` | 0.80s | 0.72s | -0.08s |

**Variation between runs is significant** — up to ±0.4s for identical text. This is the fundamental problem: Qwen3-TTS is non-deterministic and punctuation effects are unreliable.

### Silence Detection Analysis

Using `ffmpeg silencedetect` (-25dB threshold, 50ms minimum):

| Variant | Leading silence | Mid-sentence silence | Trailing silence |
|---------|----------------|---------------------|------------------|
| Baseline | 0.14s | none | 0.08s |
| Em-dash | 0.15s | **none** | 0.08s |
| Double em-dash | 0.08s | **none** | 0.11s |
| Comma | 0.17s | **0.08s** | 0.22s |
| Newline | **0.70s** | 0.10s | 0.09s |

**Critical finding:** Em-dashes produce NO detectable mid-sentence silence. The slightly longer total duration comes from speech pacing changes, not silence insertion. The comma actually produces a tiny mid-word gap. The newline produces massive leading silence (0.7s) as the model treats it as a paragraph break.

---

## 5. What Actually Works (Ranked)

### In-text approaches (limited usefulness)

1. **Newline (`\n`)** — Most effective in-text pause (~0.7s leading silence), but inconsistent (0.4s variation between runs) and the silence is at the START, not between words
2. **Comma (`,`)** — Tiny 0.08s mid-sentence gap
3. **Em-dash (`—`)** — Pacing change only, no actual silence. Triple em-dash was actually SHORTER than single in testing
4. **Everything else** — Noise-level differences, not meaningful

### Post-processing approach (RECOMMENDED)

**Generate segments separately and stitch with silence gaps using ffmpeg.**

```bash
# Generate two segments as separate WAV files
curl -X POST http://192.168.0.134:7849/speak -d '{"text":"Hello"}' -o seg1.wav
curl -X POST http://192.168.0.134:7849/speak -d '{"text":"World"}' -o seg2.wav

# Create silence (e.g., 1.5 seconds at 24kHz)
ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t 1.5 -f wav silence.wav

# Concatenate: seg1 + silence + seg2
ffmpeg -i seg1.wav -i silence.wav -i seg2.wav \
  -filter_complex "[0:a][1:a][2:a]concat=n=3:v=0:a=1" \
  output.wav
```

**Advantages:**
- Precise, deterministic silence duration (exactly what you specify)
- No model non-determinism
- Works regardless of model version/updates
- Can vary silence duration per segment

**Disadvantages:**
- Two API calls instead of one (but they can run in parallel on different GPUs)
- Slightly more complex pipeline
- Prosody break at segment boundaries (each segment has its own intonation arc)
- Need to trim leading/trailing silence from each segment to avoid double-silence

### Hybrid approach (BEST FOR OUR USE CASE)

For the repeated-word breathing pauses in the dtfhn project:

1. **Generate each word/segment as a separate TTS call**
2. **Trim leading/trailing silence** from each segment: `ffmpeg -af silenceremove=start_periods=1:start_silence=0.05:start_threshold=-30dB,areverse,silenceremove=start_periods=1:start_silence=0.05:start_threshold=-30dB,areverse`
3. **Insert exact silence gaps** between segments using ffmpeg concat
4. **Normalize audio levels** across segments

This gives us pixel-perfect control over pause timing with zero dependence on the model's punctuation handling.

---

## 6. Alternative: Server-Side Silence Insertion

Could modify `tts_api.py` to support a pause parameter that:
1. Splits text on a delimiter (e.g., `|||`)
2. Generates each part
3. Inserts N seconds of silence between parts
4. Returns the stitched result

This keeps the client simple (single API call) while getting deterministic pauses. Example:

```json
{
  "text": "Word one ||| Word two ||| Word three",
  "pause_seconds": 1.5
}
```

**Tradeoff:** Requires server code change, but only a small wrapper around existing functionality.

---

## 7. Key Takeaways

1. **Qwen3-TTS has zero pause control features** — no SSML, no tokens, no API params
2. **Punctuation effects are inconsistent** — ±0.4s variation between identical runs
3. **Em-dashes create NO actual silence** — just subtle pacing changes
4. **Newlines create ~0.7s leading silence** but it's unreliable and misplaced
5. **Post-processing is the only reliable approach** — ffmpeg silence insertion between separately-generated segments
6. **The model is non-deterministic** — even baseline "Hello world" varies 0.8s-0.96s between runs
7. **The Base model (voice clone) has no instruction control** — can't use `instruct` param to say "pause for 2 seconds"

---

## Appendix: Test Environment

- **TTS Server:** http://192.168.0.134:7849 (3x RTX 3090)
- **Model:** Qwen3-TTS-12Hz-1.7B-Base (voice clone mode, george_carlin voice)
- **Server code:** Custom FastAPI wrapper (`tts_api.py`) passing text directly to `generate_voice_clone()`
- **Analysis tools:** ffprobe (duration), ffmpeg silencedetect (silence analysis)
- **Sample rate:** 24kHz mono WAV output
