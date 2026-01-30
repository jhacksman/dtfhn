#!/usr/bin/env bash
# Full DTFHN episode pipeline: fetch → scripts → TTS → done
# Designed to run via nohup. No sub-agents, no timeouts.
#
# Usage:
#   nohup bash scripts/run_episode.sh > /tmp/dtfhn-episode.log 2>&1 &
#   nohup bash scripts/run_episode.sh 2026-01-29-1200 > /tmp/dtfhn-episode.log 2>&1 &

set -euo pipefail
cd "$(dirname "$0")/.."

# Load R2 credentials from .env if not already set
if [ -z "${CF_R2_ACCESS_KEY_ID:-}" ] && [ -f .env ]; then
    echo "Loading R2 credentials from .env"
    set -a
    source .env
    set +a
fi

# Concurrent run protection
LOCKFILE="/tmp/dtfhn-pipeline.lock"
if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE")" 2>/dev/null; then
    echo "ERROR: Pipeline already running (PID $(cat "$LOCKFILE"))"
    exit 1
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

EPISODE_DATE="${1:-$(date +%Y-%m-%d-%H%M)}"
LOG="/tmp/dtfhn-${EPISODE_DATE}.log"

echo "=== DTFHN Episode: ${EPISODE_DATE} ===" | tee "$LOG"
echo "Started: $(date)" | tee -a "$LOG"

# Step 1: Text pipeline (fetch, scripts, interstitials, intro/outro, metadata)
echo "[1/3] Running text pipeline..." | tee -a "$LOG"
python3 -u -c "
import sys
from src.pipeline import run_episode_pipeline
import json
manifest = run_episode_pipeline(episode_date=sys.argv[1], num_stories=10, word_target=4000, verbose=True)
print(json.dumps(manifest, indent=2))
" "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"

# Step 2: TTS
echo "[2/3] Running TTS..." | tee -a "$LOG"
python3 -u scripts/generate_episode_audio.py "${EPISODE_DATE}" --force 2>&1 | tee -a "$LOG"

# Step 3: Upload to R2 + regenerate feed
echo "[3/3] Uploading to R2..." | tee -a "$LOG"
if [ -n "${CF_R2_ACCESS_KEY_ID:-}" ] && [ -n "${CF_R2_SECRET_ACCESS_KEY:-}" ]; then
    python3 -u scripts/upload_to_r2.py "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"
else
    echo "  SKIPPED: R2 credentials not set (CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY)" | tee -a "$LOG"
fi

echo "=== DONE: ${EPISODE_DATE} ===" | tee -a "$LOG"
echo "Finished: $(date)" | tee -a "$LOG"
