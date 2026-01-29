#!/usr/bin/env python3
"""Generate missing WAVs for an episode.

Reads the manifest to find which segments need WAV files,
then generates them sequentially via the TTS server.

Uses shared utilities from src/tts.py for text preparation
and WAV validation to ensure consistency with the main pipeline.
"""
import argparse
import json
import sys
import time
import requests
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.tts import prepare_text_for_tts, validate_wav_bytes, TTS_URL


def main():
    parser = argparse.ArgumentParser(
        description="Generate missing WAV files for an episode"
    )
    parser.add_argument(
        "episode_date",
        help="Episode date (YYYY-MM-DD or YYYY-MM-DD-HHMM)",
    )
    args = parser.parse_args()

    episode_dir = Path(__file__).parent.parent / "data" / "episodes" / args.episode_date
    wav_dir = episode_dir / "wav_temp"

    if not episode_dir.exists():
        print(f"Episode directory not found: {episode_dir}")
        sys.exit(1)

    wav_dir.mkdir(exist_ok=True)

    # Load manifest for segment order
    manifest_path = episode_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    all_segments = manifest["segments"]

    # Find missing
    existing = {p.stem for p in wav_dir.glob("*.wav")}
    missing = [s for s in all_segments if s not in existing]

    print(f"Episode:       {args.episode_date}")
    print(f"Total segments: {len(all_segments)}")
    print(f"Existing WAVs:  {len(existing)}")
    print(f"Missing WAVs:   {len(missing)}")
    print()

    if not missing:
        print("All WAVs exist! Nothing to do.")
        sys.exit(0)

    for i, seg_name in enumerate(missing):
        txt_path = episode_dir / f"{seg_name}.txt"
        wav_path = wav_dir / f"{seg_name}.wav"

        if not txt_path.exists():
            print(f"[{i+1}/{len(missing)}] {seg_name} — SKIPPED (no .txt file)")
            continue

        text = txt_path.read_text().strip()
        prepared = prepare_text_for_tts(text)
        words = len(text.split())

        print(f"[{i+1}/{len(missing)}] {seg_name} ({words} words)...", end=" ", flush=True)

        start = time.time()
        try:
            resp = requests.post(TTS_URL, json={
                "text": prepared,
                "voice": "george_carlin",
                "timeout": 0,
                "filename": f"{seg_name}.wav",
            }, timeout=600)

            job_id = resp.headers.get("X-Job-Id", "?")

            if resp.status_code != 200:
                print(f"FAILED (HTTP {resp.status_code}: {resp.text[:100]})")
                continue

            # Validate WAV content before writing
            is_valid, error = validate_wav_bytes(resp.content)
            if not is_valid:
                print(f"INVALID WAV: {error} (job={job_id})")
                continue

            wav_path.write_bytes(resp.content)
            elapsed = time.time() - start
            size_kb = len(resp.content) / 1024
            print(f"OK ({elapsed:.1f}s, {size_kb:.0f}KB, job={job_id})")

        except Exception as e:
            print(f"ERROR: {e}")

    # Final check
    final_existing = {p.stem for p in wav_dir.glob("*.wav")}
    still_missing = [s for s in all_segments if s not in final_existing]
    if still_missing:
        print(f"\n⚠️  Still missing {len(still_missing)} WAVs: {still_missing}")
        sys.exit(1)
    else:
        print(f"\n✅ All {len(all_segments)} WAVs generated!")


if __name__ == "__main__":
    main()
