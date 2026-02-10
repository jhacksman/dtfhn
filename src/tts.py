"""TTS module for DTFHN podcast.

Interfaces with quato TTS server. Server has 3 GPUs that process
requests in parallel. Voice selection is driven by CHARACTER env var.

Includes runaway detection: if rendered audio is >= 2x expected duration
(based on word count), the segment is automatically re-rendered.

Segment granularity: Scripts are split at [pause] markers AND paragraph
breaks. Each chunk becomes a separate TTS clip. 1 second silence is
inserted between clips during merge.
"""
import os
import re
import struct
import subprocess
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# TTS server config (quato)
TTS_URL = "http://192.168.0.134:7849/speak"
TTS_STATUS_URL = "http://192.168.0.134:7849/status"
TTS_TIMEOUT = 1200  # 20 min — Qwen3-TTS is slow (~1.7x realtime), longer segments need more time

# Character → TTS voice mapping
CHARACTER_TTS_VOICES = {
    "forbin": "forbin",
    "carlin": "george_carlin",
    "gc": "george_carlin",
    "jack": "noel",
}


def get_tts_voice() -> str:
    """Get TTS voice name based on CHARACTER env var."""
    char = os.environ.get("CHARACTER", "forbin").lower()
    return CHARACTER_TTS_VOICES.get(char, "forbin")


# Default voice (evaluated at import time, but functions use get_tts_voice() for dynamic lookup)
TTS_VOICE = get_tts_voice()

# Silence gap between TTS clips (seconds)
CLIP_SILENCE_GAP = 1.0


def split_script_into_chunks(text: str) -> list[str]:
    """
    Split script text into TTS chunks at [pause] markers and paragraph breaks.
    
    Each chunk becomes a separate TTS job. Chunks are merged with 1s silence
    gaps to create natural-sounding audio.
    
    Split points:
    - [pause] markers (explicit pause points from em-dashes)
    - Double newlines (paragraph breaks)
    
    Args:
        text: Script text with [pause] markers
    
    Returns:
        List of non-empty text chunks, each becoming a TTS clip
    """
    # First, normalize the text
    text = text.strip()
    
    # Replace [pause] with a unique delimiter
    DELIM = "<<<SPLIT>>>"
    text = re.sub(r'\[pause\]', DELIM, text, flags=re.IGNORECASE)
    
    # Replace double newlines (paragraph breaks) with delimiter
    text = re.sub(r'\n\s*\n', DELIM, text)
    
    # Split by delimiter
    chunks = text.split(DELIM)
    
    # Clean up: strip whitespace, filter empty chunks
    chunks = [c.strip() for c in chunks]
    chunks = [c for c in chunks if c]
    
    return chunks


