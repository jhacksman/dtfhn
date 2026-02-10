# PLAN: Fix DTFHN Pipeline — 2026-02-10

## Root Cause Analysis

### The Script is Broken — 5 Bugs

**Bug 1: LLM generates its own story headers with hallucinated numbers**
- Pipeline prepends correct header via `generate_story_header(i+1, title)` in `pipeline.py:509-512`
- LLM prompt (`generator.py:600+`) never says "don't write a header"
- LLM generates "Story seven. Title." independently — hallucinated number
- The +6 offset (story 1→"seven", story 2→"eight") suggests HN ranking position leaking
  from comment text or the LLM's own confusion about article ordering
- Result: TWO headers per story, one correct, one wrong

**Bug 2: Interstitials reference wrong story numbers**
- `generate_interstitial()` receives `current_story_num` and `next_story_num` (correct: 1-based)
- But the LLM ignores them or hallucinates its own — interstitial after story 1 says "Story seven"
- Need to check: is the interstitial prompt actually passing the story numbers?
- Even if it does, the LLM needs explicit instruction: "Use these exact numbers"

**Bug 3: Voice hardcoded to `george_carlin`**
- `generate_episode_audio.py` lines 425 and 580: `"voice": "george_carlin"`
- CHARACTER_CONFIG correctly maps `jack` → `noel`
- Audio generator never reads from config

**Bug 4: `[pause]` not splitting into TTS segments**
- `em_dash_to_pause()` converts `—` to `[pause]` in generator output — good
- `split_into_paragraphs()` splits on `\n\n` only
- Standalone `[pause]` on its own line = already a paragraph break (works by accident)
- Inline `[pause]` within a paragraph = passed as literal text to TTS (broken)
- TTS either reads "pause" aloud or garbles it

**Bug 5: TTS pipeline too fragile**
- 3 retries with 2s/4s/8s backoff
- Dies on cold start (~2 min) or GPU hangs
- Pipeline exits instead of persisting

## Fixes

### Fix 1: Kill LLM story headers
**File:** `src/generator.py` → `generate_script()` prompt
**Change:** Add explicit instruction: "Do NOT write a story number, header, or title line. The header is added automatically. Start directly with the content."
**Also:** Add post-processing regex in `sanitize_llm_output()` to strip any line matching `^Story \w+[\.\:].+` at the start of output

### Fix 2: Fix interstitial story numbers
**File:** `src/generator.py` → `generate_interstitial()` 
**Check:** Verify `current_story_num` and `next_story_num` are passed to the LLM prompt
**Change:** Make the prompt explicit: "You are transitioning from story {N} to story {N+1}. If you reference a story number, use EXACTLY these numbers."
**Also:** Strip any hallucinated story headers from interstitial output too

### Fix 3: Voice from config
**File:** `scripts/generate_episode_audio.py`
**Change:** Replace `"voice": "george_carlin"` on lines 425, 580 with voice read from `get_character_config()["tts_voice"]`
**How:** Import `get_character_config` from `src.generator`, thread character name through

### Fix 4: Split on `[pause]`
**File:** `scripts/generate_episode_audio.py` → `split_into_paragraphs()` or `load_segments()`
**Change:** After paragraph splitting, further split each chunk on `[pause]`
- Strip `[pause]` from text before sending to TTS
- Each `[pause]` boundary = new TTS segment with silence gap (same as paragraph gap)
- Inline `[pause]` like `"extensions [pause] each one"` becomes two segments: `"extensions"` and `"each one"` with silence between

### Fix 5: Patient TTS
**File:** `scripts/generate_episode_audio.py`
**Change:** Rewrite TTS submission:
- Submit 3 segments at a time (one per GPU)
- `timeout=0` per request (wait indefinitely)
- On HTTP error: wait 60s, hit `/restart`, wait 120s for reload, retry
- No max retry limit — runs until complete or killed
- Skip existing WAVs (already works)
- Clear progress logging: "Segment 14/51: story_04_p02 — rendering..."

## Verification
After fixes, re-generate today's episode text (dry run):
1. Confirm: single correct header per story ("Story one." not "Story seven.")
2. Confirm: interstitials reference correct story numbers
3. Confirm: no `[pause]` literal text in any TTS segment
4. Confirm: voice is `noel` in TTS requests
5. Test TTS resilience: submit one segment, verify it completes

## Files Modified
- `src/generator.py` (fixes 1, 2)
- `scripts/generate_episode_audio.py` (fixes 3, 4, 5)

## Notes
- stories.json has no `position` field — `s["position"]` returns None at pipeline.py:378
  This is benign for the script generator (doesn't use it) but should be fixed for data integrity
- The LLM's "+6" offset is likely from HN ranking context leaking through comment text
