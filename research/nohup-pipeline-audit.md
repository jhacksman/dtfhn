# Nohup Pipeline Audit — 2025-07-18

Audit of `scripts/run_episode.sh` and the full pipeline for nohup/cron execution with `YYYY-MM-DD-HHMM` date format.

## Files Audited

- `scripts/run_episode.sh`
- `src/pipeline.py`
- `src/generator.py`
- `src/storage.py`
- `src/chapters.py`
- `src/transcript.py`
- `src/metadata.py`
- `scripts/generate_episode_audio.py`

---

## Issues Found

### ISSUE 1 — CRITICAL: `src/metadata.py` line 50 — `strptime` breaks on HHMM dates

**File:** `src/metadata.py`
**Line:** 50
**Code:** `dt = datetime.strptime(episode_date, "%Y-%m-%d")`

**What breaks:** When `episode_date` is `"2026-01-29-0500"` (the new default format), `strptime("%Y-%m-%d")` raises `ValueError: unconverted data remains: -0500` because it expects exactly `YYYY-MM-DD` (10 chars) but gets 15 chars.

**Impact:** The TTS script (`generate_episode_audio.py` line 573) calls `embed_id3_metadata(str(episode_mp3), episode_date)` near the end of the pipeline. This means the entire TTS generation (20-40 minutes of GPU time) completes successfully, but then the script crashes at the metadata embedding step. The MP3 exists but has no ID3 tags, and the script exits with error code 1.

**Fix:** Apply the same pattern as `generator.py:format_date_for_tts()` — strip the `-HHMM` suffix before parsing:
```python
date_part = episode_date[:10] if len(episode_date) > 10 else episode_date
dt = datetime.strptime(date_part, "%Y-%m-%d")
```

**Secondary effect on same line:** The `episode_number` derived from `dt.timetuple().tm_yday` (day-of-year) would be the same for multiple episodes on the same day. This is a design choice, not a bug — but worth noting that the HHMM portion is not reflected in the track number.

---

### ISSUE 2 — LOW: `scripts/run_episode.sh` line 16 — Shell variable interpolation in inline Python

**File:** `scripts/run_episode.sh`
**Line:** 16
**Code:**
```bash
python3 -u -c "
from src.pipeline import run_episode_pipeline
import json
manifest = run_episode_pipeline(episode_date='${EPISODE_DATE}', ...)
"
```

**What breaks:** The shell variable `${EPISODE_DATE}` is interpolated directly into a Python string literal delimited by single quotes. If `EPISODE_DATE` ever contained a single quote character, the Python syntax would break. Since the value comes from `date +%Y-%m-%d-%H%M` (which only produces digits and hyphens), this is safe in practice.

**Risk:** Minimal — the date format is safe. However, it's fragile by construction.

**Fix:** Pass the date as a command-line argument instead of interpolating into inline Python:
```bash
python3 -u -c "
import sys
from src.pipeline import run_episode_pipeline
import json
manifest = run_episode_pipeline(episode_date=sys.argv[1], num_stories=10, word_target=4000, verbose=True)
print(json.dumps(manifest, indent=2))
" "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"
```

---

### ISSUE 3 — INFO: Stale docstrings throughout `src/storage.py`

**File:** `src/storage.py`
**Lines:** 28, 177, 207, 224, 271, 297, 344, etc.
**Code:** Docstrings say `episode_date: Episode date string "YYYY-MM-DD"` in numerous functions.

**What breaks:** Nothing. All storage functions treat `episode_date` as an opaque string key — no parsing anywhere. LanceDB stores it as `pa.string()` and queries use exact string equality. The HHMM format works perfectly.

**Fix (cosmetic):** Update docstrings to `"YYYY-MM-DD or YYYY-MM-DD-HHMM"` for accuracy.

---

## Files Verified Safe

### `src/generator.py` — ✅ SAFE
- `format_date_for_tts()` (line 347-357): Explicitly handles the HHMM suffix with `date_part = date_str[:10] if len(date_str) > 10 else date_str`. This is the correct pattern.
- No other date parsing. Episode date is passed through as an opaque string.

