# PLAN.md - Carlin Podcast Pipeline

## Status: ✅ Core Implementation Complete

**Last Updated:** 2026-01-27

---

## Target
- **Duration:** 20-25 minutes
- **Words:** 4000-5000 (~200 WPM)
- **Stories:** 10 from Hacker News

---

## Implementation Status

### ✅ Done

| Component | Status | Module |
|-----------|--------|--------|
| HN API client | ✅ | `src/hn.py` |
| Article fetching + gzip archiving | ✅ | `src/hn.py`, `src/storage.py` |
| LanceDB vector storage | ✅ | `src/storage.py` |
| Embeddings (BGE-large, MPS) | ✅ | `src/embeddings.py` |
| Chained script generation | ✅ | `src/generator.py` |
| Word count tracking | ✅ | `src/generator.py` |
| Interstitial generation | ✅ | `src/generator.py` |
| Episode orchestrator | ✅ | `src/pipeline.py` |

### 🔲 TODO

| Component | Notes |
|-----------|-------|
| Parallel TTS | Quato's job (3x 3090 GPUs) |
| Audio stitching | ffmpeg concat in `test/full_stack_test.py` |
| MP3 delivery | Signal integration tested in `test/` |

---

## Pipeline (Implemented)

### 1. Fetch (src/hn.py)
- Get top N stories from HN API
- Fetch article URL content + gzip archive
- Fetch comments
- Returns `Story` dataclass with `raw_html`, `fetch_status`

### 2. Store (src/storage.py)
- Embed article text + comments → LanceDB
- Store in `articles` table with:
  - `archive_gzip` (compressed raw HTML)
  - `fetch_status` ("full", "full_js", "title_only", "failed")

### 3. Generate Scripts (src/generator.py - Chained)
```
Script 1: article_1 → script_1
Script 2: article_2 + script_1 → script_2
Script 3: article_3 + script_2 → script_3
...
```
- Each generation sees previous script (prevents repetition)
- Track running word count toward 4000-5000 target
- Adjust length guidance: "be briefer" if over budget, "expand" if under

### 4. Store Scripts
- Embed each script → LanceDB `scripts` table
- Enables future retrieval (year-end compilations, topic searches)

### 5. Generate Interstitials (src/generator.py)
- Two adjacent scripts at a time
- 1-2 sentence Carlin-style transition

### 6. Assemble (src/pipeline.py)
```
intro + script_1 + interstitial_1_2 + script_2 + ... + script_N + outro
```
Save as `data/episodes/YYYY-MM-DD/episode.txt`

### 7. TTS (TODO - quato)
- Send all segments to quato API (3 GPUs process in parallel)
- Don't wait sequentially — fire all requests, collect results

### 8. Stitch & Transcode (in test/full_stack_test.py)
- ffmpeg concat all WAVs → single WAV
- WAV → MP3

---

## Usage

```bash
# Quick test (3 stories)
cd dtfhn
source .venv/bin/activate
python -m src.pipeline --test

# Full episode (10 stories, today's date)
python -m src.pipeline
```

---

## Output Structure

```
data/episodes/YYYY-MM-DD/
├── stories.json          # Raw HN data
├── script_1.txt          # Individual scripts
├── script_2.txt
├── ...
├── interstitial_1_2.txt  # Transitions
├── ...
├── episode.txt           # Full collated script
├── manifest.json         # Episode metadata
└── (TTS outputs go here)
```

---

## Character Reference
See `CARLIN.md` for voice guidelines:
- Pro-tech, pro-AI, accelerationist
- Mock luddites, gatekeepers, closed systems
- Never mock the technology or people using it
