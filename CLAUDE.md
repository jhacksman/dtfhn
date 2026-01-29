# Daily Tech Feed, Hacker News Edition (dtfhn)

Tech news podcast. Transforms HN articles + comments into 10-story episodes with distinctive voice and perspective.

## Architecture

See `ARCHITECTURE.md` for the full pipeline design.

## Key Conventions

### File Structure
```
dtfhn/
├── CLAUDE.md           # This file
├── ARCHITECTURE.md     # Pipeline design
├── src/                # Implementation
├── data/               # Vector DB, cached articles
├── episodes/           # Generated content
└── test/               # TTS tests, samples
```

### TTS Module (`src/tts.py`)

Interfaces with quato TTS server (F5-TTS with George Carlin voice).

```python
from src import text_to_speech, text_to_speech_parallel, check_tts_status

# Single segment
text_to_speech("Hello world", Path("output.wav"))

# Parallel generation (recommended for episodes)
segments = [("intro", "Welcome..."), ("story1", "First story...")]
wav_files = text_to_speech_parallel(segments, output_dir)

# Check server status
status = check_tts_status()  # Returns GPU queue info
```

**Key insight:** Use `text_to_speech_parallel()` for episodes. Fires all requests at once — quato's 3 GPUs process from queues in parallel.

### Audio Module (`src/audio.py`)

WAV concatenation and MP3 transcoding using ffmpeg.

```python
from src import stitch_wavs, transcode_to_mp3, get_audio_duration, cleanup_wav_files

# Stitch segments into single WAV (with 1s silence gaps by default)
stitch_wavs(wav_files, Path("episode.wav"))

# Custom silence duration (e.g., 0.5 seconds)
stitch_wavs(wav_files, Path("episode.wav"), silence_duration=0.5)

# Disable silence gaps (direct concatenation)
stitch_wavs(wav_files, Path("episode.wav"), silence_duration=None)

# Transcode to MP3
transcode_to_mp3(Path("episode.wav"), Path("episode.mp3"), bitrate="128k")

# Get duration for metadata
duration = get_audio_duration(Path("episode.mp3"))

# Clean up temp WAVs (~400MB savings)
cleanup_wav_files(wav_files)
```

**Silence gaps:** By default, 1 second of silence is inserted between segments for natural breathing room. The `DEFAULT_SILENCE_DURATION` constant in `audio.py` controls this. Pass `silence_duration=None` or `0` to disable.

### TTS API (Reference)
- **URL:** http://192.168.0.134:7849
- **Voice:** george_carlin (F5-TTS trained on Carlin specials)
- **GPUs:** 3 (parallel processing)
- **Speed:** ~1.7x realtime per GPU
- **Dispatch:** Least-queued (each request routes to GPU with shortest queue, not round-robin)

**Endpoints:**

**`POST /speak`** — Generate audio (text → WAV)
- Body: `{"text": "...", "voice": "george_carlin", "language": "English", "filename": "output.wav", "timeout": 0}`
  - `text` (required): Text to speak
  - `voice` (optional): Default `george_carlin`
  - `language` (optional): Default `English`
  - `filename` (optional): Default `output.wav`
  - `timeout` (optional): Per-request timeout in seconds. **ALWAYS USE 0** to disable timeout (critical for long segments). Overrides `TTS_TIMEOUT` env var.
- Returns: WAV audio bytes (`audio/wav`)
- Response header: `X-Job-Id` — integer job ID for tracking
- Status codes: `200` OK, `504` timed out, `409` cancelled

**`GET /`** — Basic health check
```json
{"status": "ok", "gpus": 3, "voices": ["george_carlin"]}
```

**`GET /status`** — Queue status per GPU
```json
{
  "gpus": [
    {"gpu": 0, "active": "— Text preview...", "queued": 5},
    {"gpu": 1, "active": null, "queued": 3},
    {"gpu": 2, "active": "— Another text...", "queued": 4}
  ],
  "total_active": 2,
  "total_queued": 12,
  "completed": 47
}
```

**`GET /voices`** — List available voice profiles
```json
["george_carlin"]
```

**`GET /jobs`** — List all tracked jobs with status
- Returns: `{"jobs": [{ job_id, gpu_id, text_preview, status, submitted_at }]}`
- `status`: `queued` | `active` | `done` | `failed` | `timed_out` | `cancelled`

