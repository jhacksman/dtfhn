#!/usr/bin/env python3
"""Generate missing WAVs for an episode.

Reads the manifest to find which segments need WAV files,
then generates them in parallel via the TTS server (all 3 GPUs).

Uses shared utilities from src/tts.py for text preparation,
WAV validation, and parallel dispatch.
"""
import argparse
import json
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.tts import (
    prepare_text_for_tts,
    text_to_speech_parallel_robust,
    get_tts_voice,
)


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

    # Build segment list: (name, prepared_text)
    segments = []
    for seg_name in missing:
        txt_path = episode_dir / f"{seg_name}.txt"
        if not txt_path.exists():
            print(f"  SKIPPED {seg_name} — no .txt file")
            continue
        text = txt_path.read_text().strip()
        words = len(text.split())
        print(f"  {seg_name}: {words} words")
        segments.append((seg_name, text))

    if not segments:
        print("No segments to generate!")
        sys.exit(1)

    voice = get_tts_voice()
    print(f"\nGenerating {len(segments)} segments in parallel (voice: {voice})...\n")

    wav_files, failed = text_to_speech_parallel_robust(
        segments,
        wav_dir,
        voice=voice,
        skip_existing=True,
        abort_on_queue=False,  # We're recovering — don't abort if queue has items
    )

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
