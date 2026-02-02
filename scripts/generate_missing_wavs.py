#!/usr/bin/env python3
"""Generate missing segment audio for an episode.

Reads the manifest to find which segments still need audio,
checking segments/ dir for existing MP3s first.
Generates WAVs via TTS, transcodes to segment MP3s, validates,
then deletes the WAVs.

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
from src.audio import (
    transcode_segment_to_mp3,
    validate_segment_mp3,
)


def main():
    parser = argparse.ArgumentParser(
        description="Generate missing segment audio for an episode"
    )
    parser.add_argument(
        "episode_date",
        help="Episode date (YYYY-MM-DD or YYYY-MM-DD-HHMM)",
    )
    args = parser.parse_args()

    episode_dir = Path(__file__).parent.parent / "data" / "episodes" / args.episode_date
    wav_dir = episode_dir / "wav_temp"
    segments_dir = episode_dir / "segments"

    if not episode_dir.exists():
        print(f"Episode directory not found: {episode_dir}")
        sys.exit(1)

    segments_dir.mkdir(exist_ok=True)

    # Load manifest for segment order
    manifest_path = episode_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    all_segments = manifest["segments"]

    # Check segments/ for existing valid MP3s (the archival format)
    existing_mp3s = {p.stem for p in segments_dir.glob("*.mp3") if validate_segment_mp3(p)}
    missing = [s for s in all_segments if s not in existing_mp3s]

    print(f"Episode:          {args.episode_date}")
    print(f"Total segments:   {len(all_segments)}")
    print(f"Existing MP3s:    {len(existing_mp3s)}")
    print(f"Missing segments: {len(missing)}")
    print()

    if not missing:
        print("All segment MP3s exist! Nothing to do.")
        sys.exit(0)

    # Build segment list: (name, text)
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
    wav_dir.mkdir(exist_ok=True)
    print(f"\nGenerating {len(segments)} segments in parallel (voice: {voice})...\n")

    wav_files, failed = text_to_speech_parallel_robust(
        segments,
        wav_dir,
        voice=voice,
        skip_existing=True,
        abort_on_queue=False,  # We're recovering — don't abort if queue has items
    )

    if failed:
        print(f"\n⚠️  {len(failed)} segments failed TTS: {failed}")
        # Continue to transcode whatever succeeded

    # Transcode WAVs → segment MP3s, validate, delete WAVs
    print("\nTranscoding WAVs to segment MP3s (192k CBR)...")
    for wav_path in wav_files:
        seg_name = wav_path.stem
        mp3_path = segments_dir / f"{seg_name}.mp3"

        if not transcode_segment_to_mp3(wav_path, mp3_path, bitrate="192k"):
            print(f"  ✗ {seg_name} — transcode failed")
            continue

        # WAV safe to delete — MP3 validated
        wav_path.unlink()
        print(f"  ✓ {seg_name}.mp3 ({mp3_path.stat().st_size / 1024:.0f} KB)")

    # Clean up wav_temp/ if empty
    if wav_dir.exists():
        remaining = list(wav_dir.glob("*"))
        if not remaining:
            wav_dir.rmdir()

    # Final check against segment MP3s
    final_mp3s = {p.stem for p in segments_dir.glob("*.mp3") if validate_segment_mp3(p)}
    still_missing = [s for s in all_segments if s not in final_mp3s]
    if still_missing:
        print(f"\n⚠️  Still missing {len(still_missing)} segment MP3s: {still_missing}")
        sys.exit(1)
    else:
        print(f"\n✅ All {len(all_segments)} segment MP3s present!")


if __name__ == "__main__":
    main()
