# Robust TTS Pipeline Design

**Date:** 2026-01-28  
**Status:** Proposal  
**Problem:** Duplicate submissions, orphaned requests, no visibility/recovery

---

## Problem Analysis

### What Went Wrong

During TTS generation for episode 2026-01-27, the pipeline failed in multiple ways:

#### 1. Duplicate Submissions (42 requests instead of 21)

**Root cause:** A sub-agent restarted the generation script while requests from the first run were still queued on the server.

**Why it happened:**
- No pre-flight check to detect existing queue items
- No idempotency — script doesn't check if WAV files already exist
- No visibility into whether a previous run was in progress

#### 2. Orphaned Requests

**Root cause:** The executor timeout (via `yieldMs`) expired before HTTP responses returned, but the requests continued processing on the server.

**Why it happened:**
- TTS requests can take minutes for long segments
- `text_to_speech_parallel()` waits synchronously for all responses
- When the calling process dies, requests still complete server-side but nobody retrieves the results
- HTTP response bytes are discarded when client disconnects

#### 3. No Visibility Into Progress

**Root cause:** The script fires all requests and blocks until all complete. No intermediate status.

**Why it happened:**
- `as_completed()` gives per-request notification, but only locally
- No way to monitor server-side progress (how many completed, how many remain)
- Total blackbox during the ~25 minute TTS phase

#### 4. No Recovery Mechanism

**Root cause:** If the script crashes mid-generation, there's no way to resume.

**Why it happened:**
- WAV files are only created when HTTP response is received
- If client dies before response, the audio is generated but lost
- Restarting means regenerating everything, wasting GPU time

### The Core Issue

The current design treats TTS as a synchronous batch operation: submit all, wait for all, proceed. This is fragile because:

1. **Long-running operations** — Individual requests take 30s-3min
2. **No server-side persistence** — Audio is only saved when client receives it
3. **Client-server coupling** — Client death = data loss
4. **All-or-nothing** — Can't resume partial batches

---

## Proposed Solution Architecture

### Design Principles

1. **Server owns persistence** — WAV files saved server-side, not via HTTP response
2. **Client polling, not blocking** — Submit jobs, poll for completion
3. **Idempotency everywhere** — Safe to retry, safe to restart
4. **Progress visibility** — Monitor queue and completion status
5. **Graceful recovery** — Resume from any failure point

### New TTS Flow

```
┌─────────────┐     ┌────────────────┐     ┌─────────────────┐
│   Client    │────▶│  Pre-flight    │────▶│  Submit Jobs    │
│   Start     │     │  Checks        │     │  (fire & forget)│
└─────────────┘     └────────────────┘     └─────────────────┘
                            │                       │
                    ┌───────▼───────┐               │
                    │ Queue empty?  │               │
                    │ Files exist?  │               │
                    └───────────────┘               │
                                                    │
                    ┌───────────────────────────────▼───────┐
                    │           Poll Until Done             │
                    │  - Check /status (queue empty?)       │
                    │  - Check filesystem (files created?)  │
                    │  - Timeout on no-progress, not wall   │
                    └───────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │      Verify & Download        │
                    │  - All files present?         │
                    │  - Copy from server or local  │
                    │  - Retry missing only         │
                    └───────────────────────────────┘
```

### Server-Side Changes Required

The current server returns WAV bytes directly in the HTTP response. This creates the persistence problem. Two options:

**Option A: Server saves files (recommended)**
- Add `output_path` parameter to `/speak` endpoint
- Server writes WAV to shared filesystem (NFS or local)
- Response is just `{"status": "ok", "path": "/output/segment_01.wav"}`
- Client can poll filesystem for completion

**Option B: Job queue with async retrieval**
- `/speak` returns job_id immediately
- `/job/{id}/status` returns pending/complete/failed
- `/job/{id}/result` returns WAV bytes when complete
- Jobs persist until retrieved

**Recommendation:** Option A is simpler and leverages the fact that client and server share a filesystem (quato mounts could be exposed, or we write to a path both can access). Option B requires more server changes but is more robust for truly distributed systems.

For this project, we'll assume **Option A is not immediately available** and design a client-side solution that works with the current server.

### Client-Side Robust Flow

Given that we can't change the server immediately, we implement robustness client-side:

