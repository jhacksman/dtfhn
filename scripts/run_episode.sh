#!/usr/bin/env bash
# Thin wrapper around run_episode.py for cron compatibility.
# The Python orchestrator handles everything: fetch, scripts, TTS, upload, notifications.
#
# Usage:
#   nohup bash scripts/run_episode.sh > /tmp/dtfhn-episode.log 2>&1 &
#   nohup bash scripts/run_episode.sh 2026-02-09 > /tmp/dtfhn-episode.log 2>&1 &

set -euo pipefail
cd "$(dirname "$0")/.."

# Load credentials from .env if not already set
if [ -z "${CF_R2_ACCESS_KEY_ID:-}" ] && [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Character selection (default: jack)
export CHARACTER="${CHARACTER:-jack}"

# Date-only format (YYYY-MM-DD)
EPISODE_DATE="${1:-$(date +%Y-%m-%d)}"

# Concurrent run protection
LOCKFILE="/tmp/dtfhn-pipeline.lock"
if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE")" 2>/dev/null; then
    echo "ERROR: Pipeline already running (PID $(cat "$LOCKFILE"))"
    exit 1
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

exec python3 scripts/run_episode.py "${EPISODE_DATE}"
