"""
Chapter markers for Carlin Podcast.
Handles ID3 chapter embedding and Podcast 2.0 JSON chapters.
"""

import json
from pathlib import Path
from typing import Optional

from mutagen.id3 import ID3, CHAP, CTOC, TIT2, WXXX, CTOCFlags


def segments_to_chapters(
    segments: list[dict],
    stories: list[dict] | None = None,
) -> list[dict]:
    """
    Convert segments list to chapter list (skipping interstitials).
    
    Chapters include: intro, scripts (10), outro
    Skip: interstitials (they're transitions, not chapters)
    
    Args:
        segments: List of segment dicts from storage with:
            - segment_type: "intro", "script", "interstitial", "outro"
            - start_offset_seconds: float
            - duration_seconds: float
            - text: str
            - story_position: int (for scripts)
        stories: Optional list of story dicts with title, id/hn_id, url.
            Used to enrich script chapters with real titles and HN URLs.
            Stories are matched by position (1-indexed, matching story_position).
            
    Returns:
        List of chapter dicts with title, start_time, end_time, url
    """
    # Build position -> story lookup from stories data
    # stories.json uses list order (0-indexed) as position
    # story_position in segments is 1-indexed
    story_lookup: dict[int, dict] = {}
    if stories:
        for i, story in enumerate(stories):
            pos = story.get("position", i + 1)  # position field or 1-indexed from list order
            story_lookup[pos] = story
    
    chapters = []
    
    for seg in segments:
        seg_type = seg.get("segment_type", "")
        
        # Skip interstitials
        if seg_type == "interstitial":
            continue
            
        start = seg.get("start_offset_seconds", 0.0)
        duration = seg.get("duration_seconds", 0.0)
        end = start + duration
        
        if seg_type == "intro":
            title = "Introduction"
            url = None
        elif seg_type == "outro":
            title = "Outro"
            url = None
        elif seg_type == "script":
            story_pos = seg.get("story_position")
            story = story_lookup.get(story_pos, {}) if story_pos else {}
            
            # Use real story title, fall back to segment title, then generic
            title = (
                story.get("title")
                or seg.get("title")
                or f"Story {story_pos or '?'}"
            )
            
            # Build HN URL from story data
            hn_id = story.get("id") or story.get("hn_id")
            if hn_id:
                url = f"https://news.ycombinator.com/item?id={hn_id}"
            else:
                url = seg.get("url")
        else:
            continue  # Unknown type
            
        chapters.append({
            "title": title,
            "start_time": start,
            "end_time": end,
            "url": url,
        })
    
    return chapters


def embed_chapters(
    mp3_path: str,
    segments: list[dict],
    stories: list[dict] | None = None,
) -> None:
    """
    Embed ID3v2 CHAP frames into MP3.
    
    Creates chapter markers that show in podcast apps like Apple Podcasts,
    Overcast, Pocket Casts, etc. (Not Spotify - they don't support ID3 chapters.)
    
    Args:
        mp3_path: Path to MP3 file
        segments: List of segment dicts from storage
        stories: Optional list of story dicts for real titles and HN URLs
        
    Note:
        Chapters are created for intro, each story script, and outro.
        Interstitials are skipped (they're transitions, not chapters).
    """
    chapters = segments_to_chapters(segments, stories=stories)
    
    if not chapters:
        print("  Warning: No chapters to embed")
        return
        
    # Load existing ID3 tags or create new
    try:
        audio = ID3(mp3_path)
    except Exception:
        audio = ID3()
        
    # Remove existing chapters
    audio.delall("CHAP")
    audio.delall("CTOC")
    
    # Add chapter frames
    chapter_ids = []
    
    for i, ch in enumerate(chapters):
        chap_id = f"ch{i}"
        chapter_ids.append(chap_id)
        
        # Times in milliseconds for ID3
        start_ms = int(ch["start_time"] * 1000)
        end_ms = int(ch["end_time"] * 1000)
        
        # Build sub-frames for chapter
        sub_frames = [TIT2(encoding=3, text=ch["title"])]
        
        # Add URL if present
        if ch.get("url"):
            sub_frames.append(WXXX(encoding=3, desc="", url=ch["url"]))
        
        audio.add(CHAP(
            element_id=chap_id,
            start_time=start_ms,
            end_time=end_ms,
            sub_frames=sub_frames,
        ))
    
    # Add table of contents
    audio.add(CTOC(
        element_id="toc",
        flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
        child_element_ids=chapter_ids,
        sub_frames=[TIT2(encoding=3, text="Table of Contents")],
    ))
    
    audio.save(mp3_path)
    print(f"  Embedded {len(chapters)} chapters into MP3")


