#!/bin/bash
# Generate Feb 13 and Feb 14 episodes with 5-clip longest-wins strategy
set -euo pipefail
cd "$(dirname "$0")/.."
export CHARACTER=jack

LOG="scripts/feb13_14.log"
echo "=== Starting Feb 13 + Feb 14 pipeline ===" | tee "$LOG"
echo "Started at: $(date)" | tee -a "$LOG"

for DATE in 2026-02-13 2026-02-14; do
    echo "" | tee -a "$LOG"
    echo "====== Episode: $DATE ======" | tee -a "$LOG"
    
    EPISODE_DIR="data/episodes/$DATE"
    MANIFEST="$EPISODE_DIR/manifest.json"
    
    # Phase 1+2: Fetch + Scripts (only if manifest doesn't exist)
    if [ ! -f "$MANIFEST" ]; then
        echo "--- Generating scripts for $DATE ---" | tee -a "$LOG"
        python3 -c "
import os, sys
os.environ['CHARACTER'] = 'jack'
sys.path.insert(0, '.')
from scripts.run_episode import phase_fetch, phase_scripts, get_pipeline_state
from src.pipeline import get_episode_dir
from src.storage import upsert_pipeline_state

episode_date = '$DATE'
episode_dir = get_episode_dir(episode_date)
upsert_pipeline_state(episode_date, phase='fetch')
phase_fetch(episode_date, episode_dir)
phase_scripts(episode_date, episode_dir)
print(f'Scripts complete for {episode_date}')
" 2>&1 | tee -a "$LOG"
    else
        echo "Scripts already exist for $DATE, skipping" | tee -a "$LOG"
    fi
    
    # Phase 3: TTS with 5-clip strategy
    echo "--- TTS with 5-take strategy for $DATE ---" | tee -a "$LOG"
    python3 -u scripts/generate_episode_audio.py "$DATE" --force --num-takes 5 2>&1 | tee -a "$LOG"
    
    echo "--- Episode $DATE complete ---" | tee -a "$LOG"
done

echo "" | tee -a "$LOG"
echo "=== All done at $(date) ===" | tee -a "$LOG"

# Send to Telegram
for DATE in 2026-02-13 2026-02-14; do
    MP3="data/episodes/$DATE/DTFHN-$DATE.mp3"
    if [ -f "$MP3" ]; then
        echo "Sending $MP3 to Telegram..." | tee -a "$LOG"
        openclaw message send --channel telegram --target 6151859458 \
            --file "$MP3" --caption "DTFHN $DATE - 5-take longest-wins strategy" 2>&1 | tee -a "$LOG" || true
    fi
done
