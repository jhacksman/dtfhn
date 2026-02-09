# PLAN: Resilient Episode Pipeline with LanceDB as State Machine

**Date:** 2026-02-08
**Status:** DRAFT — Awaiting Jack's approval before execution

## Problem

Today's episode had 3 partial runs across 3 directories (`2026-02-08-0947`, `-1001`, `-1009`). WAVs scattered, no way to know state without manually searching the filesystem. Pipeline runs once and gives up on failure.

## Core Insight

LanceDB already stores episodes, stories, and segments. The gap is that **the pipeline doesn't check what already exists before doing work**. Each run starts fresh, creates a new timestamped directory, and hopes for the best.

The fix: make the pipeline **query LanceDB first** at every step, and only do work that's missing.

---

## 1. Schema Changes

### 1.1 New Table: `pipeline_state`

This is the key addition. One row per episode date, tracking the state of each pipeline phase.

```python
PIPELINE_STATE_SCHEMA = pa.schema([
    pa.field("episode_date", pa.string()),          # PK: "2026-02-08" (DATE ONLY, no HHMM)
    pa.field("phase", pa.string()),                 # Current phase (see below)
    pa.field("stories_fetched", pa.int32()),         # Number of stories in DB
    pa.field("scripts_generated", pa.int32()),       # Number of scripts completed
    pa.field("interstitials_generated", pa.int32()), # Number of interstitials completed
    pa.field("intro_generated", pa.bool_()),         # Intro text exists
    pa.field("outro_generated", pa.bool_()),         # Outro text exists
    pa.field("segments_rendered", pa.int32()),        # Segment MP3s completed
    pa.field("segments_total", pa.int32()),           # Total segments expected
    pa.field("segments_failed", pa.string()),         # JSON list of failed segment names
    pa.field("episode_assembled", pa.bool_()),        # Final MP3 stitched
    pa.field("episode_uploaded", pa.bool_()),          # R2 upload done
    pa.field("feed_updated", pa.bool_()),              # feed_episodes.json updated
    pa.field("site_deployed", pa.bool_()),             # Cloudflare Pages triggered
    pa.field("notified", pa.bool_()),                  # Telegram sent
    pa.field("started_at", pa.string()),               # ISO timestamp of first run
    pa.field("updated_at", pa.string()),               # ISO timestamp of last update
    pa.field("error_log", pa.string()),                # Last error message (if any)
    pa.field("schema_version", pa.int32()),
])
```

**Phases** (string enum):
- `fetch` — fetching stories
- `scripts` — generating scripts + interstitials + intro/outro
- `tts` — rendering TTS segments
- `assembly` — stitching MP3 + metadata
- `upload` — R2 upload + feed + deploy
- `complete` — everything done

### 1.2 Existing Tables: No Schema Changes

- `episodes` — unchanged (stores final MP3 + transcript)
- `stories` — unchanged (stores articles + scripts)
- `segments` — unchanged (stores segment metadata + timing)

The existing tables already contain the data we need. The new `pipeline_state` table is just the **progress tracker**.

### 1.3 Episode Date Format Change: DATE ONLY

**Critical change:** Episode dates become `YYYY-MM-DD` (no more `-HHMM` suffix).

Why: The `-HHMM` suffix is what causes directory sprawl. Multiple runs on the same day create different dates. With date-only keys:
- One canonical directory per date: `data/episodes/2026-02-08/`
- One set of DB records per date
- Pipeline always finds prior work for today

**Migration:** Existing episodes with `-HHMM` suffixes remain as-is. New episodes use date-only. The `format_date_for_tts()` function already strips the `-HHMM` for spoken dates.

---

## 2. Pipeline Flow (Step by Step with Resume Logic)

### New entry point: `scripts/run_episode.py` (Python, replaces `run_episode.sh`)

Why Python instead of bash: Resume logic requires DB queries, conditional branching, and structured error handling that's painful in bash. The shell script becomes a thin wrapper if needed for cron.