**`DELETE /jobs/{job_id}`** — Cancel a specific job
- Only cancels queued (not yet running) jobs
- `job_id`: integer (from `X-Job-Id` header)

**`DELETE /gpu/{gpu_id}/queue`** — Flush all queued jobs for a GPU
- Cancels all queued (not yet running) jobs for the specified GPU
- `gpu_id`: integer (0, 1, or 2)

**CLIENT PATTERN:** Fire all segments at once, no timeout. Server handles queuing and least-queued dispatch across 3 GPUs.

### Vector Storage (LanceDB) — Schema v2.1

Located at `data/vectors/`. Uses BAAI/bge-large-en-v1.5 embeddings (1024 dim).

**Tables:**
- `episodes` — episode_date, mp3_binary, transcript, duration, word_count, vector
- `stories` — id, episode_date, position, hn_id, title, url, article_text, script, article_vector, script_vector
- `segments` — id, episode_date, segment_type, position, text, duration_seconds, start_offset_seconds, tts_model, voice

**Key design decisions:**
- MP3 stored as binary in LanceDB (not file paths) — simplifies backup, atomic operations
- WAV files are ephemeral — delete after MP3 is created
- Segments store metadata only (text, timing, TTS info) — not audio
- Dual vectors on stories: article content + script text (search by either)
- Old `articles` + `scripts` tables merged into `stories`

**Usage:**
```python
from src.storage import (
    # Episodes
    store_episode, get_episode, get_episode_mp3, search_episodes, list_episodes,
    # Stories
    store_story, store_stories_batch, get_story, get_stories_by_date, search_stories,
    get_existing_hn_ids, update_story_script,
    # Segments
    store_segment, store_segments_batch, get_segment, get_episode_segments,
    # Migration
    migrate_from_v1,
)

# Store a story
store_story(
    episode_date="2025-01-28",
    position=1,
    hn_id="12345",
    title="Some Tech Article",
    url="https://...",
    article_text="Full article text...",
    comments=[{"author": "user", "text": "comment"}],
    script="You know what's funny about this...",
)

# Search stories by article content
results = search_stories("AI machine learning", vector_column="article_vector")

# Search by Carlin rant topic
results = search_stories("billionaires", vector_column="script_vector")

# Store episode with MP3
store_episode(
    episode_date="2025-01-28",
    mp3_binary=mp3_bytes,
    transcript="Full episode text...",
    duration_seconds=1234.5,
)

# Retrieve MP3 for playback
mp3_bytes = get_episode_mp3("2025-01-28")

# Store segment metadata after TTS generation
store_segment(
    episode_date="2025-01-28",
    segment_type="script",  # "intro", "script", "interstitial", "outro"
    position=1,             # 0=intro, 1-10=scripts, 11-19=interstitials, 99=outro
    text="You know what kills me about AI?...",
    duration_seconds=120.5,
    start_offset_seconds=15.5,
    story_position=1,       # for script/interstitial only
)

# Get all segments for an episode (ordered by position)
segments = get_episode_segments("2025-01-28")  # Returns 21 segments

# Generate chapter markers from segments
for seg in segments:
    print(f"{seg['start_offset_seconds']}: {seg['segment_type']} {seg.get('story_position', '')}")
```

**Device auto-detection:** MPS (Apple Silicon) → CUDA → CPU. Model loads once as singleton.

### Segment File Naming Convention (Zero-Padded Sequential)

All segment files use zero-padded sequential numbering so filesystem sorting matches episode order:

```
00_-_intro.txt / .wav
01_-_script_01.txt / .wav
02_-_interstitial_01_02.txt / .wav
03_-_script_02.txt / .wav
...
19_-_script_10.txt / .wav
20_-_outro.txt / .wav
```

Pattern: `{sequence_number}_-_{segment_name}.ext`

**Rules:**
- Sequence prefix: always two digits (00-20)
- Script numbers: always two digits (01-10)
- Interstitial numbers: always two digits (01_02 through 09_10)
- Total: 21 segments (1 intro + 10 scripts + 9 interstitials + 1 outro)

**Helper functions** in `src/pipeline.py`:
- `segment_name(kind, script_num, next_num)` — builds the name with `_-_` separator
- `parse_segment_name(name)` — parses back to `{kind, script_num, next_num}` (handles both old `script_1` and new `01_-_script_01` formats)

