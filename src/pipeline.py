"""
Episode pipeline orchestrator for Carlin Podcast.
Fetches stories, generates scripts, stores everything.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .hn import fetch_stories, story_to_article_dict
from .storage import (
    store_stories_batch,
    update_story_script,
    get_stories_by_date,
    get_existing_hn_ids,
    store_episode,
    get_episode_segments,
)
from .generator import (
    generate_episode_scripts,
    generate_interstitial,
    generate_intro,
    generate_outro,
    format_date_for_tts,
    count_words,
)
from .transcript import generate_vtt, generate_plain_transcript
from .chapters import generate_chapters_json, embed_chapters, load_stories_for_episode

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
EPISODES_DIR = PROJECT_ROOT / "data" / "episodes"

# Speaking rate for estimated timing (words per minute)
# Carlin speaks relatively fast - around 160-170 WPM
WORDS_PER_MINUTE = 165


def segment_name(kind: str, script_num: int = 0, next_num: int = 0) -> str:
    """
    Build a zero-padded sequential segment filename (without extension).

    Pattern: {sequence_number}_-_{segment_name}
    Naming scheme (21 segments total, 00-20):
        00_-_intro
        01_-_script_01  02_-_interstitial_01_02  03_-_script_02  ...
        19_-_script_10
        20_-_outro

    Args:
        kind: "intro", "script", "interstitial", or "outro"
        script_num: 1-based script number (for script/interstitial)
        next_num: 1-based next script number (for interstitial only)
    """
    if kind == "intro":
        return "00_-_intro"
    elif kind == "outro":
        return "20_-_outro"
    elif kind == "script":
        seq = 2 * script_num - 1
        return f"{seq:02d}_-_script_{script_num:02d}"
    elif kind == "interstitial":
        seq = 2 * script_num
        return f"{seq:02d}_-_interstitial_{script_num:02d}_{next_num:02d}"
    else:
        raise ValueError(f"Unknown segment kind: {kind}")


def parse_segment_name(name: str) -> dict:
    """
    Parse a zero-padded segment name back into its components.

    Handles format: NN_-_kind[_args...]
    Returns dict with keys: kind, script_num (optional), next_num (optional).
    """
    # Strip the "NN_-_" sequence prefix
    if len(name) > 5 and name[2:5] == '_-_':
        base = name[5:]
    else:
        base = name

    if base == "intro":
        return {"kind": "intro"}
    elif base == "outro":
        return {"kind": "outro"}
    elif base.startswith("script_"):
        num = int(base.split("_")[1])
        return {"kind": "script", "script_num": num}
    elif base.startswith("interstitial_"):
        parts = base.split("_")
        return {"kind": "interstitial", "script_num": int(parts[1]), "next_num": int(parts[2])}
    else:
        return {"kind": "unknown"}


def estimate_duration(text: str) -> float:
    """Estimate audio duration from word count."""
    words = count_words(text)
    return (words / WORDS_PER_MINUTE) * 60


def build_segment_dicts(
    segments: list[tuple[str, str]],
    articles: list[dict],
) -> list[dict]:
    """
    Convert pipeline segments to segment dicts with estimated timing.
    
    Args:
        segments: List of (segment_name, text) tuples
        articles: List of article dicts (for titles/URLs)
        
    Returns:
        List of segment dicts compatible with transcript/chapters modules
    """
    segment_dicts = []
    current_offset = 0.0
    
    for name, text in segments:
        duration = estimate_duration(text)
        
        # Parse segment type from name (handles zero-padded "NN_kind_..." format)
        parsed = parse_segment_name(name)
        kind = parsed["kind"]
        
        if kind == "intro":
            seg_type = "intro"
            story_pos = None
            title = None
            url = None
        elif kind == "outro":
            seg_type = "outro"
            story_pos = None
            title = None
            url = None
        elif kind == "script":
            seg_type = "script"
            story_pos = parsed["script_num"]
            if story_pos <= len(articles):
                article = articles[story_pos - 1]
                title = article.get("title", f"Story {story_pos}")
                url = article.get("source_url", "")
            else:
                title = f"Story {story_pos}"
                url = None
        elif kind == "interstitial":
            seg_type = "interstitial"
            story_pos = parsed.get("script_num")
            title = None
            url = None
        else:
            seg_type = "unknown"
            story_pos = None
            title = None
            url = None
        
        segment_dicts.append({
            "segment_type": seg_type,
            "story_position": story_pos,
            "text": text,
            "title": title,
            "url": url,
            "start_offset_seconds": current_offset,
            "duration_seconds": duration,
        })
        
        current_offset += duration
    
    return segment_dicts


def generate_episode_metadata(
    episode_dir: Path,
    segment_dicts: list[dict],
    episode_date: str,
    verbose: bool = True,
) -> dict:
    """
    Generate transcript (VTT) and chapter files for an episode.
    
    Args:
        episode_dir: Episode output directory
        segment_dicts: List of segment dicts with timing
        episode_date: Episode date for titles
        verbose: Print progress
        
    Returns:
        Dict with paths to generated files
    """
    if verbose:
        print("\n  Generating metadata files...")
    
    # Generate WebVTT transcript
    vtt_path = episode_dir / "transcript.vtt"
    generate_vtt(segment_dicts, str(vtt_path))
    
    # Generate plain text transcript
    plain_path = episode_dir / "transcript.txt"
    generate_plain_transcript(segment_dicts, str(plain_path))
    
    # Load stories for real chapter titles and HN URLs
    stories = load_stories_for_episode(episode_date)
    
    # Generate JSON chapters
    json_path = episode_dir / "chapters.json"
    generate_chapters_json(
        segment_dicts,
        str(json_path),
        episode_title=f"Daily Tech Feed - {episode_date}",
        stories=stories,
    )
    
    return {
        "transcript_vtt": str(vtt_path),
        "transcript_txt": str(plain_path),
        "chapters_json": str(json_path),
    }


def finalize_episode_audio(
    mp3_path: str,
    episode_date: str,
    verbose: bool = True,
) -> None:
    """
    Finalize episode MP3 with ID3 chapters.
    
    Call this AFTER TTS generation when the MP3 exists and
    segments have real timing in the database.
    
    Args:
        mp3_path: Path to the MP3 file
        episode_date: Episode date to fetch segments
        verbose: Print progress
    """
    if verbose:
        print(f"\n  Embedding chapters into MP3...")
    
    # Get segments with real timing from database
    segments = get_episode_segments(episode_date)
    
    if not segments:
        print(f"  Warning: No segments found for {episode_date}, skipping ID3 chapters")
        return
    
    # Load stories for real chapter titles and HN URLs
    stories = load_stories_for_episode(episode_date)
    
    # Embed chapters
    embed_chapters(mp3_path, segments, stories=stories)


def get_episode_dir(episode_date: str) -> Path:
    """Get the output directory for an episode."""
    episode_dir = EPISODES_DIR / episode_date
    episode_dir.mkdir(parents=True, exist_ok=True)
    return episode_dir


def convert_article_to_story(article: dict) -> dict:
    """Convert old article dict format to new story format."""
    # Extract HN ID from source_id (e.g., "hn-12345" -> "12345")
    source_id = article.get("source_id", "")
    hn_id = source_id.replace("hn-", "") if source_id.startswith("hn-") else source_id
    
    return {
        "episode_date": article["episode_date"],
        "position": article["story_number"],
        "hn_id": hn_id,
        "title": article["title"],
        "url": article.get("source_url", ""),
        "author": article.get("author", ""),
        "score": article.get("score", 0),
        "article_text": article.get("content", ""),
        "comments": article.get("comments", []),
        "raw_html": article.get("raw_html"),
        "fetch_status": article.get("fetch_status", "title_only"),
    }


def run_episode_pipeline(
    episode_date: str = None,
    num_stories: int = 10,
    word_target: int = 4000,
    skip_fetch: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Run the full episode pipeline: fetch → store → generate → assemble.

    Args:
        episode_date: Episode date (default: today)
        num_stories: Number of stories to fetch
        word_target: Total word target for scripts
        skip_fetch: If True, use existing stories from DB
        verbose: Print progress

    Returns:
        Dict with episode metadata and file paths
    """
    if episode_date is None:
        episode_date = datetime.now().strftime("%Y-%m-%d")

    episode_dir = get_episode_dir(episode_date)

    if verbose:
        print("=" * 70)
        print(f"CARLIN PODCAST - EPISODE {episode_date}")
        print("=" * 70)

    # Step 1: Fetch stories (or load from DB)
    if not skip_fetch:
        if verbose:
            print("\n[1/7] FETCHING STORIES FROM HN...")

        hn_stories = fetch_stories(limit=num_stories, verbose=verbose)
        if not hn_stories:
            raise RuntimeError("No stories fetched from HN!")

        # Check for duplicates
        existing_ids = get_existing_hn_ids()
        new_stories = [s for s in hn_stories if s.id not in existing_ids]

        if verbose:
            print(f"\nFetched {len(hn_stories)} stories ({len(new_stories)} new)")

        # Convert to article dicts then to story dicts
        articles = [
            story_to_article_dict(s, episode_date, i + 1)
            for i, s in enumerate(hn_stories)
        ]
        stories = [convert_article_to_story(a) for a in articles]

        # Save raw stories data
        stories_json = [
            {
                "id": s.id,
                "title": s.title,
                "url": s.url,
                "score": s.score,
                "comment_count": s.comment_count,
                "fetch_status": s.fetch_status,
                "article_chars": len(s.article_text),
                "comments": len(s.comments),
            }
            for s in hn_stories
        ]
        (episode_dir / "stories.json").write_text(json.dumps(stories_json, indent=2))

        # Store in LanceDB
        if verbose:
            print("\n[2/7] STORING STORIES IN LANCEDB...")
        store_stories_batch(stories)
        if verbose:
            print(f"  Stored {len(stories)} stories")
    else:
        if verbose:
            print("\n[1/7] LOADING EXISTING STORIES...")
        stories = get_stories_by_date(episode_date)
        if not stories:
            raise RuntimeError(f"No stories found for {episode_date}")
        if verbose:
            print(f"  Loaded {len(stories)} stories")
            print("\n[2/7] SKIPPING STORAGE (using existing)")
        # Convert loaded stories to article format for generator compatibility
        articles = [
            {
                "episode_date": s["episode_date"],
                "story_number": s["position"],
                "source_id": f"hn-{s['hn_id']}",
                "source_url": s["url"],
                "title": s["title"],
                "content": s.get("article_text", ""),
                "comments": s.get("comments", []),
                "fetch_status": s.get("fetch_status", "title_only"),
            }
            for s in stories
        ]

    # Ensure articles is defined for either path
    if not skip_fetch:
        # Convert stories back to articles format for generator
        articles = [
            {
                "episode_date": s["episode_date"],
                "story_number": s["position"],
                "source_id": f"hn-{s['hn_id']}",
                "source_url": s["url"],
                "title": s["title"],
                "content": s.get("article_text", ""),
                "comments": s.get("comments", []),
                "fetch_status": s.get("fetch_status", "title_only"),
            }
            for s in stories
        ]

    # Step 3: Generate scripts
    if verbose:
        print("\n[3/7] GENERATING SCRIPTS...")

    scripts_with_counts = generate_episode_scripts(articles, word_target)

    # Save individual scripts and store in DB
    for i, (script, word_count) in enumerate(scripts_with_counts):
        script_path = episode_dir / f"{segment_name('script', i + 1)}.txt"
        script_path.write_text(script)

        # Update script in LanceDB story
        update_story_script(
            episode_date=episode_date,
            position=i + 1,
            script=script,
        )

    scripts = [s for s, _ in scripts_with_counts]
    total_words = sum(c for _, c in scripts_with_counts)

    if verbose:
        print(f"\n  Generated {len(scripts)} scripts ({total_words} words total)")

    # Step 4: Generate interstitials
    if verbose:
        print("\n[4/7] GENERATING INTERSTITIALS...")

    interstitials = []
    for i in range(len(scripts) - 1):
        if verbose:
            print(f"  Transition {i + 1}→{i + 2}...")

        # Get next article title
        next_title = articles[i + 1].get("title", "next topic") if i + 1 < len(articles) else "next topic"

        trans = generate_interstitial(scripts[i], scripts[i + 1], next_title)
        interstitials.append(trans)

        # Save individual interstitial
        trans_path = episode_dir / f"{segment_name('interstitial', i + 1, i + 2)}.txt"
        trans_path.write_text(trans)

        # Update story with interstitial
        update_story_script(
            episode_date=episode_date,
            position=i + 1,
            script=scripts[i],
            interstitial_next=trans,
        )

    if verbose:
        print(f"  Generated {len(interstitials)} interstitials")

    # Step 5: Generate dynamic intro and outro
    if verbose:
        print("\n[5/7] GENERATING INTRO & OUTRO...")

    # Resolve TTS date
    try:
        tts_date = format_date_for_tts(episode_date)
    except ValueError:
        # For test episodes like "test-20260127-200820"
        tts_date = episode_date

    intro = generate_intro(scripts, interstitials, tts_date)
    intro_path = episode_dir / f"{segment_name('intro')}.txt"
    intro_path.write_text(intro)
    if verbose:
        print(f"  Intro: {count_words(intro)} words → {intro_path.name}")

    outro = generate_outro(scripts, interstitials, intro, tts_date)
    outro_path = episode_dir / f"{segment_name('outro')}.txt"
    outro_path.write_text(outro)
    if verbose:
        print(f"  Outro: {count_words(outro)} words → {outro_path.name}")

    # Step 6: Assemble full episode
    if verbose:
        print("\n[6/7] ASSEMBLING EPISODE...")

    # Build full episode text with zero-padded sequential names
    segments = []
    segments.append((segment_name("intro"), intro))

    for i, script in enumerate(scripts):
        segments.append((segment_name("script", i + 1), script))
        if i < len(interstitials):
            segments.append((segment_name("interstitial", i + 1, i + 2), interstitials[i]))

    segments.append((segment_name("outro"), outro))

    # Save full episode text (this is the transcript)
    full_text = "\n\n---\n\n".join(text for _, text in segments)
    episode_txt_path = episode_dir / "episode.txt"
    episode_txt_path.write_text(full_text)

    episode_words = count_words(full_text)

    if verbose:
        print(f"\n  Episode assembled: {episode_words} words")
        print(f"  Saved to: {episode_txt_path}")

    # Step 6: Generate metadata files (transcript, chapters)
    if verbose:
        print("\n[7/7] GENERATING METADATA FILES...")
    
    # Build segment dicts with estimated timing
    segment_dicts = build_segment_dicts(segments, articles)
    
    # Generate VTT, plain transcript, and JSON chapters
    metadata_files = generate_episode_metadata(
        episode_dir=episode_dir,
        segment_dicts=segment_dicts,
        episode_date=episode_date,
        verbose=verbose,
    )

    # Save manifest
    manifest = {
        "episode_date": episode_date,
        "generated_at": datetime.now().isoformat(),
        "stories": len(articles),
        "scripts_words": total_words,
        "episode_words": episode_words,
        "segments": [name for name, _ in segments],
        "files": {
            "episode": str(episode_txt_path),
            "intro": str(episode_dir / f"{segment_name('intro')}.txt"),
            "outro": str(episode_dir / f"{segment_name('outro')}.txt"),
            "scripts": [str(episode_dir / f"{segment_name('script', i + 1)}.txt") for i in range(len(scripts))],
            "interstitials": [str(episode_dir / f"{segment_name('interstitial', i + 1, i + 2)}.txt") for i in range(len(interstitials))],
            "transcript_vtt": metadata_files["transcript_vtt"],
            "transcript_txt": metadata_files["transcript_txt"],
            "chapters_json": metadata_files["chapters_json"],
        },
    }
    manifest_path = episode_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    if verbose:
        print("\n" + "=" * 70)
        print("PIPELINE COMPLETE")
        print(f"Episode date: {episode_date}")
        print(f"Stories: {len(articles)}")
        print(f"Total words: {episode_words}")
        print(f"Output: {episode_dir}")
        print("=" * 70)

    return manifest


def run_test_pipeline(num_stories: int = 3, verbose: bool = True) -> dict:
    """
    Run a quick test pipeline with fewer stories.

    Args:
        num_stories: Number of stories (default 3 for quick test)
        verbose: Print progress

    Returns:
        Episode manifest
    """
    episode_date = f"test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    return run_episode_pipeline(
        episode_date=episode_date,
        num_stories=num_stories,
        word_target=num_stories * 400,  # ~400 words per story
        verbose=verbose,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # Quick test with 3 stories
        print("Running test pipeline...")
        manifest = run_test_pipeline(num_stories=3)
    else:
        # Full episode
        manifest = run_episode_pipeline()

    print(f"\nManifest: {json.dumps(manifest, indent=2)}")
