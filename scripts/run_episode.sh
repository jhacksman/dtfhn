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
    openclaw system event \
        --text "DTFHN Pipeline ${status}: ${message}" \
        --mode now 2>&1 || echo "[notify] WARNING: openclaw system event failed" | tee -a "${LOG:-/dev/null}"
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
echo "[1/5] Running text pipeline..." | tee -a "$LOG"
python3 -u -c "
import sys
from src.pipeline import run_episode_pipeline
import json
manifest = run_episode_pipeline(episode_date=sys.argv[1], num_stories=10, word_target=4000, verbose=True)
print(json.dumps(manifest, indent=2))
" "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"

# Pre-flight: TTS server health check (retry 3x with 30s sleep)
echo "[pre-flight] Checking TTS server..." | tee -a "$LOG"
TTS_OK=0
for i in 1 2 3; do
    if curl -sf http://192.168.0.134:7849/ > /dev/null 2>&1; then
        echo "  TTS server is up" | tee -a "$LOG"
        TTS_OK=1
        break
    fi
    echo "  TTS server not responding, retry $i/3..." | tee -a "$LOG"
    sleep 30
done
if [ "$TTS_OK" -ne 1 ]; then
    notify "FAILURE" "Episode ${EPISODE_DATE}: TTS server unreachable after 3 retries"
    exit 1
fi

# Step 2: TTS
echo "[2/5] Running TTS..." | tee -a "$LOG"
python3 -u scripts/generate_episode_audio.py "${EPISODE_DATE}" --force 2>&1 | tee -a "$LOG"

# Step 3: Upload to R2 + regenerate feed
echo "[3/5] Uploading to R2..." | tee -a "$LOG"
if [ -n "${CF_R2_ACCESS_KEY_ID:-}" ] && [ -n "${CF_R2_SECRET_ACCESS_KEY:-}" ]; then
    python3 -u scripts/upload_to_r2.py "${EPISODE_DATE}" 2>&1 | tee -a "$LOG"
else
    echo "  SKIPPED: R2 credentials not set (CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY)" | tee -a "$LOG"
fi

# Post-upload verification: confirm episode is accessible on CDN
echo "[verify] Checking episode URL..." | tee -a "$LOG"
EPISODE_URL="https://podcast.pdxh.org/dtfhn/episodes/DTFHN-${EPISODE_DATE}.mp3"
HTTP_CODE=$(curl -so /dev/null -w '%{http_code}' "$EPISODE_URL" 2>/dev/null) || HTTP_CODE="000"
if [ "$HTTP_CODE" = "200" ]; then
    echo "  Episode accessible (HTTP 200)" | tee -a "$LOG"
else
    echo "  WARNING: Episode returned HTTP ${HTTP_CODE} (may need CDN propagation time)" | tee -a "$LOG"
fi

# Step 4: Trigger Cloudflare Pages rebuild
echo "[4/5] Triggering website rebuild..." | tee -a "$LOG"
if [ -n "${CF_PAGES_DEPLOY_HOOK_URL:-}" ]; then
    DEPLOY_RESPONSE=$(curl -s -X POST "${CF_PAGES_DEPLOY_HOOK_URL}" 2>&1) || true
    echo "  Deploy hook response: ${DEPLOY_RESPONSE}" | tee -a "$LOG"
else
    echo "  SKIPPED: CF_PAGES_DEPLOY_HOOK_URL not set in .env" | tee -a "$LOG"
fi

# Step 5: Telegram delivery notification (non-fatal)
echo "[5/5] Sending Telegram notification..." | tee -a "$LOG"
EPISODE_URL="https://podcast.pdxh.org/dtfhn/episodes/DTFHN-${EPISODE_DATE}.mp3"
FEED_URL="https://podcast.pdxh.org/dtfhn/feed.xml"
# Extract story count and duration from the episode manifest/log
STORY_COUNT=$(python3 -c "
import json, sys
try:
    m = json.load(open('data/episodes/${EPISODE_DATE}/manifest.json'))
    scripts = [s for s in m.get('segments', []) if 'script' in s and 'interstitial' not in s]
    print(len(scripts))
except: print('?')
" 2>/dev/null) || STORY_COUNT="?"
DURATION=$(python3 -c "
from src.audio import get_audio_duration
from pathlib import Path
mp3 = Path('data/episodes/${EPISODE_DATE}/DTFHN-${EPISODE_DATE}.mp3')
if mp3.exists():
    d = get_audio_duration(mp3)
    print(f'{d/60:.0f} min')
else: print('?')
" 2>/dev/null) || DURATION="?"
TG_MSG="🎙️ New DTFHN Episode: ${EPISODE_DATE}

📊 ${STORY_COUNT} stories · ${DURATION}
🎧 ${EPISODE_URL}
📡 ${FEED_URL}"
/opt/homebrew/bin/openclaw message send \
    --channel telegram \
    --target "6151859458" \
    --message "${TG_MSG}" 2>&1 | tee -a "$LOG" || echo "  WARNING: Telegram notification failed" | tee -a "$LOG"

echo "=== DONE: ${EPISODE_DATE} ===" | tee -a "$LOG"
echo "Finished: $(date)" | tee -a "$LOG"

# Notify success
notify "SUCCESS" "Episode ${EPISODE_DATE} completed. Log: ${LOG}"
