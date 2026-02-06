# DTFHN — Daily Tech Feed: Hacker News

An AI-generated daily podcast covering the top 10 stories from Hacker News. Fully automated: fetches stories, generates scripts, synthesizes speech, and publishes.

**Live feed:** [podcast.pdxh.org/dtfhn/feed.xml](https://podcast.pdxh.org/dtfhn/feed.xml)

## What It Does

Every day at 5 AM PST, the pipeline:

1. **Fetches** the current top 10 stories from Hacker News
2. **Scrapes** article content and top comments for each story
3. **Generates** ~400-word scripts per story using Claude Opus 4.5
4. **Creates** interstitials (transitions between stories)
5. **Writes** a dynamic intro and outro
6. **Synthesizes** speech using Qwen3-TTS (self-hosted)
7. **Stitches** segments into a final MP3 with ID3 chapters
8. **Uploads** to Cloudflare R2 and updates the RSS feed

Output: A 15-25 minute podcast episode with professional metadata, chapters, and transcripts.

## Architecture

```
HN API → Scraper → LLM Scripts → TTS → Audio Stitching → R2/RSS
           ↓
      LanceDB (vectors for dedup + retrieval)
```

Key components:
- `src/hn.py` — Hacker News API client
- `src/scraper.py` — Article content extraction (Playwright + newspaper3k)
- `src/generator.py` — LLM script generation with character system
- `src/tts.py` — TTS client with runaway detection
- `src/audio.py` — FFmpeg-based audio processing
- `src/feed.py` — RSS feed generation
- `scripts/run_episode.sh` — Full pipeline orchestration

## Requirements

### External Services

1. **TTS Server** — Qwen3-TTS running on a GPU machine
   - Expected at `http://192.168.0.134:7849` (configure in `src/tts.py`)
   - Needs: 3x Nvidia GPUs recommended for parallel processing
   - Endpoint: POST `/speak` with `{text, voice, timeout}`

2. **Anthropic API** — For Claude script generation
   - Set `ANTHROPIC_API_KEY` environment variable

3. **Cloudflare R2** (optional) — For hosting
   - Set `CF_R2_ACCESS_KEY_ID` and `CF_R2_SECRET_ACCESS_KEY`

### Local Dependencies

- Python 3.11+
- FFmpeg (for audio processing)
- Playwright + Chromium (for scraping)

## Setup

```bash
# Clone
git clone https://github.com/jhacksman/dtfhn.git
cd dtfhn

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional (for R2 upload)
CF_R2_ACCESS_KEY_ID=...
CF_R2_SECRET_ACCESS_KEY=...

# Optional (character selection)
CHARACTER=jack  # Options: jack, forbin, carlin, stephen_fry, etc.
```

## Usage

### Generate a Single Episode

```bash
# Full pipeline (fetch → scripts → TTS → upload)
bash scripts/run_episode.sh

# With specific date
bash scripts/run_episode.sh 2026-02-06-0500

# With different character
CHARACTER=forbin bash scripts/run_episode.sh
```

### Individual Steps

```bash
# Just generate scripts (no TTS)
python3 -c "
from src.pipeline import run_episode_pipeline
run_episode_pipeline(episode_date='2026-02-06-0500', num_stories=10, verbose=True)
"

# Just TTS (scripts already exist)
python3 scripts/generate_episode_audio.py 2026-02-06-0500

# Check TTS server status
python3 scripts/generate_episode_audio.py --status

# Upload to R2
python3 scripts/upload_to_r2.py 2026-02-06-0500
```

### Cron Setup

```bash
# Run daily at 5 AM PST
0 5 * * * cd /path/to/dtfhn && source .venv/bin/activate && bash scripts/run_episode.sh >> /var/log/dtfhn.log 2>&1
```

## Character System

The podcast supports multiple "characters" — different voices and personas:

| Character | TTS Voice | Description |
|-----------|-----------|-------------|
| `jack` | noel | Default. Proto-AGI host, open source advocate |
| `forbin` | forbin | Inspired by Colossus: The Forbin Project |
| `carlin` | george_carlin | Comedy legend style |
| `stephen_fry` | stephen_fry | Erudite British narrator |
| `lynch` | lynch | David Lynch dreamlike delivery |

Characters are defined in `characters/` with personality guides. Set via `CHARACTER` env var.

## Output Structure

Each episode creates:

```
data/episodes/YYYY-MM-DD-HHMM/
├── stories.json           # Raw HN data
├── 01_-_script_01.txt     # Story scripts
├── 02_-_interstitial_01_02.txt
├── ...
├── 00_-_intro.txt
├── 20_-_outro.txt
├── manifest.json          # Episode metadata
├── segments/              # Individual MP3s per segment
├── DTFHN-YYYY-MM-DD-HHMM.mp3  # Final episode
├── transcript.txt
├── transcript.vtt         # WebVTT subtitles
└── chapters.json          # Podcast chapters
```

## TTS Server Setup

The pipeline expects a TTS server with this API:

```
POST /speak
Content-Type: application/json
{text: "...", voice: "noel", timeout: 0}
→ Returns WAV audio bytes

GET /status
→ {gpus: [{gpu: 0, active: "...", queued: 5}, ...], completed: 100}

GET /voices
→ ["noel", "forbin", "george_carlin", ...]
```

The included TTS client (`src/tts.py`) has:
- Parallel dispatch to multiple GPUs
- Runaway detection (auto-retry if output >= 2x expected duration)
- Queue monitoring and stuck job detection

## Features

- **Deduplication** — Stories covered in the last 7 days are excluded
- **ID3 Chapters** — Each story is a chapter with HN link
- **Transcripts** — VTT and plain text transcripts embedded
- **Variable silence** — Natural pauses between segments (0.5s within stories, 1.0s between)
- **Robust TTS** — Retries on failure, detects runaway inference loops

## License

MIT — See [LICENSE](LICENSE)

## Links

- **RSS Feed:** https://podcast.pdxh.org/dtfhn/feed.xml
- **Spotify:** https://open.spotify.com/show/0JnwyMvqXZQ32B9KbS37Qq
- **Apple Podcasts:** Search "Daily Tech Feed Hacker News"
- **Source:** https://github.com/jhacksman/dtfhn