```
1. PRE-FLIGHT CHECKS
   ├── Check /status — if queue not empty, ABORT with warning
   ├── Scan output_dir — identify existing valid WAV files
   └── Build skip list — don't regenerate what exists

2. FILTERED SUBMISSION
   ├── Submit only missing segments (idempotency)
   ├── Fire all at once (parallel efficiency)
   └── Don't wait for responses yet

3. PROGRESS MONITORING
   ├── Poll /status every 5-10 seconds
   ├── Track: completed_count, queue_depth
   ├── Log progress: "12/21 complete, 9 queued"
   ├── Timeout if no progress for N minutes (not wall clock)
   └── Timeout = progress stall, not total time

4. RESULT COLLECTION
   ├── As files complete, collect them
   ├── ThreadPool waits for HTTP responses
   ├── On timeout: check if file was created anyway (race recovery)
   └── Build list of successes and failures

5. RETRY PHASE
   ├── For any failures, check if WAV exists (late completion)
   ├── Retry only truly failed segments
   └── Limit retry attempts (3 max)

6. VERIFICATION
   ├── All expected WAVs present?
   ├── All WAVs non-zero size?
   ├── Checksums if paranoid
   └── Report final status
```

---

## Code Changes

### Changes to `src/tts.py`

#### New Constants

```python
# Polling configuration
POLL_INTERVAL_SECONDS = 5
PROGRESS_TIMEOUT_SECONDS = 300  # 5 min with no progress = stall
MAX_RETRY_ATTEMPTS = 3
MIN_WAV_SIZE_BYTES = 1000  # Minimum valid WAV size
```

#### New Function: `check_queue_empty()`

```python
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
```

#### New Function: `find_existing_wavs()`

```python
def find_existing_wavs(
    segments: list[tuple[str, str]], 
    output_dir: Path
) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Identify which segments already have valid WAV files.
    
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
        if wav_path.exists() and wav_path.stat().st_size > MIN_WAV_SIZE_BYTES:
            existing.append(name)
        else:
            missing.append((name, text))
    
    return existing, missing
```

#### New Function: `wait_for_queue_drain()`

```python
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
    import time
    
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
```

#### Refactored: `text_to_speech_parallel_robust()`

```python
def text_to_speech_parallel_robust(
    segments: list[tuple[str, str]],
    output_dir: Path,
    voice: str = TTS_VOICE,
    max_workers: int = 25,
    skip_existing: bool = True,
    abort_on_queue: bool = True,
) -> tuple[list[Path], list[str]]:
    """
    Robust parallel TTS with pre-flight checks and recovery.
    
    Args:
        segments: list of (name, text) tuples
        output_dir: where to save WAV files
        voice: voice profile to use
        max_workers: max concurrent requests
        skip_existing: skip segments with existing valid WAVs
        abort_on_queue: abort if queue already has items
    
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
    
    # PRE-FLIGHT: Find existing WAVs
    if skip_existing:
        existing, to_generate = find_existing_wavs(segments, output_dir)
        if existing:
            print(f"Skipping {len(existing)} existing WAVs: {existing[:3]}...")
    else:
        existing = []
        to_generate = segments
    
    if not to_generate:
        print("All segments already exist!")
        return [output_dir / f"{name}.wav" for name, _ in segments], []
    
    print(f"Generating {len(to_generate)} segments...")
    
    # SUBMIT: Fire all requests
    # (Using existing parallel mechanism, but with retry support)
    
    failed_names = []
    for attempt in range(MAX_RETRY_ATTEMPTS):
        if attempt > 0:
            print(f"Retry attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS}...")
        
        # Generate missing segments
        wav_files = text_to_speech_parallel(to_generate, output_dir, voice, max_workers)
        
        # Check what succeeded
        succeeded = {p.stem for p in wav_files}
        failed_names = [name for name, _ in to_generate if name not in succeeded]
        
        if not failed_names:
            break
        
        # Check if files were created despite timeout (race condition recovery)
        still_missing = []
        for name in failed_names:
            wav_path = output_dir / f"{name}.wav"
            if wav_path.exists() and wav_path.stat().st_size > MIN_WAV_SIZE_BYTES:
                print(f"  Recovered {name} (file created after timeout)")
                wav_files.append(wav_path)
            else:
                still_missing.append(name)
        
        if not still_missing:
            failed_names = []
            break
        
        # Update to_generate for retry
        to_generate = [(n, t) for n, t in to_generate if n in still_missing]
        failed_names = still_missing
    
    # Build complete list including pre-existing files
    all_paths = []
    for name, _ in segments:
        wav_path = output_dir / f"{name}.wav"
        if wav_path.exists() and wav_path.stat().st_size > MIN_WAV_SIZE_BYTES:
            all_paths.append(wav_path)
    
    return all_paths, failed_names
```