### `src/pipeline.py` — ✅ SAFE
- Default date generation (line 201): `datetime.now().strftime("%Y-%m-%d-%H%M")` — correctly produces the new format.
- `format_date_for_tts()` call (line 254): Wrapped in try/except for test dates. Safe.
- All other episode_date usage is opaque string passing to storage/generator/chapters.

### `src/storage.py` — ✅ SAFE (functionally)
- `make_story_id()`: Concatenates `f"{episode_date}-{position:02d}"` — works with any string.
- `make_segment_id()`: Same pattern — `f"{episode_date}-intro"`, etc.
- All queries use string equality (`f"episode_date = '{episode_date}'"`) — opaque, works fine.
- No `strptime` or date parsing anywhere.

### `src/chapters.py` — ✅ SAFE
- `load_stories_for_episode()`: Uses `data/episodes/{episode_date}/stories.json` path — opaque string, works with any date format.
- `segments_to_chapters()`: No date parsing. Reads segment dicts, not date strings.
- `generate_chapters_json()`: Accepts `episode_title` as pre-formatted string. No parsing.
- `embed_chapters()`: Same — no date awareness.

### `src/transcript.py` — ✅ SAFE
- Zero references to `episode_date` or any date parsing.
- Purely operates on segment dicts with text and timing.

### `scripts/generate_episode_audio.py` — ✅ SAFE (except for the `embed_id3_metadata` call, see Issue 1)
- `load_segments()`: Reads manifest.json from `data/episodes/{episode_date}/` — opaque path. Safe.
- `build_segment_metadata()`: Passes episode_date through to storage. No parsing.
- All directory lookups use `Path(...) / episode_date` — works with any string.
- The `--force` flag is correctly passed in `run_episode.sh`, bypassing the interactive queue check that would fail under nohup (stdin is /dev/null).

---

## Cron/Nohup Integration Analysis

### Will `nohup bash scripts/run_episode.sh` work from a Clawdbot cron session?

**Yes, with caveats:**

1. **PATH:** The cron job is executed by Clawdbot's agent via the `exec` tool, which inherits the agent's shell environment. `python3`, `ffmpeg`, and `claude` should all be in PATH. If the cron uses a fresh shell, `/usr/local/bin` may need to be in PATH for `claude`.

2. **Working directory:** `run_episode.sh` uses `cd "$(dirname "$0")/.."` to set CWD to the project root. This is robust — works regardless of where the script is invoked from.

3. **Python module resolution:** The inline `python3 -c "from src.pipeline import ..."` works because Python's `-c` flag adds CWD to `sys.path`. Since the script already `cd`'d to the project root, `src/` is importable.

4. **nohup stdin:** Under nohup, stdin is redirected to `/dev/null`. The TTS script's interactive prompt (`sys.stdin.isatty()`) returns False, but this is handled by the `--force` flag in `run_episode.sh`.

5. **`set -euo pipefail`:** Correct. Pipeline failures propagate. If the text pipeline fails, TTS won't run.

6. **Logging:** The script writes to both stdout (captured by nohup's `>` redirect) and a per-episode log via `tee`. Both capture the same output — redundant but harmless.

7. **Date auto-generation:** `date +%Y-%m-%d-%H%M` produces the correct format. No issues.

---

## Summary

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | **CRITICAL** | `src/metadata.py:50` | `strptime("%Y-%m-%d")` crashes on `YYYY-MM-DD-HHMM` dates |
| 2 | LOW | `scripts/run_episode.sh:16` | Shell variable interpolation in inline Python (safe in practice) |
| 3 | INFO | `src/storage.py` (many lines) | Docstrings say "YYYY-MM-DD" but code handles any string |

**Blocking issue count: 1** — Issue 1 must be fixed before the pipeline can run end-to-end with the new date format. The pipeline will complete TTS (~30 min of GPU time) then crash at metadata embedding.
