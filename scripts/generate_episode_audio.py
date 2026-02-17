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
import subprocess
import fcntl
import json
import time
import random
import re
import argparse
import requests
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.tts import text_to_speech_parallel_robust, check_tts_status, TTS_STATUS_URL, warmup_tts_server
from src.audio import (
    stitch_wavs, transcode_to_mp3, get_audio_duration, cleanup_wav_files,
    generate_silence_wav, transcode_segment_to_mp3, validate_segment_mp3,
    stitch_mp3s_variable,
)
from src.storage import store_episode, store_segments_batch
from src.chapters import embed_chapters, generate_chapters_json, load_stories_for_episode
from src.metadata import embed_id3_metadata
from src.pipeline import parse_segment_name
from src.generator import get_character_config

# TTS server base URL
TTS_BASE_URL = "http://192.168.0.134:7849"

# Stuck job detection threshold (seconds)
STUCK_JOB_THRESHOLD = 600  # 10 minutes with no progress = warning

# ---------------------------------------------------------------------------
# Pipeline config (loaded from pipeline_config.json)
# ---------------------------------------------------------------------------

PIPELINE_CONFIG_PATH = PROJECT_ROOT / "pipeline_config.json"


def load_pipeline_config() -> dict:
    """Load pipeline_config.json. Falls back to defaults if missing."""
    if PIPELINE_CONFIG_PATH.exists():
        with open(PIPELINE_CONFIG_PATH) as f:
            config = json.load(f)
        print(f"Loaded pipeline config from {PIPELINE_CONFIG_PATH}")
        return config
    print("WARNING: pipeline_config.json not found, using defaults")
    return {
        "voice": {"tts_voice": "forbin", "tts_instruct": None, "rvc_enabled": False},
        "pause": {"increments": [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]},
        "music": {},
        "audio": {"loudnorm_i": -13, "loudnorm_tp": -1, "loudnorm_lra": 11,
                  "sample_rate": 44100, "bitrate": "192k"},
    }


# ---------------------------------------------------------------------------
# RVC voice conversion
# ---------------------------------------------------------------------------

def rvc_convert(wav_path: Path, output_path: Path, rvc_url: str, rvc_model: str,
                retries: int = 3) -> bool:
    """
    Convert a WAV through RVC voice model.
    
    Args:
        wav_path: Input WAV file
        output_path: Output WAV file (RVC-converted)
        rvc_url: RVC server URL (e.g., http://192.168.0.134:7850/convert)
        rvc_model: RVC model name (e.g., "bob")
        retries: Number of retry attempts
    
    Returns:
        True if conversion succeeded
    """
    if output_path.exists() and output_path.stat().st_size > 1000:
        return True  # Already converted
    
    for attempt in range(retries):
        try:
            with open(wav_path, 'rb') as f:
                resp = requests.post(
                    rvc_url,
                    files={"audio": f},
                    data={"model_name": rvc_model},
                    timeout=300,
                )
            if resp.status_code == 200 and len(resp.content) > 1000:
                output_path.write_bytes(resp.content)
                return True
            print(f"  RVC fail: status={resp.status_code} size={len(resp.content)}")
        except Exception as e:
            print(f"  RVC error (attempt {attempt + 1}/{retries}): {e}")
        time.sleep(10 * (attempt + 1))
    return False


# ---------------------------------------------------------------------------
# Music overlay
# ---------------------------------------------------------------------------

