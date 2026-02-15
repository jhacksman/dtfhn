#!/usr/bin/env python3
"""
Resilient episode pipeline orchestrator.

Replaces run_episode.sh's inline Python with a proper Python orchestrator
that checks DB + disk before each phase and resumes from any failure point.

5-phase pipeline: fetch → scripts → tts → assembly → upload

Usage:
    python3 scripts/run_episode.py                    # Today's date (YYYY-MM-DD)
    python3 scripts/run_episode.py 2026-02-09         # Specific date
    python3 scripts/run_episode.py --dry-run           # Show what would happen
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage import (
    get_stories_by_date,
    get_pipeline_state,
    upsert_pipeline_state,
    store_episode,
    store_segments_batch,
    episode_exists,
)
from src.pipeline import (
    run_episode_pipeline,
    get_episode_dir,
    segment_name,
    EPISODES_DIR,
)
from src.audio import get_audio_duration

# TTS server
TTS_URL = "http://192.168.0.134:7849"


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def notify(status: str, message: str):
    """Send notification via openclaw system event."""
    log(f"NOTIFY {status}: {message}")
    try:
        subprocess.run(
            ["openclaw", "system", "event", "--text",
             f"DTFHN Pipeline {status}: {message}", "--mode", "now"],
            capture_output=True, timeout=30,
        )
    except Exception as e:
        log(f"WARNING: notification failed: {e}")


def check_tts_server() -> bool:
    """Check TTS server health with retries."""
    import requests
    for attempt in range(1, 4):
        try:
            r = requests.get(f"{TTS_URL}/", timeout=10)
            if r.status_code == 200:
                log("TTS server is up")
                return True
        except Exception:
            pass
        log(f"TTS server not responding, retry {attempt}/3...")
        time.sleep(30)
    return False


def check_tts_voice(voice: str) -> bool:
    """Check if required voice is available, restart server if needed."""
    import requests
    try:
        r = requests.get(f"{TTS_URL}/voices", timeout=10)
        voices = r.json()
        if voice in voices:
            log(f"Voice '{voice}' available")
            return True
    except Exception:
        pass
    
    log(f"Voice '{voice}' not found, triggering restart...")
    try:
        requests.post(f"{TTS_URL}/restart", timeout=10)
    except Exception:
        pass
    
    for i in range(24):
        time.sleep(5)
        try:
            r = requests.get(f"{TTS_URL}/", timeout=5)
            if r.status_code == 200:
                r2 = requests.get(f"{TTS_URL}/voices", timeout=5)
                if voice in r2.json():
                    log(f"Voice '{voice}' available after restart")
                    return True
        except Exception:
            pass
    return False


def phase_fetch(episode_date: str, episode_dir: Path, dry_run: bool = False) -> bool:
    """Phase 1: Fetch stories from HN."""
    stories = get_stories_by_date(episode_date)
    if len(stories) >= 10:
        log(f"SKIP fetch: {len(stories)} stories already exist for {episode_date}")
        if not dry_run:
            upsert_pipeline_state(episode_date, phase="fetch", stories_fetched=len(stories))
        return True

    if dry_run:
        log(f"DRY-RUN: Would fetch stories for {episode_date}")
        return True

    log("Fetching stories from HN...")
    # run_episode_pipeline handles fetch + storage
    # We call it but it also does scripts — we handle that by checking skip_fetch
    # Actually, for the resilient pipeline we need to separate fetch from scripts.
    # But run_episode_pipeline bundles them. For now, let it run — it's idempotent-ish.
    # The key insight: if stories exist, we skip fetch. If scripts exist, phase_scripts skips.
    from src.hn import fetch_stories, story_to_article_dict
    from src.storage import store_stories_batch, get_existing_hn_ids
    from src.pipeline import convert_article_to_story

    # Collect HN IDs from ALL previous episodes — never repeat a story
    recent_ids = set()
    for recent_dir in sorted(EPISODES_DIR.glob("20*")):
        sfile = recent_dir / "stories.json"
        if sfile.exists() and recent_dir.name != episode_date:
            try:
                for s in json.loads(sfile.read_text()):
                    if s.get("id"):
                        recent_ids.add(str(s["id"]))
            except Exception:
                pass
    if recent_ids:
        log(f"Excluding {len(recent_ids)} story IDs from recent episodes")

    hn_stories = fetch_stories(limit=10, verbose=True, exclude_ids=recent_ids)
    if not hn_stories:
        raise RuntimeError("No stories fetched from HN!")

    stories_dicts = [
        convert_article_to_story(story_to_article_dict(s, episode_date, i + 1))
        for i, s in enumerate(hn_stories)
    ]

    store_stories_batch(stories_dicts)
    log(f"Stored {len(stories_dicts)} stories")

    # Save stories.json
    stories_json = [
        {
            "id": s.id, "title": s.title, "url": s.url, "score": s.score,
            "comment_count": s.comment_count, "fetch_status": s.fetch_status,
            "article_chars": len(s.article_text), "comments": len(s.comments),
        }
        for s in hn_stories
    ]
    (episode_dir / "stories.json").write_text(json.dumps(stories_json, indent=2))

    upsert_pipeline_state(episode_date, phase="fetch", stories_fetched=len(stories_dicts))
    return True


def phase_scripts(episode_date: str, episode_dir: Path, dry_run: bool = False) -> bool:
    """Phase 2: Generate scripts, interstitials, intro, outro."""
    # Check what already exists on disk
    all_exist = True
    for i in range(1, 11):
        if not (episode_dir / f"{segment_name('script', i)}.txt").exists():
            all_exist = False
            break
    for i in range(1, 10):
        if not (episode_dir / f"{segment_name('interstitial', i, i + 1)}.txt").exists():
            all_exist = False
            break
    intro_exists = (episode_dir / f"{segment_name('intro')}.txt").exists()
    outro_exists = (episode_dir / f"{segment_name('outro')}.txt").exists()

    if all_exist and intro_exists and outro_exists:
        # Also check manifest
        if (episode_dir / "manifest.json").exists():
            log("SKIP scripts: All scripts, interstitials, intro, outro already exist")
            upsert_pipeline_state(
                episode_date, phase="scripts",
                scripts_generated=10, interstitials_generated=9,
                intro_generated=True, outro_generated=True,
            )
            return True

    if dry_run:
        log("DRY-RUN: Would generate scripts")
        return True

    log("Generating scripts via run_episode_pipeline (skip_fetch=True)...")
    # Use the existing pipeline which handles script generation
    manifest = run_episode_pipeline(
        episode_date=episode_date,
        num_stories=10,
        word_target=4000,
        skip_fetch=True,
        verbose=True,
    )

    upsert_pipeline_state(
        episode_date, phase="scripts",
        scripts_generated=10, interstitials_generated=9,
        intro_generated=True, outro_generated=True,
    )
    return True


def phase_tts(episode_date: str, episode_dir: Path, dry_run: bool = False) -> bool:
    """Phase 3: TTS rendering."""
    # Check if final MP3 already exists (skip everything)
    final_mp3 = episode_dir / f"DTFHN-{episode_date}.mp3"
    if final_mp3.exists() and final_mp3.stat().st_size > 1_000_000:
        log(f"SKIP tts: Final MP3 already exists ({final_mp3.stat().st_size / 1024 / 1024:.1f} MB)")
        upsert_pipeline_state(episode_date, phase="tts", segments_rendered=21, segments_total=21)
        return True

    if dry_run:
        log("DRY-RUN: Would run TTS generation")
        return True

    # generate_episode_audio.py already has all the resume logic
    log("Running TTS generation...")
    result = subprocess.run(
        [sys.executable, "-u", "scripts/generate_episode_audio.py", episode_date, "--force"],
        cwd=str(PROJECT_ROOT),
        timeout=7200,  # 2 hour timeout
    )

    if result.returncode != 0:
        upsert_pipeline_state(episode_date, phase="tts", error_log=f"TTS failed with exit code {result.returncode}")
        raise RuntimeError(f"TTS generation failed (exit {result.returncode})")

    upsert_pipeline_state(episode_date, phase="tts", segments_rendered=21, segments_total=21)
    return True


def phase_assembly(episode_date: str, episode_dir: Path, dry_run: bool = False) -> bool:
    """Phase 4: Assembly (MP3 already created by TTS phase, just verify)."""
    final_mp3 = episode_dir / f"DTFHN-{episode_date}.mp3"
    if not final_mp3.exists():
        raise RuntimeError(f"Assembly: Final MP3 not found at {final_mp3}")

    duration = get_audio_duration(final_mp3)
    if duration < 60:
        raise RuntimeError(f"Assembly: MP3 too short ({duration:.1f}s)")

    log(f"Assembly verified: {final_mp3.name} ({duration / 60:.1f} min)")
    upsert_pipeline_state(episode_date, phase="assembly", episode_assembled=True)
    return True


def phase_upload(episode_date: str, episode_dir: Path, dry_run: bool = False) -> bool:
    """Phase 5: Upload to R2, update feed, deploy site, notify."""
    state = get_pipeline_state(episode_date)

    # Sub-step: R2 upload
    if not (state and state.get("episode_uploaded")):
        if not os.environ.get("CF_R2_ACCESS_KEY_ID"):
            log("SKIP upload: R2 credentials not set")
        elif dry_run:
            log("DRY-RUN: Would upload to R2")
        else:
            log("Uploading to R2...")
            result = subprocess.run(
                [sys.executable, "-u", "scripts/upload_to_r2.py", episode_date],
                cwd=str(PROJECT_ROOT),
                timeout=300,
            )
            if result.returncode != 0:
                log(f"WARNING: R2 upload failed (exit {result.returncode})")
            else:
                upsert_pipeline_state(episode_date, episode_uploaded=True)

    # Sub-step: Verify CDN
    if not dry_run and os.environ.get("CF_R2_ACCESS_KEY_ID"):
        import requests
        ep_url = f"https://pod.c457.org/dtfhn/episodes/DTFHN-{episode_date}.mp3"
        try:
            r = requests.head(ep_url, timeout=10)
            log(f"CDN verify: HTTP {r.status_code}")
        except Exception:
            log("WARNING: CDN verify failed")

    # Sub-step: Trigger site rebuild
    if not (state and state.get("site_deployed")):
        if dry_run:
            log("DRY-RUN: Would trigger site rebuild")
        else:
            log("Triggering site rebuild...")
            try:
                result = subprocess.run(
                    ["git", "commit", "--allow-empty", "-m", f"deploy: {episode_date}"],
                    cwd=os.path.expanduser("~/clawd/dailytechfeedsite"),
                    capture_output=True, timeout=30,
                )
                subprocess.run(
                    ["git", "push"],
                    cwd=os.path.expanduser("~/clawd/dailytechfeedsite"),
                    capture_output=True, timeout=60,
                )
                upsert_pipeline_state(episode_date, site_deployed=True)
                log("Site rebuild triggered")
            except Exception as e:
                log(f"WARNING: Site rebuild failed: {e}")

    # Sub-step: Telegram notification
    if not (state and state.get("notified")):
        if dry_run:
            log("DRY-RUN: Would send Telegram notification")
        else:
            log("Sending Telegram notification...")
            try:
                # Get story count and duration
                manifest_path = episode_dir / "manifest.json"
                story_count = "?"
                if manifest_path.exists():
                    m = json.loads(manifest_path.read_text())
                    scripts = [s for s in m.get("segments", []) if "script" in s and "interstitial" not in s]
                    story_count = str(len(scripts))

                final_mp3 = episode_dir / f"DTFHN-{episode_date}.mp3"
                duration = "?"
                if final_mp3.exists():
                    d = get_audio_duration(final_mp3)
                    duration = f"{d / 60:.0f} min"

                ep_url = f"https://pod.c457.org/dtfhn/episodes/DTFHN-{episode_date}.mp3"
                feed_url = "https://pod.c457.org/dtfhn/feed.xml"
                msg = f"🎙️ New DTFHN Episode: {episode_date}\n\n📊 {story_count} stories · {duration}\n🎧 {ep_url}\n📡 {feed_url}"

                subprocess.run(
                    ["openclaw", "message", "send", "--channel", "telegram",
                     "--target", "6151859458", "--message", msg],
                    capture_output=True, timeout=30,
                )
                upsert_pipeline_state(episode_date, notified=True)
                log("Telegram notification sent")
            except Exception as e:
                log(f"WARNING: Telegram notification failed: {e}")

    upsert_pipeline_state(episode_date, phase="upload")
    return True


def load_pipeline_voice_config() -> dict:
    """Load voice config from pipeline_config.json."""
    config_path = PROJECT_ROOT / "pipeline_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f).get("voice", {})
    return {}


def run_pipeline(episode_date: str, dry_run: bool = False):
    """Run the full resilient pipeline."""
    voice_cfg = load_pipeline_voice_config()
    tts_voice = voice_cfg.get("tts_voice", "forbin")
    rvc_model = voice_cfg.get("rvc_model", "")
    log(f"=== DTFHN Pipeline: {episode_date} ===")
    log(f"Voice: {tts_voice}" + (f" + RVC {rvc_model}" if voice_cfg.get("rvc_enabled") else ""))

    episode_dir = get_episode_dir(episode_date)

    # Load .env if not already set
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists() and not os.environ.get("CF_R2_ACCESS_KEY_ID"):
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

    # Initialize pipeline state
    state = get_pipeline_state(episode_date)
    if state:
        log(f"Resuming from phase: {state.get('phase', 'unknown')}")
    elif not dry_run:
        upsert_pipeline_state(episode_date, phase="fetch")
        log("Starting new pipeline run")
    else:
        log("Starting new pipeline run (dry-run, no DB writes)")

    try:
        # Phase 1: Fetch
        phase_fetch(episode_date, episode_dir, dry_run)

        # Phase 2: Scripts
        phase_scripts(episode_date, episode_dir, dry_run)

        # Pre-flight: TTS server check
        if not dry_run:
            if not check_tts_server():
                raise RuntimeError("TTS server unreachable after 3 retries")

            # Voice check — use pipeline_config.json as source of truth
            voice_cfg = load_pipeline_voice_config()
            voice = voice_cfg.get("tts_voice", "forbin")
            if not check_tts_voice(voice):
                raise RuntimeError(f"Voice '{voice}' not available")

        # Phase 3: TTS
        phase_tts(episode_date, episode_dir, dry_run)

        # Phase 4: Assembly (verify)
        if not dry_run:
            phase_assembly(episode_date, episode_dir, dry_run)

        # Phase 5: Upload
        phase_upload(episode_date, episode_dir, dry_run)

        # Mark complete
        if not dry_run:
            upsert_pipeline_state(episode_date, phase="complete")
        log(f"=== PIPELINE COMPLETE: {episode_date} ===")

        if not dry_run:
            notify("SUCCESS", f"Episode {episode_date} completed")

    except Exception as e:
        log(f"PIPELINE FAILED: {e}")
        upsert_pipeline_state(episode_date, error_log=str(e))
        if not dry_run:
            notify("FAILURE", f"Episode {episode_date}: {e}")
        raise


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Resilient DTFHN episode pipeline")
    parser.add_argument("episode_date", nargs="?",
                        default=datetime.now().strftime("%Y-%m-%d"),
                        help="Episode date (YYYY-MM-DD, default: today)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without doing it")
    args = parser.parse_args()

    # Pipeline config is now the source of truth for voice (not CHARACTER env var)
    # Keep CHARACTER for backward compat with generator.py character system
    os.environ.setdefault("CHARACTER", "jack")

    run_pipeline(args.episode_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
