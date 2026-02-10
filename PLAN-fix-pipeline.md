# PLAN: Fix DTFHN Pipeline — 2026-02-10

## Problems Identified

### Bug 1: Voice hardcoded to `george_carlin`
- `generate_episode_audio.py` lines 425 and 580 hardcode `"voice": "george_carlin"`
- `CHARACTER_CONFIG` in `generator.py` correctly maps `jack` → `noel`
- The audio generator never reads from config

### Bug 2: Double story headers with wrong numbers
- LLM generates its own "Story seven. Title." (hallucinated number)
- `pipeline.py:512` prepends correct "Story one. Title." via `generate_story_header()`
- Result: two headers per story, one with wrong number
- The prompt (`generator.py:600+`) says "Write ONLY the script text" but never says "don't write a header"

### Bug 3: `[pause]` not splitting into separate TTS segments
- `em_dash_to_pause()` converts em-dashes to `[pause]` — good
- `split_into_paragraphs()` splits on `\n\n` only
- Inline `[pause]` stays as literal text, TTS reads "pause" aloud or garbles it
- Should split on `[pause]` and insert silence between resulting clips

### Bug 4: TTS pipeline gives up too fast
- 3 retries with 2s/4s/8s backoff
- TTS server cold start takes ~2 min, GPU hangs can last longer
- Pipeline dies, episode doesn't ship

## Fixes

### Fix 1: Voice from config
**File:** `scripts/generate_episode_audio.py`
**Change:** Replace hardcoded `"voice": "george_carlin"` (lines 425, 580) with voice read from `get_character_config(character)["tts_voice"]`
**How:** Import `get_character_config` from `src.generator`, pass character through, use `config["tts_voice"]`

### Fix 2: Strip LLM story headers
**File:** `src/generator.py`
**Changes:**
1. Add to prompt (after "Write ONLY the script text"): `"Do NOT write a story number or header line. The header is added automatically by the pipeline."`
2. Add post-processing in `sanitize_llm_output()`: strip lines matching `^Story \w+\..*` at the start of output (catch any the LLM still generates)

### Fix 3: Split on `[pause]`
**File:** `scripts/generate_episode_audio.py` → `load_segments()` / `split_into_paragraphs()`
**Change:** After paragraph splitting, further split each paragraph on `[pause]`. Each `[pause]` boundary becomes a separate TTS segment with silence gap inserted during assembly.
**Detail:**
- `[pause]` on its own line (standalone) already works as paragraph break — verify this
- Inline `[pause]` within text: split into two segments, strip `[pause]` from both
- Silence gap between pause-split segments: same duration as paragraph gaps (currently 1s)

### Fix 4: Patient TTS submission
**File:** `scripts/generate_episode_audio.py`
**Change:** Replace parallel blast + 3 retries with:
- Submit segments sequentially in batches of 3 (one per GPU)
- `timeout=0` on each request (wait indefinitely)
- On HTTP error: wait 60s, hit `/restart`, wait 120s for reload, retry
- No max retry limit — runs until complete or manually killed
- Skip existing WAV files (already implemented)
- Log progress clearly: "Segment 14/51: story_04_p02 — rendering..."

## Verification
- Generate a test episode (dry run or use today's scripts)
- Confirm: single correct story header per story
- Confirm: voice is noel (not george_carlin)  
- Confirm: `[pause]` markers produce silence gaps, not spoken text
- Confirm: TTS resilience by checking it survives a `/restart` mid-run

## Files Modified
- `scripts/generate_episode_audio.py` (fixes 1, 3, 4)
- `src/generator.py` (fix 2)