### Changes to `scripts/generate_episode_audio.py`

#### Add Pre-Flight Safety Check

```python
def main():
    print(f"=== Generating TTS for episode {EPISODE_DATE} ===")
    
    # PRE-FLIGHT: Check if WAVs already exist (detect re-run)
    wav_dir = EPISODE_DIR / "wav_temp"
    if wav_dir.exists():
        existing = list(wav_dir.glob("*.wav"))
        if existing:
            print(f"WARNING: {len(existing)} WAV files already exist in {wav_dir}")
            print("This may indicate a previous incomplete run.")
            response = input("Continue? (y/N): ")
            if response.lower() != 'y':
                print("Aborted.")
                sys.exit(1)
    
    # PRE-FLIGHT: Check TTS server queue
    print("Checking TTS server status...")
    status = check_tts_status()
    if "error" in status:
        print(f"ERROR: TTS server unreachable: {status['error']}")
        sys.exit(1)
    
    active = status.get('total_active', 0)
    queued = status.get('total_queued', 0)
    
    if active > 0 or queued > 0:
        print(f"WARNING: TTS queue not empty ({active} active, {queued} queued)")
        print("This may indicate another process is using the TTS server.")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(1)
    
    # ... rest of main() ...
```

#### Use Robust TTS Function

```python
# Replace:
wav_files = text_to_speech_parallel(segments, wav_dir)

# With:
from src.tts import text_to_speech_parallel_robust

wav_files, failed = text_to_speech_parallel_robust(
    segments, 
    wav_dir,
    skip_existing=True,
    abort_on_queue=False,  # Already checked manually above
)

if failed:
    print(f"ERROR: {len(failed)} segments failed after retries: {failed}")
    print("Fix the issue and re-run. Existing WAVs will be reused.")
    sys.exit(1)
```

#### Add Lock File for Concurrency Protection

```python
import fcntl

LOCK_FILE = EPISODE_DIR / ".tts_generation.lock"

def acquire_lock():
    """Acquire exclusive lock to prevent concurrent runs."""
    lock_fd = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except BlockingIOError:
        print("ERROR: Another TTS generation is already running for this episode.")
        print(f"Lock file: {LOCK_FILE}")
        sys.exit(1)

def release_lock(lock_fd):
    """Release the exclusive lock."""
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()
    LOCK_FILE.unlink(missing_ok=True)

def main():
    lock_fd = acquire_lock()
    try:
        # ... main logic ...
    finally:
        release_lock(lock_fd)
```

---

## Pseudocode: Robust TTS Flow

