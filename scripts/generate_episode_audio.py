#!/usr/bin/env python3
"""
Generate TTS audio for a podcast episode.
Fires all segments to quato TTS in parallel, stitches to WAV, transcodes to MP3,
stores in LanceDB with segment metadata.

Features robust TTS pipeline with:
- Lock file to prevent concurrent runs
- Pre-flight checks for queue status and existing files
- Retry logic for failed segments
- Progress monitoring
- Queue management (--status, --clear-queue, --flush-gpu)
- Job tracking via X-Job-Id headers
- Stuck job detection with configurable threshold (10 min default)
- Job listing via --list-jobs

Usage:
    python generate_episode_audio.py 2026-01-27           # Normal mode (aborts if queue not empty)
    python generate_episode_audio.py 2026-01-27 --force   # Skip queue check
    python generate_episode_audio.py 2026-01-27 --wait    # Wait for queue to drain first
    python generate_episode_audio.py --status             # Check TTS server queue status
    python generate_episode_audio.py --clear-queue        # Clear all GPU queues
    python generate_episode_audio.py --flush-gpu 0        # Flush a specific GPU's queue
    python generate_episode_audio.py --list-jobs          # List all tracked jobs with status
"""
import sys
import fcntl
import json
import time
import argparse
import subprocess
import requests
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tts import text_to_speech_parallel_robust, check_tts_status, TTS_STATUS_URL
from src.audio import stitch_wavs, transcode_to_mp3, get_audio_duration, cleanup_wav_files
from src.storage import store_episode, store_segments_batch
from src.chapters import embed_chapters, generate_chapters_json, load_stories_for_episode
from src.metadata import embed_id3_metadata
from src.pipeline import parse_segment_name

# TTS server base URL
TTS_BASE_URL = "http://192.168.0.134:7849"

# Stuck job detection threshold (seconds)
STUCK_JOB_THRESHOLD = 600  # 10 minutes with no progress = warning


def wait_for_queue_drain(timeout_seconds: int = 1800, poll_interval: int = 10,
                         stuck_threshold: int = STUCK_JOB_THRESHOLD) -> bool:
    """
    Wait for TTS queue to drain completely.
    
    The server uses least-queued GPU dispatch (not round-robin), so jobs
    are distributed to whichever GPU has the shortest queue.
    
    Args:
        timeout_seconds: Max time to wait (default 30 min)
        poll_interval: Seconds between status checks
        stuck_threshold: Seconds with no progress before warning
    
    Returns:
        True if queue drained, False if timeout
    """
    start = time.time()
    last_completed = -1
    last_progress_time = time.time()
    stuck_warned = False
    
    while time.time() - start < timeout_seconds:
        status = check_tts_status()
        if "error" in status:
            print(f"  Warning: TTS server error: {status['error']}")
            time.sleep(poll_interval)
            continue
        
        active = status.get('total_active', 0)
        queued = status.get('total_queued', 0)
        completed = status.get('completed', 0)
        
        print(f"  Queue: {active} active, {queued} queued, {completed} completed")
        
        if active == 0 and queued == 0:
            return True
        
        # Stuck job detection
        if completed > last_completed:
            last_completed = completed
            last_progress_time = time.time()
            stuck_warned = False
        else:
            stall_duration = time.time() - last_progress_time
            if stall_duration > stuck_threshold and not stuck_warned:
                print(f"  ⚠️  WARNING: No progress for {stall_duration:.0f}s (threshold: {stuck_threshold}s)")
                print(f"      Jobs may be stuck. Consider --clear-queue or restarting TTS server.")
                stuck_warned = True
        
        time.sleep(poll_interval)
    
    return False


def show_queue_status():
    """Display detailed TTS queue status."""
    status = check_tts_status()
    if "error" in status:
        print(f"ERROR: TTS server unreachable: {status['error']}")
        return False

    print("TTS Server Status")
    print("=" * 50)
    gpus = status.get("gpus", [])
    for gpu in gpus:
        gpu_id = gpu["gpu"]
        active = gpu.get("active")
        queued = gpu.get("queued", 0)
        status_str = f"ACTIVE: {active[:60]}..." if active else "IDLE"
        print(f"  GPU {gpu_id}: {status_str} | {queued} queued")

    print(f"\n  Total active: {status.get('total_active', 0)}")
    print(f"  Total queued: {status.get('total_queued', 0)}")
    print(f"  Completed:    {status.get('completed', 0)}")
    print("=" * 50)
    return True


