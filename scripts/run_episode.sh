#!/usr/bin/env bash
# Full DTFHN episode pipeline: fetch → scripts → TTS → done
# Designed to run via nohup. No sub-agents, no timeouts.
#
# Usage:
#   nohup bash scripts/run_episode.sh > /tmp/dtfhn-episode.log 2>&1 &
#   nohup bash scripts/run_episode.sh 2026-01-29-1200 > /tmp/dtfhn-episode.log 2>&1 &

set -euo pipefail
cd "$(dirname "$0")/.."

# Load credentials from .env if not already set
if [ -z "${CF_R2_ACCESS_KEY_ID:-}" ] && [ -f .env ]; then
    echo "Loading credentials from .env"
    set -a
    source .env
    set +a
fi

# --- Notification helper ---
# Sends a system event to Clawdbot gateway (local) on completion.
# Works from nohup'd scripts since clawdbot CLI talks to local gateway.
notify() {
    local status="$1"  # "SUCCESS" or "FAILURE"
    local message="$2"
    echo "[notify] ${status}: ${message}" | tee -a "${LOG:-/dev/null}"
    # Send via clawdbot system event (local gateway, no auth needed)
    clawdbot system event \
        --text "DTFHN Pipeline ${status}: ${message}" \
        --mode now 2>&1 || echo "[notify] WARNING: clawdbot system event failed" | tee -a "${LOG:-/dev/null}"
}

# Concurrent run protection
LOCKFILE="/tmp/dtfhn-pipeline.lock"
if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE")" 2>/dev/null; then
    echo "ERROR: Pipeline already running (PID $(cat "$LOCKFILE"))"
    exit 1
fi
echo $$ > "$LOCKFILE"

# --- Failure trap ---
# On any error (set -e), notify and clean up
on_error() {
    local exit_code=$?
    local line_no=${BASH_LINENO[0]:-unknown}
    notify "FAILURE" "Episode ${EPISODE_DATE:-unknown} failed at line ${line_no} (exit ${exit_code}). Check log: ${LOG:-/tmp/dtfhn-episode.log}"
    rm -f "$LOCKFILE"
    exit $exit_code
}
trap 'on_error' ERR
trap 'rm -f "$LOCKFILE"' EXIT

EPISODE_DATE="${1:-$(date +%Y-%m-%d-%H%M)}"
LOG="/tmp/dtfhn-${EPISODE_DATE}.log"

echo "=== DTFHN Episode: ${EPISODE_DATE} ===" | tee "$LOG"
echo "Started: $(date)" | tee -a "$LOG"

# Step 1: Text pipeline (fetch, scripts, interstitials, intro/outro, metadata)
echo "[1/4] Running text pipeline..." | tee -a "$LOG"
python3 -u -c "
import sys
from src.pipeline import run_episode_pipeline
import json
manifest = run_episode_pipeline(episode_date=sys.argv[1], num_stories=10, word_target=4000, verbose=True)
print(json.dumps(manifest, indent=2))
" "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"

# Step 2: TTS
echo "[2/4] Running TTS..." | tee -a "$LOG"
python3 -u scripts/generate_episode_audio.py "${EPISODE_DATE}" --force 2>&1 | tee -a "$LOG"

# Step 3: Upload to R2 + regenerate feed
echo "[3/4] Uploading to R2..." | tee -a "$LOG"
if [ -n "${CF_R2_ACCESS_KEY_ID:-}" ] && [ -n "${CF_R2_SECRET_ACCESS_KEY:-}" ]; then
    python3 -u scripts/upload_to_r2.py "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"
else
    echo "  SKIPPED: R2 credentials not set (CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY)" | tee -a "$LOG"
fi

# Step 4: Trigger Cloudflare Pages rebuild
echo "[4/4] Triggering website rebuild..." | tee -a "$LOG"
if [ -n "${CF_PAGES_DEPLOY_HOOK_URL:-}" ]; then
    DEPLOY_RESPONSE=$(curl -s -X POST "${CF_PAGES_DEPLOY_HOOK_URL}" 2>&1) || true
    echo "  Deploy hook response: ${DEPLOY_RESPONSE}" | tee -a "$LOG"
else
    echo "  SKIPPED: CF_PAGES_DEPLOY_HOOK_URL not set in .env" | tee -a "$LOG"
fi

echo "=== DONE: ${EPISODE_DATE} ===" | tee -a "$LOG"
echo "Finished: $(date)" | tee -a "$LOG"

# Notify success
notify "SUCCESS" "Episode ${EPISODE_DATE} completed. Log: ${LOG}"
