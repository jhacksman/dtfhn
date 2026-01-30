"""TTS module for Carlin podcast.

Interfaces with quato TTS server (F5-TTS with George Carlin voice).
Server has 3 GPUs that process requests in parallel.
"""
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# TTS server config (quato)
TTS_URL = "http://192.168.0.134:7849/speak"
TTS_STATUS_URL = "http://192.168.0.134:7849/status"
TTS_VOICE = "george_carlin"
TTS_TIMEOUT = 3600  # 1 hour — connections wait in server queue until processed

# Robust TTS pipeline configuration
POLL_INTERVAL_SECONDS = 5  # How often to poll /status
PROGRESS_TIMEOUT_SECONDS = 300  # 5 min with no progress = stall
MAX_RETRY_ATTEMPTS = 3  # Max times to retry failed segments
MIN_WAV_SIZE_BYTES = 1000  # Minimum valid WAV file size


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
        'yml': 'yeah mel',
        'yaml': 'yeah mel',
        'json': 'jason',
        'txt': 'text',
        'toml': 'toemul',
        'gif': 'jif',
        'wav': 'wave',
    }
    
    # Extensions that sound fine spoken as-is (not spelled out)
    NATURAL_EXTENSIONS = {
        'zip', 'log', 'bin', 'bat', 'doc', 'go',
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


def text_to_speech(text: str, output_path: Path, voice: str = TTS_VOICE) -> tuple[bool, str]:
    """
    Generate WAV from text via quato TTS.
    
    Args:
        text: Text to convert to speech
        output_path: Where to save the WAV file
        voice: Voice profile to use (default: george_carlin)
    
    Returns:
        (success, error_message) - error_message is empty on success
    """
    try:
        # Add em-dashes for natural breathing pauses
        prepared_text = prepare_text_for_tts(text)
        
        response = requests.post(
            TTS_URL,
            headers={"Content-Type": "application/json"},
            json={"text": prepared_text, "voice": voice, "timeout": 0},
            timeout=TTS_TIMEOUT,
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
        
        # Write validated WAV
        output_path.write_bytes(response.content)
        return (True, "")
    except requests.exceptions.Timeout:
        return (False, "request timeout")
    except requests.exceptions.ConnectionError as e:
        return (False, f"connection error: {e}")
    except Exception as e:
        return (False, f"unexpected error: {e}")


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
    max_workers: int = 25,
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
    max_workers: int = 25,
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
    
    # SUBMIT & RETRY: Fire all requests with retry support
    for attempt in range(MAX_RETRY_ATTEMPTS):
        if attempt > 0:
            backoff_time = retry_backoff * (2 ** (attempt - 1))
            print(f"Retry attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS} after {backoff_time:.1f}s backoff...")
            time.sleep(backoff_time)
        
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