def clear_gpu_queue(gpu_id: int) -> bool:
    """
    Clear a specific GPU's queue via DELETE /gpu/{gpu_id}/queue.
    
    Cancels all queued (not yet running) jobs for the given GPU.
    
    Args:
        gpu_id: GPU index (0, 1, or 2)
    
    Returns:
        True if queue was cleared successfully
    """
    try:
        resp = requests.delete(f"{TTS_BASE_URL}/gpu/{gpu_id}/queue", timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            cancelled = result.get("cancelled", "?")
            print(f"  GPU {gpu_id}: cleared {cancelled} queued jobs")
            return True
        elif resp.status_code == 404:
            print(f"  GPU {gpu_id}: endpoint not available (404)")
            return False
        else:
            print(f"  GPU {gpu_id}: HTTP {resp.status_code} — {resp.text[:80]}")
            return False
    except Exception as e:
        print(f"  GPU {gpu_id}: Error — {e}")
        return False


def clear_gpu_queues():
    """
    Clear all GPU queues via DELETE /gpu/{id}/queue.
    """
    status = check_tts_status()
    if "error" in status:
        print(f"ERROR: TTS server unreachable: {status['error']}")
        return False

    gpus = status.get("gpus", [])
    any_cleared = False
    for gpu in gpus:
        if clear_gpu_queue(gpu["gpu"]):
            any_cleared = True

    if not any_cleared:
        print("\nNote: No queues were cleared. They may already be empty.")
    return any_cleared


def list_jobs() -> bool:
    """
    List all tracked jobs via GET /jobs.
    
    Returns:
        True if jobs were listed successfully
    """
    try:
        resp = requests.get(f"{TTS_BASE_URL}/jobs", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Response is {"jobs": [...]} with fields: job_id, gpu_id, text_preview, status, submitted_at
            jobs = data.get("jobs", data) if isinstance(data, dict) else data
            if not jobs:
                print("No jobs tracked.")
                return True
            
            print(f"{'ID':<6} {'Status':<12} {'GPU':<5} {'Submitted':<20} {'Text Preview'}")
            print("=" * 100)
            for job in jobs:
                job_id = job.get("job_id", job.get("id", "?"))
                status = job.get("status", "?")
                gpu = job.get("gpu_id", job.get("gpu", "?"))
                submitted = job.get("submitted_at", "")
                if isinstance(submitted, (int, float)):
                    submitted = datetime.fromtimestamp(submitted).strftime("%H:%M:%S")
                text = job.get("text_preview", job.get("text", ""))[:50]
                print(f"{job_id:<6} {status:<12} {gpu:<5} {submitted:<20} {text}")
            
            print(f"\nTotal: {len(jobs)} jobs")
            return True
        elif resp.status_code == 404:
            print("Job listing endpoint not available (404)")
            return False
        else:
            print(f"HTTP {resp.status_code}: {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"Error listing jobs: {e}")
        return False


# Telegram file size limit (Clawdbot media limit is 16MB, leave 1MB margin)
TELEGRAM_SIZE_LIMIT = 15 * 1024 * 1024  # 15 MB


def create_telegram_mp3(source_mp3: Path, output_mp3: Path) -> bool:
    """
    Create a Telegram-friendly MP3 (96k mono) if the source exceeds 15MB.
    
    Args:
        source_mp3: Path to the full-quality episode.mp3
        output_mp3: Path to save the Telegram version (e.g., episode_telegram.mp3)
    
    Returns:
        True if a Telegram version was created, False if not needed or failed
    """
    source_size = source_mp3.stat().st_size
    if source_size <= TELEGRAM_SIZE_LIMIT:
        print(f"  MP3 is {source_size / 1024 / 1024:.1f} MB — under {TELEGRAM_SIZE_LIMIT // (1024*1024)} MB limit, no Telegram version needed.")
        return False
    
    print(f"  MP3 is {source_size / 1024 / 1024:.1f} MB — exceeds {TELEGRAM_SIZE_LIMIT // (1024*1024)} MB limit, creating Telegram version...")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(source_mp3),
                "-ac", "1",           # mono
                "-b:a", "96k",        # 96 kbps
                "-map_metadata", "0", # preserve ID3 tags
                str(output_mp3),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  ERROR: ffmpeg failed: {result.stderr[:200]}")
            return False
        
        tg_size = output_mp3.stat().st_size
        print(f"  Telegram MP3: {output_mp3.name} ({tg_size / 1024 / 1024:.1f} MB)")
        
        if tg_size > TELEGRAM_SIZE_LIMIT:
            print(f"  WARNING: Telegram version still exceeds limit ({tg_size / 1024 / 1024:.1f} MB)!")
        
        return True
    except FileNotFoundError:
        print("  ERROR: ffmpeg not found. Install ffmpeg to enable Telegram transcoding.")
        return False
    except subprocess.TimeoutExpired:
        print("  ERROR: ffmpeg timed out after 120s")
        return False


def parse_args():
    parser = argparse.ArgumentParser(description="Generate TTS audio for podcast episode")
    parser.add_argument("episode_date", nargs="?", help="Episode date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Skip queue check, proceed immediately")
    parser.add_argument("--wait", action="store_true", help="Wait for queue to drain before starting")
    parser.add_argument("--wait-timeout", type=int, default=1800, help="Max seconds to wait for queue (default 1800)")
    parser.add_argument("--status", action="store_true", help="Show TTS server queue status and exit")
    parser.add_argument("--clear-queue", action="store_true", help="Clear all GPU queues and exit")
    parser.add_argument("--flush-gpu", type=int, metavar="GPU_ID",
                        help="Flush a specific GPU's queue (0, 1, or 2) and exit")
    parser.add_argument("--list-jobs", action="store_true", help="List all tracked jobs with status and exit")
    parser.add_argument("--stuck-threshold", type=int, default=STUCK_JOB_THRESHOLD,
                        help=f"Seconds with no progress before warning (default {STUCK_JOB_THRESHOLD})")
    return parser.parse_args()


def load_segments(episode_dir: Path, episode_date: str) -> list[tuple[str, str]]:
    """
    Load all segments in order from manifest.

    Intro and outro are now dynamic files generated by the pipeline
    (episode_dir/00_-_intro.txt and 20_-_outro.txt), not static templates.
    The TTS date is already baked into the generated text.
    """
    segments = []

    # Read manifest for segment order
    manifest_path = episode_dir / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Read all segments (intro, scripts, interstitials, outro) from episode_dir
    for seg_name in manifest["segments"]:
        text = (episode_dir / f"{seg_name}.txt").read_text()
        segments.append((seg_name, text))

    return segments


def build_segment_metadata(
    episode_date: str,
    segments: list[tuple[str, str]],
    wav_files: list[Path]
) -> list[dict]:
    """Build segment metadata with durations from WAV files."""
    # Get durations for each WAV
    durations = {}
    for wav in wav_files:
        name = wav.stem
        durations[name] = get_audio_duration(wav)
    
    # Build metadata
    metadata = []
    offset = 0.0
    
    for i, (name, text) in enumerate(segments):
        duration = durations.get(name, 0.0)
        
        # Determine segment type and position (handles zero-padded names)
        parsed = parse_segment_name(name)
        kind = parsed["kind"]
        
        if kind == "intro":
            seg_type = "intro"
            position = 0
            story_pos = None
            next_story = None
        elif kind == "outro":
            seg_type = "outro"
            position = 99
            story_pos = None
            next_story = None
        elif kind == "script":
            seg_type = "script"
            story_pos = parsed["script_num"]
            position = story_pos
            next_story = None
        elif kind == "interstitial":
            seg_type = "interstitial"
            story_pos = parsed["script_num"]
            next_story = parsed["next_num"]
            position = 10 + story_pos  # interstitials are positions 11-19
        else:
            continue
        
        metadata.append({
            "episode_date": episode_date,
            "segment_type": seg_type,
            "position": position,
            "text": text,
            "duration_seconds": duration,
            "start_offset_seconds": offset,
            "story_position": story_pos,
            "next_story_position": next_story,
            "tts_model": "f5-tts",
            "voice": "george_carlin",
        })
        
        # Add duration + 1s silence gap (except after last segment)
        offset += duration
        if i < len(segments) - 1:
            offset += 1.0  # Silence gap
    
    return metadata


def release_lock(lock_fd, lock_file: Path) -> None:
    """Release the exclusive lock and clean up lock file."""
    if lock_fd is None:
        return
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
        lock_file.unlink(missing_ok=True)
    except Exception:
        pass  # Best effort cleanup


def main():
    args = parse_args()

    # Handle utility commands that don't need an episode date
    if args.status:
        show_queue_status()
        return
    if args.clear_queue:
        print("Clearing GPU queues...")
        clear_gpu_queues()
        return
    if args.flush_gpu is not None:
        print(f"Flushing GPU {args.flush_gpu} queue...")
        clear_gpu_queue(args.flush_gpu)
        return
    if args.list_jobs:
        list_jobs()
        return

    if not args.episode_date:
        print("ERROR: episode_date is required (unless using --status or --clear-queue)")
        sys.exit(1)

    episode_date = args.episode_date
    episode_dir = Path(__file__).parent.parent / "data" / "episodes" / episode_date
    lock_file = episode_dir / ".tts_generation.lock"
    
    print(f"=== Generating TTS for episode {episode_date} ===")
    print()
    
    # LOCK: Prevent concurrent runs
    print("Acquiring lock...")
    episode_dir.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_file, 'w')
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("ERROR: Another TTS generation is already running for this episode.")
        print(f"Lock file: {lock_file}")
        print("If you're sure no other process is running, delete the lock file.")
        sys.exit(1)
    print("Lock acquired.")
    print()
    
    try:
        # PRE-FLIGHT: Check TTS server status
        print("Checking TTS server status...")
        status = check_tts_status()
        if "error" in status:
            print(f"ERROR: TTS server unreachable: {status['error']}")
            sys.exit(1)
        
        active = status.get('total_active', 0)
        queued = status.get('total_queued', 0)
        print(f"TTS server: {active} active, {queued} queued")
        
        if active > 0 or queued > 0:
            print()
            if args.force:
                print("--force: Skipping queue check, proceeding immediately.")
            elif args.wait:
                print("--wait: Waiting for queue to drain...")
                if not wait_for_queue_drain(args.wait_timeout):
                    print(f"ERROR: Queue did not drain within {args.wait_timeout}s timeout.")
                    sys.exit(1)
                print("Queue drained!")
            elif sys.stdin.isatty():
                print("WARNING: TTS queue not empty!")
                print("This may indicate orphaned jobs from a previous run.")
                response = input("Continue anyway? (y/N): ")
                if response.lower() != 'y':
                    print("Aborted.")
                    sys.exit(1)
            else:
                print("ERROR: TTS queue not empty!")
                print("Use --force to skip check, or --wait to wait for drain.")
                sys.exit(1)
        print()
        
        # PRE-FLIGHT: Check for existing WAV files
        wav_dir = episode_dir / "wav_temp"
        if wav_dir.exists():
            existing_wavs = list(wav_dir.glob("*.wav"))
            if existing_wavs:
                print(f"Found {len(existing_wavs)} existing WAV files in {wav_dir}")
                print("These may be from a previous incomplete run.")
                print("The robust TTS function will skip valid existing files.")
                print()
        
        # Load all segments
        print("Loading segments...")
        segments = load_segments(episode_dir, episode_date)
        print(f"Loaded {len(segments)} segments:")
        for name, text in segments:
            words = len(text.split())
            print(f"  {name}: {words} words")
        print()
        
        # Create temp directory for WAVs
        wav_dir.mkdir(exist_ok=True)
        
        # Generate all TTS with robust pipeline
        print("Generating TTS (parallel to 3 GPUs with retry support)...")
        start_time = datetime.now()
        wav_files, failed = text_to_speech_parallel_robust(
            segments,
            wav_dir,
            skip_existing=True,
            abort_on_queue=False,  # Already checked manually above
        )
        tts_time = (datetime.now() - start_time).total_seconds()
        print(f"TTS completed in {tts_time:.1f}s ({len(wav_files)} files)")
        print()
        
        if failed:
            print(f"ERROR: {len(failed)} segments failed after all retries:")
            for name in failed:
                print(f"  - {name}")
            print()
            print("Fix the issue and re-run. Existing WAVs will be reused.")
            sys.exit(1)
        
        if len(wav_files) != len(segments):
            print(f"WARNING: Only {len(wav_files)}/{len(segments)} segments generated!")
        
        # Stitch WAVs together
        print("Stitching WAVs with 1s silence gaps...")
        episode_wav = episode_dir / "episode.wav"
        if not stitch_wavs(wav_files, episode_wav):
            print("ERROR: Failed to stitch WAVs")
            sys.exit(1)
        print(f"Stitched: {episode_wav} ({episode_wav.stat().st_size / 1024 / 1024:.1f} MB)")
        print()
        
        # Transcode to MP3
        print("Transcoding to MP3 (128k mono)...")
        episode_mp3 = episode_dir / "episode.mp3"
        if not transcode_to_mp3(episode_wav, episode_mp3):
            print("ERROR: Failed to transcode to MP3")
            sys.exit(1)
        mp3_size = episode_mp3.stat().st_size
        print(f"MP3: {episode_mp3} ({mp3_size / 1024 / 1024:.1f} MB)")
        print()
        
        # Get final duration
        duration = get_audio_duration(episode_mp3)
        print(f"Duration: {duration:.1f}s ({duration / 60:.1f} min)")
        print()
        
        # Build segment metadata
        print("Building segment metadata...")
        segment_metadata = build_segment_metadata(episode_date, segments, wav_files)
        
        # Store in LanceDB
        print("Storing episode in LanceDB...")
        transcript = (episode_dir / "transcript.txt").read_text()
        mp3_bytes = episode_mp3.read_bytes()
        
        store_episode(
            episode_date=episode_date,
            mp3_binary=mp3_bytes,
            transcript=transcript,
            duration_seconds=duration,
            story_count=10,
        )
        print("Episode stored!")
        
        # Store segment metadata
        print("Storing segment metadata...")
        segment_ids = store_segments_batch(segment_metadata)
        print(f"Stored {len(segment_ids)} segments")
        print()
        
        # Load stories for real chapter titles and HN URLs
        stories = load_stories_for_episode(episode_date)
        
        # Embed ID3 chapters into MP3
        print("Embedding ID3 chapters into MP3...")
        embed_chapters(str(episode_mp3), segment_metadata, stories=stories)
        
        print("Embedding ID3 metadata tags...")
        embed_id3_metadata(
            str(episode_mp3),
            episode_date,
        )
        
        print("Updating chapters.json with actual timing...")
        generate_chapters_json(
            segment_metadata,
            str(episode_dir / "chapters.json"),
            episode_title=f"Daily Tech Feed - {episode_date}",
            stories=stories,
        )
        print()
        
        # Create Telegram-friendly version if needed
        print("Checking Telegram file size...")
        episode_telegram = episode_dir / "episode_telegram.mp3"
        telegram_created = create_telegram_mp3(episode_mp3, episode_telegram)
        print()
        
        # Cleanup temp WAVs
        print("Cleaning up temp WAV files...")
        deleted = cleanup_wav_files(wav_files)
        episode_wav.unlink(missing_ok=True)
        print(f"Deleted {deleted + 1} temp files")
        try:
            wav_dir.rmdir()
        except OSError:
            pass  # Directory may not be empty if there were failures
        print()
        
        # Summary
        print("=" * 50)
        print(f"Episode {episode_date} complete!")
        print(f"  Duration: {duration:.1f}s ({duration / 60:.1f} min)")
        print(f"  MP3 size: {mp3_size / 1024 / 1024:.1f} MB")
        if telegram_created:
            tg_size = episode_telegram.stat().st_size
            print(f"  Telegram: {tg_size / 1024 / 1024:.1f} MB (96k mono)")
        print(f"  Segments: {len(segment_metadata)}")
        print(f"  TTS time: {tts_time:.1f}s")
        print("=" * 50)
    
    finally:
        # Always release lock, even on failure
        release_lock(lock_fd, lock_file)
        print("Lock released.")


if __name__ == "__main__":
    main()