### Phase 1: FETCH

```
Input:  episode_date (YYYY-MM-DD)
Check:  get_stories_by_date(episode_date) → existing stories
Skip if: len(existing) >= 10

Action: fetch_stories(limit=10) → store_stories_batch()
Update: pipeline_state.stories_fetched = count
```

### Phase 2: SCRIPTS

```
Check:  For each story, check if story.script is non-empty
Skip if: All 10 scripts + 9 interstitials + intro + outro exist on disk

Action (per story, sequential):
  - If story.script is empty → generate_script() → update_story_script()
  - Write script text to episode_dir/{segment_name}.txt

Action (interstitials, sequential):
  - For each pair (i, i+1), check if interstitial file exists
  - If missing → generate_interstitial() → write to disk

Action (intro/outro):
  - Check if 00_-_intro.txt exists → if not, generate_intro()
  - Check if 20_-_outro.txt exists → if not, generate_outro()

Update: pipeline_state.scripts_generated, intro_generated, outro_generated
Write:  manifest.json, stories.json, transcript.txt, transcript.vtt, chapters.json
```

**Key detail:** Script generation checks BOTH the DB (for scripts) and disk (for text files). The DB is the source of truth for script content; disk files are derived artifacts. If a disk file is missing but the DB has the script, just re-write the file.

### Phase 3: TTS

```
Check:  For each segment in manifest, check if segments/{name}.mp3 exists and is valid
Skip if: All segment MP3s exist and validate

Action:
  - Build list of missing segments
  - Fire all missing segments to TTS in parallel (max_workers=6)
  - On completion, transcode WAV → MP3, validate, delete WAV
  - Track render_time_seconds per segment (store in pipeline_state or log)

Retry: Failed segments get up to 3 retries with exponential backoff
Update: pipeline_state.segments_rendered, segments_failed
```

This is essentially what `generate_episode_audio.py` already does with `find_existing_segment_mp3s()`. The change is making it **the default behavior** rather than requiring `--force`.

### Phase 4: ASSEMBLY

```
Check:  Does DTFHN-{date}.mp3 exist with valid duration?
Skip if: Final MP3 exists AND all segment MP3s are older than it

Action:
  - Stitch segment MP3s → final MP3
  - Embed ID3 chapters + metadata
  - Store in LanceDB (store_episode)
  - Store segment metadata (store_segments_batch)
  - Generate chapters.json with actual timing

Update: pipeline_state.episode_assembled = True
```

### Phase 5: UPLOAD

```
Check:  pipeline_state.episode_uploaded?
Skip if: Already uploaded (and verified accessible)

Action:
  - upload_to_r2.py (MP3 + VTT + chapters)
  - Verify HTTP 200 from CDN URL
  - Update feed_episodes.json
  - Regenerate feed.xml
  - Git push dailytechfeedsite (trigger Cloudflare Pages)
  - Send Telegram notification

Update: pipeline_state for each sub-step
```

Each sub-step of upload is independently tracked so a failure in Telegram doesn't re-upload the MP3.

---

## 3. Status Command

### `scripts/episode_status.py [date]`

```
$ python3 scripts/episode_status.py 2026-02-08

Episode: 2026-02-08
Phase:   tts (in progress)
Started: 2026-02-08T05:00:12
Updated: 2026-02-08T05:23:45

  ✅ Fetch:     10/10 stories
  ✅ Scripts:   10/10 scripts, 9/9 interstitials, intro ✓, outro ✓
  🔄 TTS:       14/21 segments (67%)
     Failed:    03_-_script_02_p01 (runaway, retry 2/3)
     Remaining: ~12 min (7 segments × ~100s avg)
  ⬜ Assembly:  pending
  ⬜ Upload:    pending

Episode dir: data/episodes/2026-02-08/
```

Without a date argument, shows today. Also supports `--all` to list all episodes with their phase.