```
FUNCTION generate_episode_audio(episode_date):
    episode_dir = get_episode_dir(episode_date)
    wav_dir = episode_dir / "wav_temp"
    
    # 1. ACQUIRE LOCK
    lock = acquire_exclusive_lock(episode_dir)
    IF NOT lock:
        ERROR("Another generation in progress")
        EXIT
    
    TRY:
        # 2. PRE-FLIGHT CHECKS
        server_status = GET /status
        IF server_status.error:
            ERROR("TTS server unreachable")
            EXIT
        
        IF server_status.total_active > 0 OR server_status.total_queued > 0:
            WARN("Queue not empty - possible orphaned jobs")
            IF NOT user_confirms_continue():
                EXIT
        
        # 3. LOAD SEGMENTS
        segments = load_segments_from_manifest(episode_dir)
        
        # 4. FIND EXISTING WAVS (idempotency)
        existing_wavs = []
        missing_segments = []
        FOR name, text IN segments:
            wav_path = wav_dir / f"{name}.wav"
            IF wav_path.exists() AND wav_path.size > 1000:
                existing_wavs.append(wav_path)
                LOG(f"Skipping {name} - already exists")
            ELSE:
                missing_segments.append((name, text))
        
        IF missing_segments.empty():
            LOG("All segments already generated!")
        ELSE:
            # 5. GENERATE MISSING SEGMENTS
            FOR attempt IN 1..MAX_RETRIES:
                # Submit all missing at once
                futures = submit_parallel_tts(missing_segments, wav_dir)
                
                # Poll for progress (not blocking on futures)
                initial_completed = server_status.completed
                last_progress_time = NOW()
                
                WHILE futures_still_pending(futures):
                    status = GET /status
                    current_completed = status.completed
                    
                    # Log progress
                    newly_done = current_completed - initial_completed
                    LOG(f"Progress: {newly_done}/{len(missing_segments)}")
                    
                    # Track stalls
                    IF current_completed > last_completed:
                        last_progress_time = NOW()
                    ELIF NOW() - last_progress_time > STALL_TIMEOUT:
                        WARN("Progress stalled!")
                        BREAK
                    
                    WAIT(5 seconds)
                
                # Collect results
                FOR name, text IN missing_segments:
                    wav_path = wav_dir / f"{name}.wav"
                    IF wav_path.exists() AND wav_path.size > 1000:
                        existing_wavs.append(wav_path)
                        missing_segments.remove((name, text))
                
                IF missing_segments.empty():
                    BREAK  # All done!
                
                LOG(f"Retrying {len(missing_segments)} failed segments...")
            
            IF NOT missing_segments.empty():
                ERROR(f"Failed after {MAX_RETRIES} attempts: {missing_segments}")
                EXIT
        
        # 6. STITCH & FINALIZE
        all_wavs = get_wavs_in_order(segments, wav_dir)
        stitch_wavs(all_wavs, episode_dir / "episode.wav")
        transcode_to_mp3(episode_dir / "episode.wav", episode_dir / "episode.mp3")
        
        # 7. STORE & CLEANUP
        store_episode_in_lancedb(episode_dir)
        cleanup_temp_wavs(wav_dir)
        
        LOG("Episode generation complete!")
    
    FINALLY:
        release_lock(lock)
```

---

## Questions for Server-Side Improvements

If we can modify the quato TTS server, these changes would make the pipeline much more robust:

### 1. Queue Clear Endpoint

```
DELETE /queue
```

Clears all queued (not active) jobs. Useful for recovery from orphaned state.

### 2. Job Tagging

```
POST /speak
{
    "text": "...",
    "voice": "george_carlin",
    "tag": "episode_2026-01-27_script_01"  # NEW
}

GET /status
{
    "gpus": [...],
    "tagged_jobs": {
        "episode_2026-01-27_script_01": "completed",
        "episode_2026-01-27_script_02": "queued"
    }
}
```

Would allow:
- Identifying orphaned jobs by tag
- Resuming by checking which tags completed
- Avoiding duplicates (reject if tag already queued/completed)

### 3. Server-Side File Output

```
POST /speak
{
    "text": "...",
    "output_path": "/shared/episodes/2026-01-27/script_01.wav"  # NEW
}

Response: {"status": "queued", "job_id": "abc123"}
```

Would allow:
- Decoupling submission from retrieval
- Client can die and files still persist
- Polling filesystem instead of holding HTTP connections

### 4. Completed Jobs List

```
GET /completed?since=1706400000
{
    "jobs": [
        {"tag": "script_01", "completed_at": 1706400100, "path": "/tmp/output_abc.wav"},
        ...
    ]
}
```

Would allow:
- Discovering what completed while client was dead
- Recovering orphaned audio files

---

## Summary

### Immediate Client-Side Changes (No Server Mods)

1. **Pre-flight queue check** — Abort if queue not empty
2. **Idempotency via filesystem** — Skip existing valid WAVs
3. **Lock file** — Prevent concurrent runs
4. **Retry with recovery** — Check if files created despite timeout
5. **Progress logging** — Poll /status during generation

### Future Server-Side Improvements

1. Queue clear endpoint
2. Job tagging for tracking
3. Server-side file persistence
4. Completed jobs history

### Risk Mitigation Matrix

| Risk | Mitigation |
|------|------------|
| Duplicate submissions | Pre-flight queue check + lock file |
| Orphaned requests | Progress-based timeout + file existence check |
| No visibility | Poll /status during generation |
| Partial failure | Skip existing + retry failed only |
| Client crash | Files persist, resume on restart |

This design makes the TTS pipeline resilient to the exact failures we experienced, while remaining compatible with the current server implementation.
