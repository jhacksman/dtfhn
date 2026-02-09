#!/usr/bin/env python3
"""
Show pipeline status for an episode.

Usage:
    python3 scripts/episode_status.py              # Today
    python3 scripts/episode_status.py 2026-02-08   # Specific date
    python3 scripts/episode_status.py --all        # All episodes
"""

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage import get_pipeline_state, get_stories_by_date
from src.pipeline import segment_name, EPISODES_DIR


def show_status(episode_date: str):
    """Show detailed status for one episode."""
    state = get_pipeline_state(episode_date)
    episode_dir = EPISODES_DIR / episode_date

    print(f"\nEpisode: {episode_date}")

    if state:
        print(f"Phase:   {state.get('phase', '?')}")
        print(f"Started: {state.get('started_at', '?')}")
        print(f"Updated: {state.get('updated_at', '?')}")
        if state.get("error_log"):
            print(f"Error:   {state['error_log']}")
    else:
        print("Phase:   (no pipeline state in DB)")

    print()

    # Fetch
    stories = get_stories_by_date(episode_date)
    n_stories = len(stories)
    icon = "✅" if n_stories >= 10 else ("🔄" if n_stories > 0 else "⬜")
    print(f"  {icon} Fetch:     {n_stories}/10 stories")

    # Scripts
    n_scripts = sum(1 for i in range(1, 11)
                    if (episode_dir / f"{segment_name('script', i)}.txt").exists())
    n_inter = sum(1 for i in range(1, 10)
                  if (episode_dir / f"{segment_name('interstitial', i, i + 1)}.txt").exists())
    intro = (episode_dir / f"{segment_name('intro')}.txt").exists()
    outro = (episode_dir / f"{segment_name('outro')}.txt").exists()
    scripts_done = n_scripts == 10 and n_inter == 9 and intro and outro
    icon = "✅" if scripts_done else ("🔄" if n_scripts > 0 else "⬜")
    intro_mark = "✓" if intro else "✗"
    outro_mark = "✓" if outro else "✗"
    print(f"  {icon} Scripts:   {n_scripts}/10 scripts, {n_inter}/9 interstitials, intro {intro_mark}, outro {outro_mark}")

    # TTS
    segments_dir = episode_dir / "segments"
    if segments_dir.exists():
        mp3s = list(segments_dir.glob("*.mp3"))
        n_mp3 = len(mp3s)
    else:
        n_mp3 = 0
    final_mp3 = episode_dir / f"DTFHN-{episode_date}.mp3"
    tts_done = final_mp3.exists() and final_mp3.stat().st_size > 1_000_000
    icon = "✅" if tts_done else ("🔄" if n_mp3 > 0 else "⬜")
    extra = ""
    if tts_done:
        try:
            from src.audio import get_audio_duration
            d = get_audio_duration(final_mp3)
            extra = f" → {d / 60:.1f} min"
        except Exception:
            pass
    print(f"  {icon} TTS:       {n_mp3} segment MP3s{extra}")

    # Assembly
    icon = "✅" if tts_done else "⬜"
    size = f" ({final_mp3.stat().st_size / 1024 / 1024:.1f} MB)" if tts_done else ""
    print(f"  {icon} Assembly:  {'done' if tts_done else 'pending'}{size}")

    # Upload
    uploaded = state.get("episode_uploaded", False) if state else False
    icon = "✅" if uploaded else "⬜"
    print(f"  {icon} Upload:    {'done' if uploaded else 'pending'}")

    print(f"\nEpisode dir: {episode_dir}")

    # Also check for old HHMM-suffixed dirs
    parent = EPISODES_DIR
    related = sorted([d.name for d in parent.iterdir()
                      if d.is_dir() and d.name.startswith(episode_date)])
    if len(related) > 1:
        print(f"Related dirs: {', '.join(related)}")


def show_all():
    """Show summary for all episodes."""
    from src.storage import get_pipeline_state_table, _table_names, get_db
    
    # Collect all known episode dates from directories
    dates = set()
    if EPISODES_DIR.exists():
        for d in EPISODES_DIR.iterdir():
            if d.is_dir() and len(d.name) == 10 and d.name[4] == '-':
                dates.add(d.name)
    
    # Also check pipeline_state table
    db = get_db()
    if "pipeline_state" in _table_names(db):
        table = db.open_table("pipeline_state")
        rows = table.to_arrow().to_pylist()
        for r in rows:
            dates.add(r["episode_date"])
    
    for date in sorted(dates, reverse=True):
        state = get_pipeline_state(date)
        phase = state.get("phase", "?") if state else "?"
        episode_dir = EPISODES_DIR / date
        has_mp3 = (episode_dir / f"DTFHN-{date}.mp3").exists()
        icon = "✅" if phase == "complete" or has_mp3 else "🔄"
        print(f"  {icon} {date}  phase={phase}")


def main():
    if "--all" in sys.argv:
        show_all()
        return

    date = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            date = arg
            break
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    show_status(date)


if __name__ == "__main__":
    main()
