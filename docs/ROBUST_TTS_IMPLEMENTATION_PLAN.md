# Robust TTS Implementation Plan

**Date:** 2026-01-28
**Status:** In Progress

## Phase 1: Update src/tts.py

### Add Constants
- `POLL_INTERVAL_SECONDS = 5`
- `PROGRESS_TIMEOUT_SECONDS = 300`
- `MAX_RETRY_ATTEMPTS = 3`
- `MIN_WAV_SIZE_BYTES = 1000`

### Add New Functions

1. **`check_queue_empty()`**
   - Call `check_tts_status()`
   - Return tuple: `(is_empty, active_count, queued_count)`
   - Handle error case (assume not empty on error)

2. **`find_existing_wavs()`**
   - Takes `segments` list and `output_dir`
   - Checks for existing WAV files > MIN_WAV_SIZE_BYTES
   - Returns tuple: `(existing_names, missing_segments)`

3. **`wait_for_queue_drain()`**
   - Takes `expected_count`, `timeout_on_stall`, `poll_interval`
   - Polls `/status` until queue empty or progress stalls
   - Returns tuple: `(success, completed_count)`

4. **`text_to_speech_parallel_robust()`**
   - Pre-flight: check queue empty (optional abort)
   - Pre-flight: find existing WAVs (skip)
   - Submit missing segments
   - Retry loop with race condition recovery
   - Returns tuple: `(successful_paths, failed_names)`

## Phase 2: Update scripts/generate_episode_audio.py

### Add Lock File Mechanism
- Import `fcntl` for file locking
- `acquire_lock()` - get exclusive lock on `.tts_generation.lock`
- `release_lock()` - release lock and delete file
- Wrap `main()` in try/finally with lock

### Add Pre-Flight Checks
- Check if WAV files already exist (detect re-run)
- Check TTS queue status (detect orphaned jobs)
- Prompt user to continue or abort (for interactive runs)
- For automated runs, abort on conflicts

### Use Robust TTS Function
- Replace `text_to_speech_parallel()` with `text_to_speech_parallel_robust()`
- Handle failed segments list gracefully
- Exit with error if any segments failed

## Phase 3: Testing (Syntax Only)
- Check Python syntax compiles
- Verify imports resolve
- DO NOT make actual HTTP requests

## Phase 4: Documentation
- Update CLAUDE.md lessons learned
- Commit changes with meaningful messages

## Commit Plan
1. "feat(tts): add robust TTS constants and helper functions"
2. "feat(tts): add text_to_speech_parallel_robust with retry logic"
3. "feat(scripts): add lock file and pre-flight checks to audio generation"
4. "docs: update CLAUDE.md with robust TTS lessons learned"