Both `src/pipeline.py` and `scripts/generate_episode_audio.py` use these for all name construction and parsing. **Never hardcode segment names** — always use these helpers.

**Note:** Episodes generated before the `_-_` separator change (e.g., 2026-01-27, 2026-01-28) have old-style names in their manifests (`script_1`, `interstitial_1_2`). `parse_segment_name()` handles both formats.

### Branding Convention

The podcast name is **"Daily Tech Feed"**. With source qualifier: **"Daily Tech Feed, Hacker News Edition"** or **"Daily Tech Feed for Hacker News"**.

- **Spoken intro line:** "You're listening to D T F H N for {date}."
- **Spoken outro line:** "This has been your daily tech feed for Hacker News for {date}."
- **Outro sign-off:** "Now go [dynamic uplifting imperative]. We'll see you back here tomorrow."
- **Episode titles:** "Daily Tech Feed - YYYY-MM-DD"
- **Chapter JSON / ID3 tags:** "Daily Tech Feed"
- **Never use "DTF" or "DTF:HN"** in code, prompts, docs, or metadata — that's visual/logo branding only.

#### Static vs Dynamic Elements (Intro/Outro)

Every episode has hardcoded static lines and dynamic creative lines:

**Intro STATIC:** "You're listening to D T F H N for {date}." (line 1 — always first)
**Intro DYNAMIC:** Host descriptor (wide open — absurd, vulgar, surreal, not just "dead" synonyms), HN riff, mood setter, launch line

**Outro STATIC:** "This has been your daily tech feed for Hacker News for {date}." (line 2) + "We'll see you back here tomorrow." (always last)
**Outro DYNAMIC:** Parting thought, credit delivery style, "Now go..." imperative (always optimistic/uplifting)

**Hardening:** `generate_intro()` and `generate_outro()` enforce static parts as safety nets — prepend/append if LLM omits them. Also strips markdown artifacts and warns on word count overages (>20% over limit).

### Critical Insight: Context Boundaries

Each pipeline stage receives ONLY what it needs:
- Summaries get: article chunks + comment chunks
- Carlin scripts get: summaries only
- Interstitials get: adjacent final scripts only

**Never** pass raw articles to later stages. Token budget depends on this.

### Lessons Learned

1. **Use `claude` CLI, not Anthropic API directly.** The system uses `claude -p "prompt"` which handles auth via the installed CLI. Don't hardcode API keys or try to use the anthropic library directly. Mirror the pattern from `hn-podcast/scripts/generate.py`.

2. **Look at existing projects first.** Before writing new code, check `/Users/jackhacksman/clawd/hn-podcast/` for established patterns. It has working LLM calls, TTS integration, and config patterns already solved.

3. **NEVER spawn sub-agents for TTS generation.** Sub-agents have a 10-minute timeout. TTS for a full episode takes 20-40 minutes. Use `nohup` instead:
   ```bash
   cd ~/clawd/dtfhn && nohup python3 scripts/generate_episode_audio.py YYYY-MM-DD --force > tts.log 2>&1 &
   ```
   The process runs independently. Check `tts.log` or `curl http://192.168.0.134:7849/status` for progress. MP3 appears when done. Do NOT babysit, poll, or monitor — kick it off and walk away. This lesson was learned the hard way when a spawn timed out at 10 minutes with only 2 of 21 WAVs completed.

4. **Claude CLI subprocess calls need `stdin=subprocess.DEVNULL`.** Without it, the CLI hangs waiting for interactive input when auth fails or prompts occur. Always add this to prevent silent hangs.

5. **Chained generation prevents repetition.** Pass the previous script text to the LLM prompt when generating sequential content. This allows variety guidance ("don't repeat phrases or structures") and produces more natural-sounding episodes.

6. **Dynamic word budgeting works.** Track running word count and adjust per-story budget based on remaining target. Clamp to reasonable bounds (250-600 words) to avoid absurdly short or long segments.

7. **Gzip HTML for archival efficiency.** Storing raw HTML compressed achieves 10-20x compression ratios. Use `pa.binary()` in LanceDB schema for bytes storage. Decompress only when explicitly requested.

8. **Separate fetch_status from content.** Track how content was obtained ("full", "full_js", "title_only", "failed") separately from the content itself. Useful for debugging and filtering low-quality articles.

