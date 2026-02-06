#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="/tmp/tts_api.log"
PORT=7849

echo "Stopping TTS server..."
pkill -f "python tts_api.py" 2>/dev/null && sleep 2 || true

echo "Starting TTS server..."
cd "$DIR"
nohup .venv/bin/python tts_api.py >> "$LOG" 2>&1 &
PID=$!
echo "Started (pid=$PID), waiting for port $PORT..."

for i in $(seq 1 60); do
    if curl -s -o /dev/null -w '' "http://localhost:$PORT/health" 2>/dev/null; then
        echo "TTS server ready on port $PORT (pid=$PID)"
        exit 0
    fi
    sleep 1
done

echo "ERROR: server did not respond after 60s — check $LOG"
exit 1