def merge_wavs_with_silence(
    wav_files: list[Path],
    output_path: Path,
    silence_seconds: float = CLIP_SILENCE_GAP,
) -> bool:
    """
    Merge WAV files with silence gaps between each clip.
    
    Uses ffmpeg to concatenate WAVs with silence inserts.
    
    Args:
        wav_files: List of WAV file paths in order
        output_path: Output WAV path
        silence_seconds: Seconds of silence between clips (default 1.0)
    
    Returns:
        True on success, False on failure
    """
    if not wav_files:
        return False
    
    if len(wav_files) == 1:
        # Single file, just copy
        import shutil
        shutil.copy(wav_files[0], output_path)
        return True
    
    try:
        # Build ffmpeg filter for concatenation with silence
        # Create a concat filter that inserts silence between each clip
        
        # First, create a silent audio clip
        # We'll use anullsrc for silence generation
        
        # Build complex filter:
        # - Input each WAV
        # - Create silence segment
        # - Interleave: wav1, silence, wav2, silence, ..., wavN
        
        inputs = []
        filter_parts = []
        
        for i, wav in enumerate(wav_files):
            inputs.extend(['-i', str(wav)])
        
        # Number of inputs
        n = len(wav_files)
        
        # Build filter graph
        # Each input becomes [0:a], [1:a], etc.
        # We need to insert silence between them
        
        # Generate silence of specified duration
        # anullsrc generates silence, atrim trims it to duration
        silence_filter = f"anullsrc=r=24000:cl=mono,atrim=0:{silence_seconds}[silence]"
        
        # Build the concat sequence: file0, silence, file1, silence, ..., fileN
        concat_inputs = []
        for i in range(n):
            concat_inputs.append(f"[{i}:a]")
            if i < n - 1:  # No silence after last file
                concat_inputs.append("[silence]")
        
        # Total streams: n files + (n-1) silences
        total_streams = n + (n - 1)
        
        # Problem: we only have one [silence] but need to use it n-1 times
        # Solution: Use asplit to duplicate the silence stream
        
        if n > 1:
            # Generate n-1 copies of silence
            silence_copies = ",".join(f"[s{i}]" for i in range(n - 1))
            silence_gen = f"anullsrc=r=24000:cl=mono,atrim=0:{silence_seconds},asplit={n-1}{silence_copies}"
            
            # Now build concat with the duplicated silences
            concat_inputs = []
            for i in range(n):
                concat_inputs.append(f"[{i}:a]")
                if i < n - 1:
                    concat_inputs.append(f"[s{i}]")
            
            concat_str = "".join(concat_inputs)
            full_filter = f"{silence_gen};{concat_str}concat=n={total_streams}:v=0:a=1[out]"
        else:
            full_filter = "[0:a]acopy[out]"
        
        cmd = [
            'ffmpeg', '-y',
            *inputs,
            '-filter_complex', full_filter,
            '-map', '[out]',
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            print(f"ffmpeg merge failed: {result.stderr}")
            return False
        
        return True
        
    except Exception as e:
        print(f"Error merging WAVs: {e}")
        return False

# Robust TTS pipeline configuration
POLL_INTERVAL_SECONDS = 5  # How often to poll /status
PROGRESS_TIMEOUT_SECONDS = 300  # 5 min with no progress = stall
MAX_RETRY_ATTEMPTS = 5  # Max times to retry failed segments
MIN_WAV_SIZE_BYTES = 1000  # Minimum valid WAV file size
RETRY_BACKOFF_SCHEDULE = [10, 20, 40, 80, 120]  # seconds per retry round
MASS_FAILURE_THRESHOLD = 3  # re-warmup if more than this many fail in a round

TTS_BASE_URL = "http://192.168.0.134:7849"


def warmup_tts_server(max_wait: int = 180) -> bool:
    """Send a health check + test TTS request to wake the server from cold start.
    
    The TTS server unloads models after 1hr idle. First request after idle
    takes ~2 min for model reload. This function ensures the model is loaded
    before we fire off parallel TTS jobs.
    
    Retries every 10s for up to max_wait seconds.
    """
    import json as _json
    start = time.time()
    attempt = 0
    while time.time() - start < max_wait:
        attempt += 1
        try:
            # Health check first
            resp = requests.get(f"{TTS_BASE_URL}/", timeout=15)
            if resp.status_code == 200:
                # Server is up — send a tiny TTS request to force model load
                try:
                    test_resp = requests.post(
                        TTS_URL,
                        json={"text": "test", "voice": TTS_VOICE, "timeout": 0},
                        timeout=300,
                    )
                    if test_resp.status_code == 200 and len(test_resp.content) > 100:
                        print(f"  TTS warmup OK (attempt {attempt}, {time.time()-start:.0f}s)")
                        return True
                    else:
                        print(f"  TTS warmup: unexpected response {test_resp.status_code}, retrying...")
                except Exception as e:
                    print(f"  TTS warmup request failed (attempt {attempt}): {e}")
        except Exception as e:
            print(f"  TTS server not ready (attempt {attempt}): {e}")
        time.sleep(10)
    
    print(f"  TTS warmup FAILED after {max_wait}s")
    return False


def prepare_text_for_tts(text: str) -> str:
    """
    Prepare text for TTS: pronunciation fixes and breathing pauses.
    
    Applies pronunciation substitutions for words the TTS model
    mispronounces, then adds em-dashes at segment boundaries for
    natural breathing room.
    
    Args:
        text: Raw segment text
    
    Returns:
        Text with pronunciation fixes and em-dashes
    """
    text = text.strip()
    
    # Pronunciation fixes — words the TTS model mispronounces
    # Add new entries as discovered. Format: (pattern, replacement)
    # Case-sensitive replacements first, then case-insensitive
    import re
    
    # Extensions that have specific spoken pronunciations
    SPOKEN_EXTENSIONS = {
        'py': 'pie',
        'yml': 'yeahmel',
        'yaml': 'yeahmel',
        'json': 'jason',
        'txt': 'text',
        'toml': 'tomul',
        'wav': 'wave',
    }
    
    # Extensions that sound fine spoken as-is (not spelled out)
    NATURAL_EXTENSIONS = {
        'zip', 'log', 'bin', 'bat', 'doc', 'go', 'gif',
    }
    
    # Generic file extension handler: .xyz → "dot X Y Z" (spells out up to 5 chars)
    # Unless the extension sounds natural when spoken
    def _spell_extension(match):
        ext = match.group(1)
        low = ext.lower()
        if low in SPOKEN_EXTENSIONS:
            return f' dot {SPOKEN_EXTENSIONS[low]}'
        if low in NATURAL_EXTENSIONS:
            return f' dot {ext}'
        return ' dot ' + ' '.join(ext.upper())
    
    text = re.sub(r'\.([a-zA-Z]{1,5})\b', _spell_extension, text)
    
    # Word pronunciation fixes
    PRONUNCIATION_FIXES = [
        (r'\bGrok\b', 'Grock'),
        (r'\bREADME\b', 'read me'),
        (r'\bReadme\b', 'read me'),
        (r'\breadme\b', 'read me'),
    ]
    
    for pattern, replacement in PRONUNCIATION_FIXES:
        text = re.sub(pattern, replacement, text)
    
    # Em-dash breathing pauses
    if not text.startswith('—'):
        text = '— ' + text
    if not text.endswith('—'):
        text = text + ' —'
    return text


def validate_wav_bytes(data: bytes) -> tuple[bool, str]:
    """
    Validate WAV file bytes.
    
    Args:
        data: Raw bytes from TTS response
    
    Returns:
        (is_valid, error_message)
    """
    if not data:
        return (False, "empty response body")
    
    if len(data) < MIN_WAV_SIZE_BYTES:
        return (False, f"too small ({len(data)} bytes < {MIN_WAV_SIZE_BYTES})")
    
    # WAV files must start with "RIFF" magic bytes
    if data[:4] != b'RIFF':
        header_hex = data[:4].hex() if len(data) >= 4 else "N/A"
        return (False, f"invalid WAV header (got {header_hex!r}, expected 'RIFF')")
    
    return (True, "")


def get_wav_duration_from_bytes(data: bytes) -> float:
    """
    Calculate WAV duration from raw bytes without writing to disk.
    
    Parses WAV header to extract sample rate and data size.
    
    Args:
        data: WAV file bytes
    
    Returns:
        Duration in seconds, or 0.0 on parse error
    """
    try:
        if len(data) < 44:
            return 0.0
        
        # Find the 'fmt ' chunk (starts after RIFF header at offset 12)
        fmt_offset = data.find(b'fmt ')
        if fmt_offset == -1:
            return 0.0
        
        # Parse fmt chunk: skip chunk id (4) + chunk size (4)
        # Audio format (2), num channels (2), sample rate (4), byte rate (4), block align (2), bits per sample (2)
        fmt_data = data[fmt_offset + 8:]
        if len(fmt_data) < 16:
            return 0.0
        
        num_channels = struct.unpack('<H', fmt_data[2:4])[0]
        sample_rate = struct.unpack('<I', fmt_data[4:8])[0]
        bits_per_sample = struct.unpack('<H', fmt_data[14:16])[0]
        
        if sample_rate == 0 or bits_per_sample == 0 or num_channels == 0:
            return 0.0
        
        # Find the 'data' chunk
        data_offset = data.find(b'data')
        if data_offset == -1:
            return 0.0
        
        # Data chunk size is 4 bytes after 'data'
        data_size = struct.unpack('<I', data[data_offset + 4:data_offset + 8])[0]
        
        # Calculate duration: data_size / (sample_rate * num_channels * bytes_per_sample)
        bytes_per_sample = bits_per_sample // 8
        duration = data_size / (sample_rate * num_channels * bytes_per_sample)
        return duration
    except Exception:
        return 0.0


def get_wav_duration_from_file(wav_path: Path) -> float:
    """Get duration of WAV file using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(wav_path)],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def estimate_expected_duration(text: str) -> float:
    """
    Estimate expected TTS duration based on word count.
    
    Uses ~150 words per minute (2.5 words/second) as baseline.
    Returns a conservative estimate (actual TTS is often slightly slower).
    
    Args:
        text: Text to be spoken
    
    Returns:
        Expected duration in seconds
    """
    word_count = len(text.split())
    # 150 wpm = 2.5 words/second. Use 2.3 to be conservative.
    return word_count / 2.3


# Runaway detection configuration
RUNAWAY_THRESHOLD_MULTIPLIER = 2.0  # If duration >= 2x expected, it's a runaway
MAX_RUNAWAY_RETRIES = 2  # Max times to retry a runaway segment


def text_to_speech(text: str, output_path: Path, voice: str = TTS_VOICE) -> tuple[bool, str]:
    """
    Generate WAV from text via quato TTS with runaway detection.
    
    If the rendered audio duration is >= 2x the expected duration (based on
    word count), the segment is considered a runaway and automatically retried.
    
    Args:
        text: Text to convert to speech
        output_path: Where to save the WAV file
        voice: Voice profile to use (default from CHARACTER env)
    
    Returns:
        (success, error_message) - error_message is empty on success
    """
    expected_duration = estimate_expected_duration(text)
    
    for attempt in range(MAX_RUNAWAY_RETRIES + 1):
        try:
            # Add em-dashes for natural breathing pauses
            prepared_text = prepare_text_for_tts(text)
            
            response = requests.post(
                TTS_URL,
                headers={"Content-Type": "application/json"},
                json={"text": prepared_text, "voice": voice, "timeout": 600},
                timeout=(10, TTS_TIMEOUT),  # 10s connect, TTS_TIMEOUT read — detect dead server fast
            )
            
            # Track job ID from response header
            job_id = response.headers.get("X-Job-Id")
            
            # Check HTTP status
            if response.status_code != 200:
                return (False, f"HTTP {response.status_code} (job={job_id}): {response.text[:100]}")
            
            # Validate WAV content
            is_valid, error = validate_wav_bytes(response.content)
            if not is_valid:
                return (False, error)
            
            # RUNAWAY DETECTION: Check duration before writing
            actual_duration = get_wav_duration_from_bytes(response.content)
            if actual_duration > 0 and expected_duration > 0:
                ratio = actual_duration / expected_duration
                if ratio >= RUNAWAY_THRESHOLD_MULTIPLIER:
                    # Runaway detected!
                    if attempt < MAX_RUNAWAY_RETRIES:
                        print(f"    ⚠️ RUNAWAY detected: {actual_duration:.1f}s actual vs {expected_duration:.1f}s expected ({ratio:.1f}x) — retrying...")
                        time.sleep(2)  # Brief pause before retry
                        continue
                    else:
                        return (False, f"runaway after {MAX_RUNAWAY_RETRIES} retries: {actual_duration:.1f}s vs {expected_duration:.1f}s expected ({ratio:.1f}x)")
            
            # Write validated WAV
            output_path.write_bytes(response.content)
            
            # Log duration info for non-runaway segments
            if actual_duration > 0 and expected_duration > 0:
                ratio = actual_duration / expected_duration
                if ratio > 1.5:  # Warn if >1.5x but <2x
                    print(f"    ℹ️ Slow render: {actual_duration:.1f}s actual vs {expected_duration:.1f}s expected ({ratio:.1f}x)")
            
            return (True, "")
            
        except requests.exceptions.Timeout:
            return (False, "request timeout")
        except requests.exceptions.ConnectionError as e:
            return (False, f"connection error: {e}")
        except Exception as e:
            return (False, f"unexpected error: {e}")
    
    # Should never reach here, but just in case
    return (False, "max retries exhausted")


def _tts_worker(args: tuple[str, str, Path, str]) -> tuple[str, Path | None, str]:
    """
    Worker function for parallel TTS.
    
    Args:
        args: (name, text, output_path, voice)
    
    Returns:
        (name, output_path, error) - output_path is None and error is set on failure
    """
    name, text, output_path, voice = args
    success, error = text_to_speech(text, output_path, voice)
    return (name, output_path if success else None, error)


def text_to_speech_parallel(
    segments: list[tuple[str, str]],
    output_dir: Path,
    voice: str = TTS_VOICE,
    max_workers: int = 1,
) -> tuple[list[Path], dict[str, str]]:
    """
    Generate all WAVs in parallel.
    
    Fires all TTS requests at once. quato has 3 GPUs that process
    requests in parallel using least-queued dispatch — each new request
    is routed to the GPU with the shortest queue (not round-robin).
    Sending everything immediately maximizes throughput.
    
    Args:
        segments: list of (name, text) tuples
        output_dir: where to save WAV files
        voice: voice profile to use
        max_workers: max concurrent requests (default 25 for full episodes)
    
    Returns:
        (wav_files, failures)
        - wav_files: list of successfully created WAV paths, in original segment order
        - failures: dict of {segment_name: error_message} for failed segments
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build work items
    work_items = [
        (name, text, output_dir / f"{name}.wav", voice)
        for name, text in segments
    ]
    
    # Track results by name for ordering
    results: dict[str, Path | None] = {}
    failures: dict[str, str] = {}
    
    print(f"Starting parallel TTS for {len(segments)} segments...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_tts_worker, item): item[0] for item in work_items}
        
        for future in as_completed(futures):
            name, path, error = future.result()
            results[name] = path
            if path:
                print(f"  ✓ {name} ({path.stat().st_size:,} bytes)")
            else:
                failures[name] = error
                print(f"  ✗ {name} FAILED: {error}")
    
    # Return paths in original order, excluding failures
    wav_files = []
    for name, _ in segments:
        if results.get(name):
            wav_files.append(results[name])
    
    print(f"Generated {len(wav_files)}/{len(segments)} WAV files")
    if failures:
        print(f"Failed segments: {list(failures.keys())}")
    
    return wav_files, failures


def check_tts_status() -> dict:
    """
    Check quato TTS server status.
    
    Returns:
        Status dict with GPU info:
        {
            "gpus": [
                {"gpu": 0, "active": "text...", "queued": 2},
                ...
            ],
            "total_active": 2,
            "total_queued": 5,
            "completed": 47
        }
        
        Or {"error": "message"} on failure.
    """
    try:
        response = requests.get(TTS_STATUS_URL, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def check_queue_empty() -> tuple[bool, int, int]:
    """
    Check if TTS server queue is empty.
    
    Returns:
        (is_empty, active_count, queued_count)
    """
    status = check_tts_status()
    if "error" in status:
        return (False, 0, 0)  # Assume not empty on error
    
    active = status.get("total_active", 0)
    queued = status.get("total_queued", 0)
    return (active == 0 and queued == 0, active, queued)


def validate_existing_wav(wav_path: Path) -> bool:
    """Check if an existing WAV file is valid (RIFF header + minimum size)."""
    if not wav_path.exists():
        return False
    if wav_path.stat().st_size < MIN_WAV_SIZE_BYTES:
        return False
    # Check RIFF header
    with open(wav_path, 'rb') as f:
        header = f.read(4)
    return header == b'RIFF'


def find_existing_wavs(
    segments: list[tuple[str, str]],
    output_dir: Path,
) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Identify which segments already have valid WAV files.
    
    Validates both file size and RIFF header.
    
    Args:
        segments: list of (name, text) tuples
        output_dir: directory to check for existing files
    
    Returns:
        (existing_names, missing_segments)
        - existing_names: segment names with valid WAVs
        - missing_segments: segments that need generation
    """
    existing = []
    missing = []
    
    for name, text in segments:
        wav_path = output_dir / f"{name}.wav"
        if validate_existing_wav(wav_path):
            existing.append(name)
        else:
            missing.append((name, text))
    
    return existing, missing


def wait_for_queue_drain(
    expected_count: int,
    timeout_on_stall: int = PROGRESS_TIMEOUT_SECONDS,
    poll_interval: int = POLL_INTERVAL_SECONDS,
) -> tuple[bool, int]:
    """
    Poll /status until queue drains or progress stalls.
    
    Args:
        expected_count: number of jobs we submitted
        timeout_on_stall: seconds of no progress before giving up
        poll_interval: seconds between status checks
    
    Returns:
        (success, completed_count)
    """
    last_completed = 0
    last_progress_time = time.time()
    
    while True:
        status = check_tts_status()
        if "error" in status:
            print(f"  Warning: status check failed: {status['error']}")
            time.sleep(poll_interval)
            continue
        
        completed = status.get("completed", 0)
        active = status.get("total_active", 0)
        queued = status.get("total_queued", 0)
        
        print(f"  Progress: {completed} completed, {active} active, {queued} queued")
        
        # Check if done
        if active == 0 and queued == 0:
            return (True, completed)
        
        # Track progress
        if completed > last_completed:
            last_completed = completed
            last_progress_time = time.time()
        
        # Check for stall
        stall_duration = time.time() - last_progress_time
        if stall_duration > timeout_on_stall:
            print(f"  STALL: No progress for {stall_duration:.0f}s")
            return (False, completed)
        
        time.sleep(poll_interval)


def text_to_speech_parallel_robust(
    segments: list[tuple[str, str]],
    output_dir: Path,
    voice: str = TTS_VOICE,
    max_workers: int = 1,
    skip_existing: bool = True,
    abort_on_queue: bool = True,
    retry_backoff: float = 2.0,
) -> tuple[list[Path], list[str]]:
    """
    Robust parallel TTS with pre-flight checks, WAV validation, and retry with backoff.
    
    Features:
    - Pre-flight queue status check
    - Validates existing WAV files (size + RIFF header)
    - HTTP 200, non-empty body, WAV header validation for each response
    - Tracks successes/failures by segment name
    - Retries failed segments with exponential backoff
    - Only proceeds when all segments confirmed
    
    Args:
        segments: list of (name, text) tuples
        output_dir: where to save WAV files
        voice: voice profile to use
        max_workers: max concurrent requests
        skip_existing: skip segments with existing valid WAVs
        abort_on_queue: abort if queue already has items
        retry_backoff: base seconds to wait between retries (exponential)
    
    Returns:
        (successful_paths, failed_names)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # PRE-FLIGHT: Check queue status
    if abort_on_queue:
        is_empty, active, queued = check_queue_empty()
        if not is_empty:
            raise RuntimeError(
                f"TTS queue not empty ({active} active, {queued} queued). "
                "Clear queue or pass abort_on_queue=False to continue."
            )
    
    # PRE-FLIGHT: Find existing valid WAVs (with proper header validation)
    existing_names = []
    to_generate = []
    
    for name, text in segments:
        wav_path = output_dir / f"{name}.wav"
        if skip_existing and validate_existing_wav(wav_path):
            existing_names.append(name)
        else:
            to_generate.append((name, text))
    
    if existing_names:
        print(f"Skipping {len(existing_names)} existing valid WAVs: {existing_names[:5]}{'...' if len(existing_names) > 5 else ''}")
    
    if not to_generate:
        print("All segments already exist with valid WAV files!")
        return [output_dir / f"{name}.wav" for name, _ in segments], []
    
    print(f"Generating {len(to_generate)} segments...")
    
    # Track all failure reasons for final report
    all_failures: dict[str, str] = {}
    
    # SUBMIT & RETRY: Fire all requests with exponential backoff
    for attempt in range(MAX_RETRY_ATTEMPTS):
        if attempt > 0:
            backoff_time = RETRY_BACKOFF_SCHEDULE[min(attempt - 1, len(RETRY_BACKOFF_SCHEDULE) - 1)]
            print(f"Retry round {attempt + 1}/{MAX_RETRY_ATTEMPTS} after {backoff_time}s backoff...")
            time.sleep(backoff_time)
            
            # Re-warmup if many failures (server might be restarting/cold)
            if len(to_generate) > MASS_FAILURE_THRESHOLD:
                print(f"  {len(to_generate)} failures — re-warming TTS server...")
                warmup_tts_server(max_wait=120)
        
        # Generate missing segments
        wav_files, failures = text_to_speech_parallel(to_generate, output_dir, voice, max_workers)
        
        # Update failure tracking
        all_failures.update(failures)
        
        # Check what succeeded
        succeeded = {p.stem for p in wav_files}
        failed_names = [name for name, _ in to_generate if name not in succeeded]
        
        if not failed_names:
            print(f"All {len(to_generate)} segments generated successfully!")
            break
        
        # Check if files were created despite timeout (race condition recovery)
        # Use proper WAV validation
        still_missing = []
        for name in failed_names:
            wav_path = output_dir / f"{name}.wav"
            if validate_existing_wav(wav_path):
                print(f"  Recovered {name} (valid WAV created after initial check)")
                del all_failures[name]  # Remove from failures
            else:
                still_missing.append(name)
        
        if not still_missing:
            failed_names = []
            print("All segments recovered!")
            break
        
        # Update to_generate for retry
        to_generate = [(n, t) for n, t in to_generate if n in still_missing]
        failed_names = still_missing
        print(f"  {len(still_missing)} segments still need retry: {still_missing}")
    
    # Build complete list including pre-existing files (with validation)
    all_paths = []
    final_failed = []
    
    for name, _ in segments:
        wav_path = output_dir / f"{name}.wav"
        if validate_existing_wav(wav_path):
            all_paths.append(wav_path)
        else:
            final_failed.append(name)
    
    # Summary
    print(f"\nTTS Summary:")
    print(f"  Total segments: {len(segments)}")
    print(f"  Successful: {len(all_paths)}")
    print(f"  Failed: {len(final_failed)}")
    
    if final_failed:
        print(f"\nFailed segments with reasons:")
        for name in final_failed:
            reason = all_failures.get(name, "unknown")
            print(f"  - {name}: {reason}")
    
    return all_paths, final_failed


def render_segment_chunked(
    segment_name: str,
    text: str,
    output_dir: Path,
    voice: str = None,
) -> tuple[Path | None, str]:
    """
    Render a segment by splitting into chunks at [pause] markers and paragraphs.
    
    Each chunk becomes a separate TTS clip. Clips are merged with 1s silence
    between each to create natural-sounding audio.
    
    Args:
        segment_name: Base name for the segment (e.g., "01_-_script_01")
        text: Script text with [pause] markers
        output_dir: Output directory for WAV files
        voice: TTS voice to use (default from CHARACTER env)
    
    Returns:
        (output_path, error) - output_path is None on failure
    """
    voice = voice or get_tts_voice()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Split into chunks
    chunks = split_script_into_chunks(text)
    
    if not chunks:
        return (None, "no text chunks after split")
    
    print(f"  {segment_name}: {len(chunks)} chunks")
    
    # Create temp dir for chunk WAVs
    chunk_dir = output_dir / f".{segment_name}_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    
    # Build chunk segments
    chunk_segments = [
        (f"{segment_name}_c{i:03d}", chunk)
        for i, chunk in enumerate(chunks)
    ]
    
    # Render all chunks in parallel
    chunk_wavs, failures = text_to_speech_parallel(
        chunk_segments, chunk_dir, voice, max_workers=len(chunks)
    )
    
    if failures:
        # Clean up
        import shutil
        shutil.rmtree(chunk_dir, ignore_errors=True)
        return (None, f"chunk failures: {list(failures.keys())}")
    
    # Merge chunks with silence gaps
    output_path = output_dir / f"{segment_name}.wav"
    
    # Sort chunk WAVs by name to maintain order
    chunk_wavs_sorted = sorted(chunk_wavs, key=lambda p: p.name)
    
    success = merge_wavs_with_silence(chunk_wavs_sorted, output_path, CLIP_SILENCE_GAP)
    
    # Clean up chunk dir
    import shutil
    shutil.rmtree(chunk_dir, ignore_errors=True)
    
    if success:
        return (output_path, "")
    else:
        return (None, "merge failed")


def render_episode_chunked(
    segments: list[tuple[str, str]],
    output_dir: Path,
    voice: str = None,
) -> tuple[list[Path], list[str]]:
    """
    Render all episode segments using chunked TTS.
    
    Each segment is split at [pause] markers and paragraph breaks.
    Chunks are rendered in parallel and merged with 1s silence gaps.
    
    Args:
        segments: List of (segment_name, text) tuples
        output_dir: Output directory for WAV files
        voice: TTS voice to use (default from CHARACTER env)
    
    Returns:
        (successful_paths, failed_names)
    """
    voice = voice or get_tts_voice()
    
    print(f"Rendering {len(segments)} segments with chunked TTS...")
    
    successful = []
    failed = []
    
    for name, text in segments:
        path, error = render_segment_chunked(name, text, output_dir, voice)
        if path:
            successful.append(path)
            print(f"  ✓ {name}")
        else:
            failed.append(name)
            print(f"  ✗ {name}: {error}")
    
    print(f"\nRendered {len(successful)}/{len(segments)} segments")
    
    return successful, failed