9. **Test pipeline runs quickly.** Use `--test` with fewer stories (3) for rapid iteration. The full pipeline with 10 stories + embeddings + LLM calls takes several minutes.

10. **Multi-tier fallback chain for scraping.** Article scraping uses a simple fallback chain - let each tier try and fail naturally:
    1. newspaper3k (fast, static HTML)
    2. Playwright (headless browser for JS)
    3. Wayback Machine (archived versions)
    4. Alternative URLs from HN post text
    5. title_only (graceful degradation)
    
    Status codes track which tier succeeded: `"full"`, `"full_js"`, `"full_archive"`, `"full_alt"`, `"title_only"`. Don't pre-filter domains - let failures happen and recover gracefully.

11. **Some sites can't be scraped automatically.** Even with multiple fallback tiers, some sites are impenetrable (aggressive bot detection, paywalls, not yet archived). The chain gracefully degrades to "title_only" when all tiers fail.

12. **Scrape failures can be transient.** Sites like openai.com may fail during one scrape but work fine later. Don't add domain skip lists - the fallback chain handles failures gracefully. If a story shows "title_only", it may work on re-scrape. Causes include: rate limiting, temporary bot detection, network issues, or site maintenance.

13. **Store MP3 binary directly in LanceDB.** Binary storage works well for ~10-15MB files. Simplifies backup (single folder), ensures atomic operations (episode exists = complete), avoids path management headaches. For ~4.5GB/year, this is acceptable.

14. **WAV files are build artifacts, not archival content.** Delete after stitching to MP3. They're regenerable from stored scripts + TTS, and storing 420MB/episode (vs 10MB MP3) wastes 150GB/year on redundant data.

15. **LanceDB `table_names()` is deprecated.** Use `list_tables()` instead. The warning doesn't break anything but good to fix.

16. **Exclude large binaries from search/list results.** When returning episode lists or search results, pop the `mp3_binary` field to avoid transferring megabytes of data you don't need. Only include it when explicitly requested.

17. **Schema migrations in LanceDB require re-adding rows.** LanceDB doesn't support true UPDATE operations. For migrations, read old data, transform it, and add new rows to new tables. Keep old tables as backup until verified.

18. **Segments table stores metadata, not audio.** Each episode has 21 segments (1 intro, 10 scripts, 9 interstitials, 1 outro). Store text, timing, and TTS info for analytics/debugging/regeneration. Position field enables ordering: 0=intro, 1-10=scripts, 11-19=interstitials, 99=outro. Segment IDs encode structure: `{date}-intro`, `{date}-script-01`, `{date}-inter-01-02`, `{date}-outro`.

19. **ID3 chapters use mutagen library, not ffmpeg.** ffmpeg's chapter support only works for MP4/MKV, not MP3. For MP3 chapters, use `mutagen` with CHAP frames + CTOC (table of contents). Chapters need times in milliseconds, not seconds.

20. **Chapters skip interstitials.** Interstitials are transitions, not chapter markers. Only create chapters for intro, story scripts, and outro (~12 chapters per episode). Interstitials are included in the full transcript (VTT) but not in chapter navigation.

21. **WebVTT with `<v Speaker>` tags.** Use `<v George Carlin>` for speaker identification. Native browser support via `<track>` element. Apple Podcasts uses VTT for ingest.

22. **JSON chapters follow Podcast 2.0 spec.** Version "1.2.0", include HN URLs in chapter entries. `toc: false` can hide silent chapters (useful for interstitials if you want artwork changes without cluttering chapter list).

23. **Two-phase chapter embedding.** Pipeline generates VTT + JSON with estimated timing (based on word count ~165 WPM). After TTS generates actual audio, `finalize_episode_audio()` embeds ID3 chapters with real timing from the segments table.