**Data sources:**
- `pipeline_state` table for phase/flags
- `stories` table for script counts
- `segments/` directory for MP3 file counts
- TTS server `/status` for active rendering info

---

## 4. Migration Path

### What Changes

| File | Change |
|------|--------|
| `scripts/run_episode.sh` | **Replaced** by `scripts/run_episode.py` (thin bash wrapper for cron compatibility) |
| `scripts/generate_episode_audio.py` | **Mostly unchanged** — already has resume logic. Remove standalone entry point; called from run_episode.py |
| `src/storage.py` | **Add** `pipeline_state` table CRUD (get/update/create). ~50 lines |
| `src/pipeline.py` | **Modify** `run_episode_pipeline()` to check existing scripts before generating. ~30 lines changed |
| `scripts/episode_status.py` | **New** — ~100 lines |
| `scripts/run_episode.py` | **New** — main orchestrator, ~200 lines |

### What Stays the Same

- `src/tts.py` — no changes
- `src/audio.py` — no changes  
- `src/embeddings.py` — no changes
- `src/hn.py` — no changes
- `src/generator.py` — no changes
- `src/chapters.py` — no changes
- `src/metadata.py` — no changes
- `src/feed.py` — no changes
- `scripts/upload_to_r2.py` — no changes (called as subprocess)
- `scripts/scrape_and_load.py` — no changes (standalone tool)

### Migration Steps

1. Add `pipeline_state` table to `storage.py`
2. Write `scripts/run_episode.py` with resume logic
3. Write `scripts/episode_status.py`
4. Modify `run_episode_pipeline()` to skip existing scripts
5. Update `run_episode.sh` to call `run_episode.py` instead of inline Python
6. Test with a manual run: `python3 scripts/run_episode.py 2026-02-09`
7. Kill partway through TTS, re-run, verify resume
8. Update cron job

### Backward Compatibility

- Old episodes with `-HHMM` dates are untouched in DB
- New episodes use date-only format
- `format_date_for_tts()` already handles both formats
- No data migration needed — old data stays, new data uses new format

---

## 5. Design Decisions

### Why `pipeline_state` table instead of just checking existing data?

You could theoretically infer state from existing data (stories in DB → fetch done, scripts non-empty → scripts done, etc.). But:
1. **Explicit is better than implicit.** A single row tells you exactly where things stand.
2. **Error tracking.** Knowing that TTS failed on segment X with error Y is valuable.
3. **Timing data.** When did each phase start/finish? How long did TTS take?
4. **Atomicity.** Update one row vs. querying multiple tables to infer state.

We use BOTH: `pipeline_state` for the progress tracker, and the actual data tables for the resume checks. Belt and suspenders.

### Why not a finite state machine with transitions?

Overkill. The phases are linear (fetch → scripts → tts → assembly → upload). No branching, no parallel phases. A simple "what phase are we in + what's done" is sufficient.

### Why Python replaces bash for the orchestrator?

The bash script is already 150+ lines with inline Python calls. The resume logic requires DB queries before each step. Doing that in bash means more `python3 -c "..."` blocks, which is worse than just writing Python. The bash wrapper for cron becomes 3 lines:

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")/.."
exec python3 scripts/run_episode.py "$@"
```

---

## 6. Open Questions for Jack

1. **Date-only format:** Removing `-HHMM` means one episode per day max. Is that acceptable? (If you want multiple per day, we keep `-HHMM` but add a "latest for date" lookup.)

2. **Re-scrape tolerance:** If a story was `title_only` on first fetch but the site comes back, should the pipeline re-scrape on resume? Or only scrape once?

3. **TTS voice change mid-episode:** If you switch `CHARACTER` between runs, should the pipeline re-render all segments or only missing ones? (Current plan: render only missing, which could mix voices.)

4. **Old directory cleanup:** Should the pipeline automatically clean up multiple `-HHMM` directories for the same date, or leave that manual?
