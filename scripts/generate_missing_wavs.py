#!/usr/bin/env python3
"""Generate missing WAVs for episode 2026-01-29."""
import json
import os
import sys
import time
import requests
from pathlib import Path

EPISODE_DIR = Path(__file__).parent.parent / "data" / "episodes" / "2026-01-29"
WAV_DIR = EPISODE_DIR / "wav_temp"
TTS_URL = "http://192.168.0.134:7849/speak"

WAV_DIR.mkdir(exist_ok=True)

# Load manifest for segment order
manifest = json.loads((EPISODE_DIR / "manifest.json").read_text())
all_segments = manifest["segments"]

# Find missing
existing = {p.stem for p in WAV_DIR.glob("*.wav")}
missing = [s for s in all_segments if s not in existing]

print(f"Total segments: {len(all_segments)}")
print(f"Existing WAVs: {len(existing)}")
print(f"Missing WAVs: {len(missing)}")
print()

if not missing:
    print("All WAVs exist! Nothing to do.")
    sys.exit(0)

for i, seg_name in enumerate(missing):
    txt_path = EPISODE_DIR / f"{seg_name}.txt"
    wav_path = WAV_DIR / f"{seg_name}.wav"
    
    text = txt_path.read_text().strip()
    words = len(text.split())
    
    print(f"[{i+1}/{len(missing)}] {seg_name} ({words} words)...", end=" ", flush=True)
    
    start = time.time()
    try:
        resp = requests.post(TTS_URL, json={
            "text": text,
            "voice": "george_carlin",
            "timeout": 0,
            "filename": f"{seg_name}.wav"
        }, timeout=600)  # 10 min HTTP timeout per segment
        
        job_id = resp.headers.get("X-Job-Id", "?")
        
        if resp.status_code == 200:
            wav_path.write_bytes(resp.content)
            elapsed = time.time() - start
            size_kb = len(resp.content) / 1024
            print(f"OK ({elapsed:.1f}s, {size_kb:.0f}KB, job={job_id})")
        else:
            print(f"FAILED (HTTP {resp.status_code}: {resp.text[:100]})")
    except Exception as e:
        print(f"ERROR: {e}")

# Final check
final_existing = {p.stem for p in WAV_DIR.glob("*.wav")}
still_missing = [s for s in all_segments if s not in final_existing]
if still_missing:
    print(f"\n⚠️  Still missing {len(still_missing)} WAVs: {still_missing}")
    sys.exit(1)
else:
    print(f"\n✅ All {len(all_segments)} WAVs generated!")