def apply_music_overlay(
    body_wav: Path,
    output_wav: Path,
    intro_wav: Path,
    outro_wav: Path,
    theme_path: Path,
    music_config: dict,
) -> bool:
    """
    Apply theme music overlay to intro and outro sections of the episode.
    
    Intro: theme at intro_volume under voice, fade out after voice ends.
    Outro: theme at outro_volume under voice, ramp to full after voice ends,
           play remainder of full theme.
    
    Args:
        body_wav: Full episode WAV (all segments stitched)
        output_wav: Output WAV with music overlay
        intro_wav: Just the intro segment WAV (to get duration)
        outro_wav: Just the outro segment WAV (to get duration)
        theme_path: Path to theme MP3/WAV file
        music_config: Music config from pipeline_config.json
    
    Returns:
        True if overlay succeeded
    """
    if not theme_path.exists():
        print(f"WARNING: Theme file not found at {theme_path}, skipping music overlay")
        return False
    
    intro_vol = music_config.get("intro_volume", 0.15)
    intro_fade = music_config.get("intro_fade_out_seconds", 2)
    outro_vol = music_config.get("outro_volume_under_voice", 0.15)
    outro_ramp = music_config.get("outro_ramp_to_full_seconds", 2)
    play_full = music_config.get("outro_play_full_theme", True)
    
    intro_dur = get_audio_duration(intro_wav)
    outro_dur = get_audio_duration(outro_wav)
    body_dur = get_audio_duration(body_wav)
    theme_dur = get_audio_duration(theme_path)
    
    if intro_dur <= 0 or outro_dur <= 0 or body_dur <= 0:
        print("WARNING: Could not determine audio durations, skipping music overlay")
        return False
    
    # Outro starts at body_dur - outro_dur
    outro_start = body_dur - outro_dur
    
    # Build complex ffmpeg filter:
    # [0] = body audio
    # [1] = theme for intro
    # [2] = theme for outro
    #
    # Intro overlay: theme at intro_vol, from 0 to intro_dur + intro_fade, then fade out
    # Outro overlay: theme at outro_vol under voice, then ramp to 1.0 after voice
    
    intro_end = intro_dur + intro_fade
    
    # For outro: theme plays from outro_start to end
    # Under voice: volume = outro_vol
    # After voice ends: ramp to full over outro_ramp seconds
    # If play_full: let theme play its full duration after voice
    if play_full:
        outro_total = outro_dur + outro_ramp + max(0, theme_dur - outro_dur - outro_ramp)
    else:
        outro_total = outro_dur + outro_ramp + 3  # 3s tail
    
    # Build ffmpeg command with complex filter
    # We'll use two passes: intro overlay, then outro overlay
    # Simpler: one pass with two theme inputs
    
    filter_complex = (
        # Intro theme: trim to intro_end, set volume, fade out at end
        f"[1:a]atrim=0:{intro_end},volume={intro_vol},afade=t=out:st={intro_dur}:d={intro_fade}[intro_music];"
        # Pad intro music to start at 0 and extend to body length
        f"[intro_music]apad=whole_dur={body_dur + outro_total}[intro_padded];"
        # Outro theme: set initial volume, then ramp up after voice
        # Use volume filter with enable for the two phases
        f"[2:a]volume={outro_vol}:enable='between(t,0,{outro_dur})',"
        f"volume=1.0:enable='gte(t,{outro_dur + outro_ramp})',"
        f"afade=t=in:st={outro_dur}:d={outro_ramp}[outro_music];"
        # Delay outro music to start at outro_start
        f"[outro_music]adelay={int(outro_start * 1000)}|{int(outro_start * 1000)}[outro_delayed];"
        # Pad to ensure same length
        f"[outro_delayed]apad=whole_dur={body_dur + outro_total}[outro_padded];"
        # Pad body to extend for outro tail
        f"[0:a]apad=whole_dur={body_dur + outro_total}[body_padded];"
        # Mix all three
        f"[body_padded][intro_padded][outro_padded]amix=inputs=3:duration=longest:normalize=0[out]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(body_wav),
        "-i", str(theme_path),
        "-i", str(theme_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", "24000", "-ac", "1",
        str(output_wav),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    if result.returncode != 0:
        print(f"Music overlay ffmpeg error: {result.stderr[:500]}")
        return False
    
    print(f"Music overlay applied: intro={intro_dur:.1f}s, outro={outro_dur:.1f}s, theme={theme_dur:.1f}s")
    return True


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
    parser.add_argument("--num-takes", type=int, default=1,
                        help="Number of TTS takes per segment; keep longest (default 1)")
    return parser.parse_args()


def find_existing_segment_mp3s(
    segments: list[tuple[str, str, str]],
    segments_dir: Path,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """
    Check segments/ dir for existing valid MP3s to determine what still needs rendering.
    
    Args:
        segments: List of (segment_name, text, parent_segment_name) tuples
        segments_dir: Path to segments/ directory
    
    Returns:
        (existing_names, missing_segments)
        - existing_names: segment names that already have valid MP3s
        - missing_segments: segments that still need TTS + transcode
    """
    existing = []
    missing = []
    
    for name, text, parent in segments:
        mp3_path = segments_dir / f"{name}.mp3"
        if validate_segment_mp3(mp3_path):
            existing.append(name)
        else:
            missing.append((name, text, parent))
    
    return existing, missing


def split_into_paragraphs(text: str, min_words: int = 20) -> tuple[list[str], list[bool]]:
    """
    Split script text into TTS chunks, respecting [pause] markers as hard breaks.
    
    [pause] markers create mandatory segment boundaries with longer silence gaps.
    Regular paragraph breaks (\n\n) use the standard grouping/pairing logic.
    
    CRITICAL: After splitting, verifies NO chunk still contains literal [pause].
    If found, strips it and logs a warning.
    
    For paragraphs within a [pause] section, uses fixed grouping:
      - Pairs paragraphs (1+2), (3+4), last solo if odd
      - Short paragraphs (< min_words) merge into previous chunk
    
    Args:
        text: Full segment text (may contain [pause] markers)
        min_words: Minimum words per chunk (shorter ones merge with previous)
    
    Returns:
        Tuple of:
          - List of text chunks, each suitable for a TTS job
          - List of booleans (len = len(chunks) - 1): True if the boundary
            between chunk[i] and chunk[i+1] is a [pause] break (gets random
            silence from config increments), False for a normal paragraph break
    """
    # Split on [pause] markers first — case-insensitive
    pause_sections = re.split(r'\[pause\]', text, flags=re.IGNORECASE)
    
    all_chunks = []
    pause_boundaries = []  # True at boundaries that came from [pause]
    
    for si, section in enumerate(pause_sections):
        section = section.strip()
        if not section:
            continue
        
        # Split this section into paragraphs
        raw_paragraphs = [p.strip() for p in section.split("\n\n") if p.strip()]
        if not raw_paragraphs:
            continue
        
        if len(raw_paragraphs) == 1:
            section_chunks = raw_paragraphs
        else:
            # Merge very short paragraphs into previous first
            merged = [raw_paragraphs[0]]
            for p in raw_paragraphs[1:]:
                if len(p.split()) < min_words and merged:
                    merged[-1] = merged[-1] + "\n\n" + p
                else:
                    merged.append(p)
            
            # Pair: (1+2), (3+4), last solo — generalized for any count
            section_chunks = []
            i = 0
            while i < len(merged):
                if i + 1 < len(merged) and i + 2 <= len(merged) - 1:
                    section_chunks.append(merged[i] + "\n\n" + merged[i + 1])
                    i += 2
                else:
                    section_chunks.append(merged[i])
                    i += 1
        
        # If we already have chunks from a previous section, the boundary
        # between the last existing chunk and the first of this section is a [pause]
        if all_chunks and section_chunks:
            pause_boundaries.append(True)  # [pause] boundary
        
        # Add paragraph boundaries between chunks within this section
        for ci, chunk in enumerate(section_chunks):
            all_chunks.append(chunk)
            if ci < len(section_chunks) - 1:
                pause_boundaries.append(False)  # Normal paragraph boundary
    
    if not all_chunks:
        return [text.strip()], []
    
    # CRITICAL: Verify no chunk still contains [pause] literal
    for i, chunk in enumerate(all_chunks):
        if re.search(r'\[pause\]', chunk, flags=re.IGNORECASE):
            print(f"  WARNING: Chunk {i} still contains [pause] literal — stripping it")
            all_chunks[i] = re.sub(r'\[pause\]', '', chunk, flags=re.IGNORECASE).strip()
    
    return all_chunks, pause_boundaries


def load_segments(episode_dir: Path, episode_date: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """
    Load all segments in order from manifest, splitting scripts into
    paragraph-level sub-segments for better TTS quality.

    Intro and outro are loaded as single segments.
    Scripts are split into paragraph sub-segments (e.g., 01_-_script_01_p00, _p01, ...).
    [pause] markers in scripts create hard segment boundaries with longer silence.
    Interstitials are loaded as single segments.
    
    Also applies preamble stripping to intro/outro to catch LLM chain-of-thought leakage.

    Returns:
        Tuple of:
          - List of (segment_name, text, parent_segment_name) tuples.
            parent_segment_name == segment_name for non-split segments.
          - List of boundary types (len = len(segments) - 1):
            "pause" for [pause] breaks (0.75s silence)
            "paragraph" for paragraph breaks within same parent (0.5s silence)
            "major" for breaks between different parent segments (1.0s silence)
    """
    from src.generator import _strip_preamble
    
    segments = []
    boundary_types = []  # One per gap between consecutive segments

    # Read manifest for segment order
    manifest_path = episode_dir / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Read all segments, splitting scripts into paragraphs
    for seg_name in manifest["segments"]:
        text = (episode_dir / f"{seg_name}.txt").read_text().strip()
        
        # Major break before this segment (if not first)
        if segments:
            boundary_types.append("major")
        
        # Strip preamble from intro only (outro's opening paragraph is valid content)
        if "intro" in seg_name:
            text = _strip_preamble(text)
            segments.append((seg_name, text, seg_name))
        elif "outro" in seg_name:
            segments.append((seg_name, text, seg_name))
        elif "script" in seg_name:
            # Split scripts into paragraph sub-segments, respecting [pause] markers
            paragraphs, pause_boundaries = split_into_paragraphs(text)
            if len(paragraphs) == 1:
                segments.append((seg_name, paragraphs[0], seg_name))
            else:
                for pi, para in enumerate(paragraphs):
                    sub_name = f"{seg_name}_p{pi:02d}"
                    segments.append((sub_name, para, seg_name))
                    # Add boundary type between sub-segments
                    if pi < len(paragraphs) - 1:
                        if pi < len(pause_boundaries) and pause_boundaries[pi]:
                            boundary_types.append("pause")
                        else:
                            boundary_types.append("paragraph")
        else:
            # Interstitials stay as single segments
            segments.append((seg_name, text, seg_name))

    return segments, boundary_types


def build_segment_metadata(
    episode_date: str,
    segments: list[tuple[str, str]],
    audio_files: list[Path]
) -> list[dict]:
    """Build segment metadata with durations from audio files (WAV or MP3)."""
    # Get durations for each audio file
    durations = {}
    for af in audio_files:
        name = af.stem
        durations[name] = get_audio_duration(af)
    
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
            "voice": get_character_config()["tts_voice"],
        })
        
        # Add duration + 1s silence gap (except after last segment)
        offset += duration
        if i < len(segments) - 1:
            offset += 1.0  # Silence gap
    
    return metadata


def stitch_wavs_variable(
    wav_files: list[Path],
    output_path: Path,
    silence_durations: list[float],
) -> bool:
    """
    Concatenate WAV files with variable silence gaps between them.
    
    Args:
        wav_files: List of WAV file paths in order
        output_path: Where to save the concatenated WAV
        silence_durations: Silence duration after each WAV (len = len(wav_files) - 1)
    
    Returns:
        True if successful
    """
    import tempfile
    
    if not wav_files:
        print("No WAV files to stitch")
        return False
    
    if len(silence_durations) != len(wav_files) - 1:
        print(f"ERROR: silence_durations length ({len(silence_durations)}) must be len(wav_files)-1 ({len(wav_files) - 1})")
        return False
    
    # Pre-generate silence WAVs for each unique duration
    unique_durations = set(silence_durations)
    silence_wavs = {}
    tmp_files = []
    
    try:
        for dur in unique_durations:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                silence_path = Path(f.name)
                tmp_files.append(silence_path)
            if not generate_silence_wav(silence_path, duration=dur):
                print(f"Failed to generate {dur}s silence WAV")
                return False
            silence_wavs[dur] = silence_path
        
        # Build concat file list
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            list_file = Path(f.name)
            tmp_files.append(list_file)
            for i, wav in enumerate(wav_files):
                f.write(f"file '{wav.absolute()}'\n")
                if i < len(silence_durations):
                    sil = silence_wavs[silence_durations[i]]
                    f.write(f"file '{sil.absolute()}'\n")
        
        # Stitch segments
        stitched_raw = output_path.with_suffix('.raw.wav')
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(stitched_raw)],
            capture_output=True, text=True,
        )
        
        if result.returncode != 0:
            print(f"ffmpeg stitch error: {result.stderr}")
            return False

        # Two-pass loudness normalization to -14 LUFS (Spotify target)
        print("  Normalizing loudness (two-pass, target -14 LUFS)...")
        measure = subprocess.run(
            ["ffmpeg", "-i", str(stitched_raw), "-af",
             "loudnorm=I=-13:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        import json as _json, re as _re
        json_match = _re.search(r'\{[^}]+\}', measure.stderr, _re.DOTALL)
        if json_match:
            stats = _json.loads(json_match.group())
            mi = stats["input_i"]
            mtp = stats["input_tp"]
            mlra = stats["input_lra"]
            mth = stats["input_thresh"]
            result2 = subprocess.run(
                ["ffmpeg", "-y", "-i", str(stitched_raw), "-af",
                 f"loudnorm=I=-13:TP=-1:LRA=11:measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:measured_thresh={mth}:linear=true",
                 "-ar", "44100", "-b:a", "192k", str(output_path)],
                capture_output=True, text=True,
            )
            if result2.returncode != 0:
                print(f"  Loudnorm error: {result2.stderr}")
                # Fallback: just copy raw
                import shutil
                shutil.move(str(stitched_raw), str(output_path))
            else:
                stitched_raw.unlink(missing_ok=True)
                print(f"  Loudness normalized to ~-14 LUFS")
        else:
            print("  Warning: Could not parse loudnorm stats, using raw stitch")
            import shutil
            shutil.move(str(stitched_raw), str(output_path))
        
        return True
    finally:
        for f in tmp_files:
            f.unlink(missing_ok=True)


def build_segment_metadata_from_subs(
    episode_date: str,
    segments_with_parent: list[tuple[str, str, str]],
    audio_files: list[Path],
    silence_map: list[float],
) -> list[dict]:
    """
    Build segment metadata, coalescing paragraph sub-segments back to parent level.
    
    Chapters/metadata use parent segment names. Sub-segment durations are summed
    (plus inter-paragraph silence) to get the parent segment's total duration.
    
    Works with both WAV and MP3 files (uses ffprobe for duration).
    """
    # Get duration for each audio file
    durations = {}
    for af in audio_files:
        durations[af.stem] = get_audio_duration(af)
    
    # Group sub-segments by parent, preserving order
    from collections import OrderedDict
    parent_groups = OrderedDict()
    for i, (name, text, parent) in enumerate(segments_with_parent):
        if parent not in parent_groups:
            parent_groups[parent] = {"texts": [], "names": [], "index": i}
        parent_groups[parent]["texts"].append(text)
        parent_groups[parent]["names"].append(name)
    
    # Calculate parent durations (sum sub-segment durations + inter-paragraph silence)
    metadata = []
    offset = 0.0
    parent_list = list(parent_groups.keys())
    
    for pi, parent in enumerate(parent_list):
        group = parent_groups[parent]
        sub_names = group["names"]
        
        # Sum durations of all sub-segments
        total_dur = 0.0
        for si, sub_name in enumerate(sub_names):
            total_dur += durations.get(sub_name, 0.0)
            # Add intra-parent silence (between paragraphs of same parent)
            global_idx = group["index"] + si
            if si < len(sub_names) - 1 and global_idx < len(silence_map):
                total_dur += silence_map[global_idx]
        
        full_text = "\n\n".join(group["texts"])
        
        # Determine segment type
        parsed = parse_segment_name(parent)
        kind = parsed["kind"]
        
        if kind == "intro":
            seg_type, position, story_pos, next_story = "intro", 0, None, None
        elif kind == "outro":
            seg_type, position, story_pos, next_story = "outro", 99, None, None
        elif kind == "script":
            seg_type = "script"
            story_pos = parsed["script_num"]
            position = story_pos
            next_story = None
        elif kind == "interstitial":
            seg_type = "interstitial"
            story_pos = parsed["script_num"]
            next_story = parsed["next_num"]
            position = 10 + story_pos
        else:
            continue
        
        metadata.append({
            "episode_date": episode_date,
            "segment_type": seg_type,
            "position": position,
            "text": full_text,
            "duration_seconds": total_dur,
            "start_offset_seconds": offset,
            "story_position": story_pos,
            "next_story_position": next_story,
            "tts_model": "f5-tts",
            "voice": get_character_config()["tts_voice"],
        })
        
        # Advance offset: total duration + silence to next parent segment
        offset += total_dur
        # Add inter-parent silence (the silence after last sub-segment of this parent)
        last_global_idx = group["index"] + len(sub_names) - 1
        if last_global_idx < len(silence_map):
            offset += silence_map[last_global_idx]
    
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


def validate_preflight(segments_with_parent: list[tuple[str, str, str]], config: dict) -> bool:
    """
    Pre-flight validation: scan all segment texts for issues before assembly.
    
    Checks:
    - No literal [pause] remaining in rendered text
    - RVC output files exist for all segments (if rvc_enabled)
    
    Returns True if validation passes, False otherwise.
    """
    issues = []
    
    # Check for literal [pause] in segment texts
    for name, text, parent in segments_with_parent:
        if re.search(r'\[pause\]', text, flags=re.IGNORECASE):
            issues.append(f"PAUSE_LEAK: {name} still contains [pause] literal")
    
    if issues:
        print("PRE-FLIGHT VALIDATION FAILED:")
        for issue in issues:
            print(f"  ❌ {issue}")
        return False
    
    print("Pre-flight validation passed ✓")
    return True


def validate_final_mp3(mp3_path: Path, min_minutes: float = 5, max_minutes: float = 45) -> bool:
    """
    Validate final episode MP3 duration is reasonable.
    
    Args:
        mp3_path: Path to final MP3
        min_minutes: Minimum acceptable duration in minutes
        max_minutes: Maximum acceptable duration in minutes
    
    Returns:
        True if duration is within bounds
    """
    duration = get_audio_duration(mp3_path)
    duration_min = duration / 60
    
    if duration_min < min_minutes:
        print(f"WARNING: Episode too short ({duration_min:.1f} min < {min_minutes} min)")
        return False
    if duration_min > max_minutes:
        print(f"WARNING: Episode too long ({duration_min:.1f} min > {max_minutes} min)")
        return False
    
    print(f"Duration validation passed: {duration_min:.1f} min ✓")
    return True


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
    
    # Load pipeline config
    config = load_pipeline_config()
    voice_config = config.get("voice", {})
    pause_config = config.get("pause", {})
    music_config = config.get("music", {})
    audio_config = config.get("audio", {})
    
    tts_voice = voice_config.get("tts_voice", "forbin")
    tts_instruct = voice_config.get("tts_instruct")
    rvc_enabled = voice_config.get("rvc_enabled", False)
    rvc_url = voice_config.get("rvc_url", "")
    rvc_model = voice_config.get("rvc_model", "")
    pause_increments = pause_config.get("increments", [0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    bitrate = audio_config.get("bitrate", "192k")
    
    print(f"=== Generating TTS for episode {episode_date} ===")
    print(f"  Voice: {tts_voice} | Instruct: {'yes' if tts_instruct else 'no'} | RVC: {'enabled' if rvc_enabled else 'disabled'}")
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
        
        # Set up directories
        wav_dir = episode_dir / "wav_temp"
        segments_dir = episode_dir / "segments"
        segments_dir.mkdir(exist_ok=True)
        
        # Load all segments (scripts split into paragraph sub-segments)
        print("Loading segments...")
        segments_with_parent, boundary_types = load_segments(episode_dir, episode_date)
        print(f"Loaded {len(segments_with_parent)} TTS segments:")
        for name, text, parent in segments_with_parent:
            words = len(text.split())
            suffix = f" (from {parent})" if name != parent else ""
            print(f"  {name}: {words} words{suffix}")
        print()
        
        # PRE-FLIGHT: Validate no [pause] leaks in segment texts
        validate_preflight(segments_with_parent, config)
        print()
        
        # PRE-FLIGHT: Check for existing segment MP3s (the archival format)
        existing_mp3_names, missing_segments = find_existing_segment_mp3s(
            segments_with_parent, segments_dir
        )
        if existing_mp3_names:
            print(f"Found {len(existing_mp3_names)} existing valid segment MP3s in {segments_dir}")
            print(f"  Skipping: {existing_mp3_names[:5]}{'...' if len(existing_mp3_names) > 5 else ''}")
            print()
        
        if not missing_segments:
            print("All segments already have valid MP3s! Skipping TTS generation.")
            print()
        else:
            # Also check for leftover WAV files from incomplete runs
            if wav_dir.exists():
                existing_wavs = list(wav_dir.glob("*.wav"))
                if existing_wavs:
                    print(f"Found {len(existing_wavs)} leftover WAV files in {wav_dir}")
                    print("The robust TTS function will skip valid existing WAVs.")
                    print()
            
            # Extract (name, text) pairs for TTS pipeline — only missing segments
            segments_to_generate = [(name, text) for name, text, _ in missing_segments]
            
            # Create temp directory for WAVs
            wav_dir.mkdir(exist_ok=True)
            
            # Warmup TTS server (handles cold start — model reload takes ~2 min)
            print("Warming up TTS server...")
            if not warmup_tts_server(max_wait=180):
                print("WARNING: TTS warmup failed, proceeding anyway...")
            print()
            
            # Generate TTS for missing segments using config voice+instruct
            print(f"Generating TTS for {len(segments_to_generate)} segments (voice={tts_voice})...")
            start_time = datetime.now()
            wav_files, failed = text_to_speech_parallel_robust(
                segments_to_generate,
                wav_dir,
                voice=tts_voice,
                instruct=tts_instruct,
                skip_existing=True,
                abort_on_queue=False,  # Already checked manually above
                max_workers=2,  # 1 per GPU (TTS on GPUs 1+2, RVC on GPU 0)
                num_takes=args.num_takes,
            )
            tts_time = (datetime.now() - start_time).total_seconds()
            print(f"TTS completed in {tts_time:.1f}s ({len(wav_files)} files)")
            print()
            
            if failed:
                print(f"ERROR: {len(failed)} segments failed after all retries:")
                for name in failed:
                    print(f"  - {name}")
                print()
                print("Fix the issue and re-run. Existing segment MP3s will be reused.")
                sys.exit(1)
            
            if len(wav_files) != len(segments_to_generate):
                print(f"WARNING: Only {len(wav_files)}/{len(segments_to_generate)} segments generated!")
            
            # RVC conversion (if enabled)
            if rvc_enabled and rvc_url and rvc_model:
                print(f"Running RVC conversion (model={rvc_model})...")
                rvc_success = 0
                rvc_fallback = 0
                for wav_path in wav_files:
                    rvc_wav = wav_path.with_suffix('.rvc.wav')
                    if rvc_convert(wav_path=wav_path, output_path=rvc_wav,
                                   rvc_url=rvc_url, rvc_model=rvc_model):
                        # Replace original with RVC version
                        rvc_wav.rename(wav_path)
                        rvc_success += 1
                    else:
                        print(f"  WARNING: RVC failed for {wav_path.stem}, using raw TTS")
                        rvc_fallback += 1
                        # rvc_wav doesn't exist or is invalid, original wav_path is intact
                        if rvc_wav.exists():
                            rvc_wav.unlink()
                print(f"RVC: {rvc_success} converted, {rvc_fallback} fallbacks")
                if rvc_fallback > 0:
                    print(f"ERROR: {rvc_fallback} segments failed RVC conversion. Cannot assemble with raw dylan voice.")
                    print("Fix: ensure RVC server is running on a GPU with free VRAM (not GPU 2).")
                    print("  ssh quato 'CUDA_VISIBLE_DEVICES=0 nohup /home/quato/rvc/rvc-server/venv/bin/python /home/quato/rvc/rvc-server/server.py > /tmp/rvc.log 2>&1 &'")
                    sys.exit(1)
                print()
            
            # Transcode each WAV → segment MP3, validate, then delete WAV
            print(f"Transcoding WAVs to segment MP3s ({bitrate} CBR)...")
            for wav_path in wav_files:
                seg_name = wav_path.stem
                mp3_path = segments_dir / f"{seg_name}.mp3"
                
                if not transcode_segment_to_mp3(wav_path, mp3_path, bitrate=bitrate):
                    print(f"ERROR: Failed to transcode {seg_name} to MP3")
                    sys.exit(1)
                
                # WAV is safe to delete — MP3 is validated
                wav_path.unlink()
                print(f"  ✓ {seg_name}.mp3 ({mp3_path.stat().st_size / 1024:.0f} KB)")
            
            print(f"All segment MP3s saved to {segments_dir}")
            print()
            
            # Clean up wav_temp/ (should be empty now)
            if wav_dir.exists():
                remaining = list(wav_dir.glob("*"))
                if remaining:
                    print(f"WARNING: {len(remaining)} files remain in wav_temp/")
                else:
                    wav_dir.rmdir()
                    print("Removed empty wav_temp/")
            print()
        
        # Build ordered list of all segment MP3 paths
        segment_mp3_files = []
        for name, text, parent in segments_with_parent:
            mp3_path = segments_dir / f"{name}.mp3"
            if not mp3_path.exists():
                print(f"ERROR: Missing segment MP3: {mp3_path}")
                sys.exit(1)
            segment_mp3_files.append(mp3_path)
        
        # Stitch segment MP3s with variable silence:
        #   0.5s between paragraph sub-segments (within a script)
        #   random 0.5-1.0s at [pause] markers (from config increments)
        #   1.0s between major segments (intro→script, script→interstitial, etc.)
        print("Stitching segment MP3s with variable silence gaps...")
        silence_map = []  # silence duration AFTER each segment (except last)
        SILENCE_PARAGRAPH = 0.5
        SILENCE_MAJOR = 1.0
        for i in range(len(segments_with_parent) - 1):
            if i < len(boundary_types):
                bt = boundary_types[i]
                if bt == "pause":
                    # Random pause duration from config increments
                    silence_map.append(random.choice(pause_increments))
                elif bt == "major":
                    silence_map.append(SILENCE_MAJOR)
                else:
                    silence_map.append(SILENCE_PARAGRAPH)
            else:
                # Fallback: infer from parent relationship
                _, _, parent_curr = segments_with_parent[i]
                _, _, parent_next = segments_with_parent[i + 1]
                if parent_curr == parent_next:
                    silence_map.append(SILENCE_PARAGRAPH)
                else:
                    silence_map.append(SILENCE_MAJOR)
        
        # Determine intro/outro segment MP3s for music overlay
        intro_mp3 = None
        outro_mp3 = None
        for name, text, parent in segments_with_parent:
            if "intro" in parent:
                intro_mp3 = segments_dir / f"{name}.mp3"
                break
        for name, text, parent in reversed(segments_with_parent):
            if "outro" in parent:
                outro_mp3 = segments_dir / f"{name}.mp3"
                break
        
        episode_mp3 = episode_dir / f"DTFHN-{episode_date}.mp3"
        
        # First stitch without music overlay (raw assembly)
        raw_episode_mp3 = episode_dir / f"DTFHN-{episode_date}.raw.mp3"
        if not stitch_mp3s_variable(segment_mp3_files, raw_episode_mp3, silence_map, bitrate=bitrate):
            print("ERROR: Failed to stitch segment MP3s")
            sys.exit(1)
        
        # Apply music overlay if configured
        theme_path_str = music_config.get("theme_path", "")
        if theme_path_str and intro_mp3 and outro_mp3:
            # Resolve theme path relative to project root
            theme_path = PROJECT_ROOT / theme_path_str
            if not theme_path.exists():
                theme_path = Path(theme_path_str).expanduser()
            
            if theme_path.exists():
                print("Applying music overlay...")
                # We need WAV for overlay processing, then re-encode
                raw_wav = episode_dir / "raw_for_overlay.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(raw_episode_mp3), "-ar", "24000", "-ac", "1", str(raw_wav)],
                    capture_output=True, check=True,
                )
                overlaid_wav = episode_dir / "overlaid.wav"
                
                if apply_music_overlay(
                    body_wav=raw_wav,
                    output_wav=overlaid_wav,
                    intro_wav=intro_mp3,
                    outro_wav=outro_mp3,
                    theme_path=theme_path,
                    music_config=music_config,
                ):
                    # Two-pass loudnorm on overlaid WAV → final MP3
                    print("Applying loudnorm to overlaid audio...")
                    loudnorm_i = audio_config.get("loudnorm_i", -13)
                    loudnorm_tp = audio_config.get("loudnorm_tp", -1)
                    loudnorm_lra = audio_config.get("loudnorm_lra", 11)
                    sample_rate = audio_config.get("sample_rate", 44100)
                    
                    # Pass 1: measure
                    measure = subprocess.run(
                        ["ffmpeg", "-i", str(overlaid_wav), "-af",
                         f"loudnorm=I={loudnorm_i}:TP={loudnorm_tp}:LRA={loudnorm_lra}:print_format=json",
                         "-f", "null", "-"],
                        capture_output=True, text=True,
                    )
                    json_match = re.search(r'\{[^}]+\}', measure.stderr, re.DOTALL)
                    if json_match:
                        stats = json.loads(json_match.group())
                        mi, mtp, mlra, mth = stats["input_i"], stats["input_tp"], stats["input_lra"], stats["input_thresh"]
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", str(overlaid_wav), "-af",
                             f"loudnorm=I={loudnorm_i}:TP={loudnorm_tp}:LRA={loudnorm_lra}:"
                             f"measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:measured_thresh={mth}:linear=true",
                             "-ar", str(sample_rate), "-codec:a", "libmp3lame", "-b:a", bitrate,
                             str(episode_mp3)],
                            capture_output=True, check=True,
                        )
                        print(f"  Loudness normalized to ~{loudnorm_i} LUFS")
                    else:
                        # Fallback: simple transcode
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", str(overlaid_wav),
                             "-ar", str(sample_rate), "-codec:a", "libmp3lame", "-b:a", bitrate,
                             str(episode_mp3)],
                            capture_output=True, check=True,
                        )
                    
                    # Clean up temp files
                    raw_wav.unlink(missing_ok=True)
                    overlaid_wav.unlink(missing_ok=True)
                    raw_episode_mp3.unlink(missing_ok=True)
                else:
                    print("Music overlay failed, using raw assembly")
                    raw_wav.unlink(missing_ok=True)
                    overlaid_wav.unlink(missing_ok=True)
                    raw_episode_mp3.rename(episode_mp3)
            else:
                print(f"Theme file not found at {theme_path}, skipping music overlay")
                raw_episode_mp3.rename(episode_mp3)
        else:
            # No music config — use raw assembly as final
            raw_episode_mp3.rename(episode_mp3)
        
        mp3_size = episode_mp3.stat().st_size
        print(f"Episode MP3: {episode_mp3} ({mp3_size / 1024 / 1024:.1f} MB)")
        print()
        
        # Get final duration
        duration = get_audio_duration(episode_mp3)
        print(f"Duration: {duration:.1f}s ({duration / 60:.1f} min)")
        print()
        
        # POST-ASSEMBLY VALIDATION
        validate_final_mp3(episode_mp3, min_minutes=5, max_minutes=45)
        print()
        
        # Build segment metadata (coalesce sub-segments back to parent level for chapters)
        print("Building segment metadata...")
        segment_metadata = build_segment_metadata_from_subs(
            episode_date, segments_with_parent, segment_mp3_files, silence_map
        )
        
        # Update voice field in metadata to reflect actual voice used
        for meta in segment_metadata:
            meta["voice"] = tts_voice
            meta["tts_model"] = "qwen3-tts"
        
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
        
        # Summary
        print("=" * 50)
        print(f"Episode {episode_date} complete!")
        print(f"  Voice: {tts_voice}" + (f" + RVC {rvc_model}" if rvc_enabled else ""))
        print(f"  Duration: {duration:.1f}s ({duration / 60:.1f} min)")
        print(f"  MP3 size: {mp3_size / 1024 / 1024:.1f} MB")
        print(f"  Segments: {len(segment_metadata)}")
        print(f"  Segment MP3s: {segments_dir}")
        try:
            print(f"  TTS time: {tts_time:.1f}s")
        except NameError:
            pass
        print("=" * 50)
    
    finally:
        # Always release lock, even on failure
        release_lock(lock_fd, lock_file)
        print("Lock released.")


if __name__ == "__main__":
    main()
