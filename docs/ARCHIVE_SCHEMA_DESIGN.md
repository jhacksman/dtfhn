# Archive Schema Design (v2.1)

## Summary

**3-table schema** with MP3 binary stored directly in LanceDB. WAV files are ephemeral working files, deleted after MP3 is created. Segments table tracks metadata for each audio segment.

## Key Decisions

1. **Store MP3 in LanceDB**: Final episode MP3 as binary in `episodes` table
2. **No WAV archival**: WAV files are temporary, delete after stitching to MP3
3. **Segments table for metadata**: Track timing, text, and TTS info for each segment (no audio stored)
4. **Dual vectors on stories**: Article text + script text embeddings

## Schema

### Table: `episodes`

One row per episode day. Contains the final MP3 binary and full transcript.

| Field | Type | Description |
|-------|------|-------------|
| episode_date | string | Primary key, "YYYY-MM-DD" |
| mp3_binary | binary | Final episode MP3 |
| transcript | string | Full episode text |
| duration_seconds | float | Total audio length |
| word_count | int | Total words spoken |
| story_count | int | Number of stories (default 10) |
| generated_at | string | ISO timestamp |
| schema_version | int | For migrations |
| vector | float32[] | Embedding of transcript |

### Table: `stories`

10 rows per episode. Article content, archive, and generated script.

| Field | Type | Description |
|-------|------|-------------|
| id | string | Primary key, "YYYY-MM-DD-NN" (e.g., "2025-01-27-01") |
| episode_date | string | Links to episodes |
| position | int | Story order 1-10 |
| hn_id | string | HN story ID |
| title | string | Article title |
| url | string | Original article URL |
| author | string | HN submitter |
| score | int | HN points |
| archive_gzip | binary | Gzipped raw HTML |
| fetch_status | string | "full", "full_js", "title_only", "failed" |
| article_text | string | Extracted article text |
| comments_json | string | JSON array of comment dicts |
| script | string | Generated Carlin script |
| script_word_count | int | Words in script |
| interstitial_next | string | Transition to next story (null for #10) |
| article_vector | float32[] | Embedding of article text |
| script_vector | float32[] | Embedding of script |
| schema_version | int | For migrations |

### Table: `segments`

21 rows per episode. Audio segment metadata (text, timing, TTS info). No audio stored — WAVs are ephemeral.

| Field | Type | Description |
|-------|------|-------------|
| id | string | Primary key, format varies by type (see below) |
| episode_date | string | Links to episodes |
| segment_type | string | "intro", "script", "interstitial", "outro" |
| position | int | Ordering: 0=intro, 1-10=scripts, 11-19=interstitials, 99=outro |
| story_position | int | Which story (1-10), null for intro/outro |
| text | string | The text that was spoken |
| word_count | int | Words in this segment |
| duration_seconds | float | Length of audio |
| start_offset_seconds | float | Start position in final MP3 |
| tts_model | string | TTS model used (e.g., "f5-tts") |
| voice | string | Voice used (e.g., "george_carlin") |
| generated_at | string | ISO timestamp |
| schema_version | int | For migrations |

**Segment ID formats:**
- Intro: `2026-01-27-intro`
- Scripts: `2026-01-27-script-01` through `2026-01-27-script-10`
- Interstitials: `2026-01-27-inter-01-02` (between story 1 and 2)
- Outro: `2026-01-27-outro`

**Episode structure (21 segments):**
1. intro (position 0)
2. script-01 through script-10 (positions 1-10)
3. inter-01-02 through inter-09-10 (positions 11-19, between stories)
4. outro (position 99)

## Why Store MP3 in LanceDB?

- **Simplicity**: One backup target (LanceDB folder)
- **Atomic operations**: Episode is complete when row exists
- **Size is reasonable**: ~10-15MB per episode, ~5GB/year
- **No path management**: No broken links, no orphan files

## Why WAVs are Ephemeral

- WAV segments are 10-30MB each, 21 per episode = 420MB/episode
- That's 150GB/year of redundant data (MP3 has everything)
- Regeneration is possible from stored scripts + TTS
- WAVs are intermediate build artifacts, not archival content

## Storage Estimates

| Component | Size | Per Year (365 eps) |
|-----------|------|-------------------|
| Episodes table | ~10MB/row (MP3 + transcript + vector) | ~4GB |
| Stories table | ~100KB/row (content + 2 vectors + archive) × 10 | ~350MB |
| Segments table | ~2KB/row (text + metadata) × 21 | ~15MB |
| **Total** | | **~4.5GB** |

## Migration from v1

The old schema had:
- `articles` table → merged into `stories`
- `scripts` table → merged into `stories`

Migration maps:
- `articles.source_id` → `stories.hn_id` (strip "hn-" prefix)
- `articles.content` → `stories.article_text`
- `articles.source_url` → `stories.url`
- `scripts.script_text` → `stories.script`
- New `stories.id` = `{episode_date}-{story_number:02d}`

## Query Patterns

```python
# Get episode for playback
episode = get_episode("2025-01-27")
mp3_bytes = episode["mp3_binary"]

# Search episodes by topic
results = search_episodes("cryptocurrency regulation", top_k=5)

# Search stories by article content
results = search_stories("AI safety", vector_column="article_vector")

# Search by Carlin rant topic
results = search_stories("billionaires", vector_column="script_vector")

# Get all stories for an episode
stories = get_stories_by_date("2025-01-27")

# Get all segments for an episode (ordered by position)
segments = get_episode_segments("2025-01-27")

# Get a specific segment
intro = get_segment("2025-01-27-intro")
script_3 = get_segment("2025-01-27-script-03")
interstitial = get_segment("2025-01-27-inter-05-06")

# Store segments batch (typically after TTS generation)
store_segments_batch([
    {"episode_date": "2025-01-27", "segment_type": "intro", "position": 0,
     "text": "Welcome to...", "duration_seconds": 45.2},
    {"episode_date": "2025-01-27", "segment_type": "script", "position": 1,
     "story_position": 1, "text": "So here's the thing...", "duration_seconds": 180.5},
    # ... etc
])
```