24. **Estimated vs actual timing.** Before TTS, estimate duration from word count (165 WPM for Carlin's fast delivery). After TTS, segments table has actual duration_seconds and start_offset_seconds from audio files.

25. **ThreadPoolExecutor for parallel HTTP requests.** Use `concurrent.futures.ThreadPoolExecutor` to fire all TTS requests at once. The server queues them internally — sending 21 requests immediately lets 3 GPUs work in parallel with full queues. Sequential requests waste 2/3 of available GPU capacity.

26. **Silence between segments uses anullsrc.** Generate silence WAVs with ffmpeg's `anullsrc` lavfi source (24kHz mono to match TTS output). Interleave with content WAVs in the concat file list. Much simpler than complex filter graphs or manual sample manipulation.

27. **Em-dashes create TTS breathing pauses.** Qwen3-TTS interprets em-dashes (—) as brief pauses. `prepare_text_for_tts()` wraps all segment text with em-dashes before sending to the API. This creates natural breathing room at segment start/end without modifying stored scripts. Single point of change in `src/tts.py`.

28. **Robust TTS pipeline prevents duplicate submissions.** When a sub-agent dies or restarts, it can submit duplicate requests to the TTS server while the original requests are still queued. Use `text_to_speech_parallel_robust()` which: (a) checks queue status before submitting, (b) skips existing valid WAV files, (c) retries only failed segments, (d) recovers from race conditions where files were created after timeout.

29. **Lock files prevent concurrent TTS runs.** Use `fcntl.flock()` with `LOCK_EX | LOCK_NB` to get exclusive lock on a `.tts_generation.lock` file. If lock fails, another process is running. Always wrap in try/finally to release lock even on error. The lock file also serves as a signal to other agents that generation is in progress.

30. **Pre-flight checks save GPU time.** Before starting TTS generation: (a) check if queue is empty (orphaned jobs?), (b) scan for existing WAV files (incomplete run?). In interactive mode, prompt user to continue. In automated mode (sub-agent), abort on conflicts. Better to fail fast than waste 30 minutes of GPU time on duplicates.

31. **Dynamic intro/outro generation replaces static templates.** The pipeline now generates intro and outro text dynamically using Claude with full episode context (all scripts + interstitials). This means intro/outro can reference actual story themes. Pipeline went from 6 to 7 steps. The `INTRO_TEMPLATE` and `OUTRO_TEMPLATE` constants were removed from `pipeline.py`. The `templates/` directory files are no longer used for intro/outro (kept for reference). `generate_episode_audio.py` no longer needs `TEMPLATES_DIR` — it reads `00_-_intro.txt` and `20_-_outro.txt` directly from the episode directory. The `format_date_for_tts()` function moved from the audio script to `src/generator.py` as the canonical location.

32. **TTS server refactoring (deadlock fix) is client-transparent.** Server switched from shared thread pool + threading.Lock to per-GPU ThreadPoolExecutor(max_workers=1), fixed error-path double-decrement, switched status tracking to asyncio.Lock, and moved to lifespan handler for model loading. Client code (`src/tts.py`, `scripts/generate_episode_audio.py`) is fully compatible — API contract unchanged. Audited all `/speak` and `/status` interactions; no field names, request formats, or response formats changed. The fix actually *improves* `/status` accuracy, making our stall detection more reliable.

33. **ID3 metadata is separate from chapters.** `src/metadata.py` handles basic ID3 tags (title, artist, album, genre, date, track). `src/chapters.py` handles CHAP/CTOC frames. Both use mutagen and both preserve each other's tags (they load existing ID3 before adding). Call `embed_chapters()` first, then `embed_id3_metadata()` — order doesn't actually matter since both load-then-save, but this is the pipeline convention.

34. **Chapter titles come from stories.json, not segments.** Segments don't carry story titles or HN IDs — they only have `story_position`. To get real chapter titles and HN URLs, pass `stories` (from `stories.json` or `load_stories_for_episode()`) to `segments_to_chapters()`, `embed_chapters()`, and `generate_chapters_json()`. All three accept an optional `stories` parameter. Without it, chapters fall back to "Story N" generic titles.

35. **Open-source litmus test in script generation.** The `generate_script()` prompt includes an explicit "OPEN SOURCE LITMUS TEST" section that forces the LLM to evaluate whether a covered project is open source or proprietary, and adjust the Carlin take accordingly. Proprietary projects MUST be called out — no purely positive takes on closed-source products. This was added after ShapedQL (2026-01-29) got a glowing review with zero mention of being a closed-source cloud service, despite CARLIN.md explicitly listing "proprietary lock-in" as a target. The fix is in the prompt, not the fetcher — the generator detects signals (no repo, pricing page, cloud-only) from the article text it already receives.

---

## Quick Reference

```bash
# TTS test
curl -X POST http://192.168.0.134:7849/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Test", "voice": "george_carlin"}' \
  --output test.wav
```
