#!/usr/bin/env bash
# Full DTFHN episode pipeline: fetch → scripts → TTS → done
# Designed to run via nohup. No sub-agents, no timeouts.
#
# Usage:
#   nohup bash scripts/run_episode.sh > /tmp/dtfhn-episode.log 2>&1 &
#   nohup bash scripts/run_episode.sh 2026-01-29-1200 > /tmp/dtfhn-episode.log 2>&1 &

set -euo pipefail
cd "$(dirname "$0")/.."

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
echo "[1/2] Running text pipeline..." | tee -a "$LOG"
python3 -u -c "
import sys
from src.pipeline import run_episode_pipeline
import json
manifest = run_episode_pipeline(episode_date=sys.argv[1], num_stories=10, word_target=4000, verbose=True)
print(json.dumps(manifest, indent=2))
" "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"

# Step 2: TTS
echo "[2/2] Running TTS..." | tee -a "$LOG"
python3 -u scripts/generate_episode_audio.py "${EPISODE_DATE}" --force 2>&1 | tee -a "$LOG"

echo "=== DONE: ${EPISODE_DATE} ===" | tee -a "$LOG"
echo "Finished: $(date)" | tee -a "$LOG"