def load_stories_for_episode(episode_date: str) -> list[dict]:
    """
    Load stories data for an episode from stories.json.
    
    Args:
        episode_date: Episode date string (YYYY-MM-DD)
        
    Returns:
        List of story dicts, or empty list if not found
    """
    stories_path = Path(__file__).parent.parent / "data" / "episodes" / episode_date / "stories.json"
    if stories_path.exists():
        return json.loads(stories_path.read_text())
    return []


def generate_chapters_json(
    segments: list[dict],
    output_path: str,
    podcast_name: str = "Daily Tech Feed",
    episode_title: Optional[str] = None,
    image_url: Optional[str] = None,
    stories: list[dict] | None = None,
) -> dict:
    """
    Generate Podcast 2.0 JSON chapter file.
    
    Format follows: https://github.com/Podcastindex-org/podcast-namespace/blob/main/chapters/jsonChapters.md
    
    Args:
        segments: List of segment dicts from storage
        output_path: Where to save the JSON file
        podcast_name: Name of the podcast
        episode_title: Title for this episode
        image_url: Default image URL for chapters
        stories: Optional list of story dicts for real titles and HN URLs
        
    Returns:
        The chapters dict that was saved
    """
    chapters = segments_to_chapters(segments, stories=stories)
    
    json_chapters = []
    
    for ch in chapters:
        chapter_entry = {
            "startTime": ch["start_time"],
            "title": ch["title"],
        }
        
        # Add URL if present
        if ch.get("url"):
            chapter_entry["url"] = ch["url"]
            
        # Add default image if provided
        if image_url:
            chapter_entry["img"] = image_url
            
        json_chapters.append(chapter_entry)
    
    chapters_doc = {
        "version": "1.2.0",
        "chapters": json_chapters,
    }
    
    # Add optional metadata
    if podcast_name:
        chapters_doc["podcastName"] = podcast_name
    if episode_title:
        chapters_doc["title"] = episode_title
    
    # Write to file
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(chapters_doc, indent=2))
    
    print(f"  Generated chapters.json with {len(json_chapters)} chapters")
    
    return chapters_doc


# ============================================================================
# Testing
# ============================================================================

if __name__ == "__main__":
    # Create test segments
    test_segments = [
        {
            "segment_type": "intro",
            "start_offset_seconds": 0.0,
            "duration_seconds": 45.0,
            "text": "Welcome to the show...",
        },
        {
            "segment_type": "script",
            "story_position": 1,
            "start_offset_seconds": 45.0,
            "duration_seconds": 120.0,
            "text": "First story...",
            "title": "Super Monkey Ball Ported to Web",
            "url": "https://news.ycombinator.com/item?id=12345",
        },
        {
            "segment_type": "interstitial",
            "start_offset_seconds": 165.0,
            "duration_seconds": 15.0,
            "text": "Speaking of games...",
        },
        {
            "segment_type": "script",
            "story_position": 2,
            "start_offset_seconds": 180.0,
            "duration_seconds": 100.0,
            "text": "Second story...",
            "title": "AI Does Something Weird",
            "url": "https://news.ycombinator.com/item?id=12346",
        },
        {
            "segment_type": "outro",
            "start_offset_seconds": 280.0,
            "duration_seconds": 30.0,
            "text": "That's all folks...",
        },
    ]
    
    # Test chapter extraction
    chapters = segments_to_chapters(test_segments)
    print("Extracted chapters:")
    for ch in chapters:
        print(f"  {ch['start_time']:.1f}s - {ch['title']}")
    
    # Test JSON generation
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        json_path = f.name
    
    doc = generate_chapters_json(
        test_segments,
        json_path,
        episode_title="Test Episode",
    )
    
    print(f"\nGenerated JSON at {json_path}:")
    print(json.dumps(doc, indent=2))
    
    print("\n✓ Chapter tests passed")
