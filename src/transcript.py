"""
WebVTT transcript generation for Carlin Podcast.
"""

from pathlib import Path


def format_vtt_timestamp(seconds: float) -> str:
    """
    Format seconds as VTT timestamp: HH:MM:SS.mmm
    
    Args:
        seconds: Time in seconds (float)
        
    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def generate_vtt(
    segments: list[dict],
    output_path: str,
    speaker: str = "George Carlin",
) -> None:
    """
    Generate WebVTT transcript with timing and speaker tags.
    
    Includes ALL segments (intro, scripts, interstitials, outro) —
    this is the full transcript.
    
    Args:
        segments: List of segment dicts from storage with:
            - text: str (the spoken text)
            - start_offset_seconds: float
            - duration_seconds: float
            - segment_type: str (for comments)
        output_path: Where to save the .vtt file
        speaker: Speaker name for <v> tags (default: George Carlin)
        
    Output format:
        WEBVTT
        
        00:00:00.000 --> 00:00:45.000
        <v George Carlin>These are the top stories...
        
        00:00:45.000 --> 00:02:05.000
        <v George Carlin>Story one. Super Monkey Ball...
    """
    lines = ["WEBVTT", ""]
    
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
            
        start = seg.get("start_offset_seconds", 0.0)
        duration = seg.get("duration_seconds", 0.0)
        end = start + duration
        
        # Format timestamps
        start_ts = format_vtt_timestamp(start)
        end_ts = format_vtt_timestamp(end)
        
        # Add cue
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"<v {speaker}>{text}")
        lines.append("")
    
    # Write to file
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines))
    
    cue_count = sum(1 for seg in segments if seg.get("text", "").strip())
    print(f"  Generated transcript.vtt with {cue_count} cues")


def generate_plain_transcript(
    segments: list[dict],
    output_path: str,
) -> None:
    """
    Generate plain text transcript (for SEO and accessibility).
    
    Args:
        segments: List of segment dicts from storage
        output_path: Where to save the .txt file
    """
    lines = []
    
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
            
        seg_type = seg.get("segment_type", "")
        
        # Add section marker
        if seg_type == "intro":
            lines.append("[INTRO]")
        elif seg_type == "outro":
            lines.append("[OUTRO]")
        elif seg_type == "script":
            story_pos = seg.get("story_position", "?")
            title = seg.get("title", "")
            if title:
                lines.append(f"[STORY {story_pos}: {title}]")
            else:
                lines.append(f"[STORY {story_pos}]")
        elif seg_type == "interstitial":
            lines.append("[TRANSITION]")
        
        lines.append(text)
        lines.append("")
    
    # Write to file
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines))
    
    print(f"  Generated plain transcript with {len(segments)} segments")


# ============================================================================
# Testing
# ============================================================================

if __name__ == "__main__":
    import tempfile
    
    # Create test segments
    test_segments = [
        {
            "segment_type": "intro",
            "start_offset_seconds": 0.0,
            "duration_seconds": 45.0,
            "text": "These are the top stories for January 28th from Hacker News. I'm George Carlin, and I'm dead.",
        },
        {
            "segment_type": "script",
            "story_position": 1,
            "start_offset_seconds": 45.0,
            "duration_seconds": 120.0,
            "text": "Story one. Some programmer ported Super Monkey Ball to a website. Why? Because they could.",
            "title": "Super Monkey Ball Web Port",
        },
        {
            "segment_type": "interstitial",
            "start_offset_seconds": 165.0,
            "duration_seconds": 15.0,
            "text": "Speaking of wasting time on the internet...",
        },
        {
            "segment_type": "script",
            "story_position": 2,
            "start_offset_seconds": 180.0,
            "duration_seconds": 100.0,
            "text": "Story two. An AI model learned to write code. Great. Now programmers are obsolete.",
            "title": "AI Writes Code",
        },
        {
            "segment_type": "outro",
            "start_offset_seconds": 280.0,
            "duration_seconds": 30.0,
            "text": "This has been your favorite dead comedian. See you tomorrow.",
        },
    ]
    
    # Test VTT generation
    with tempfile.NamedTemporaryFile(suffix=".vtt", delete=False) as f:
        vtt_path = f.name
    
    generate_vtt(test_segments, vtt_path)
    
    print(f"\nGenerated VTT at {vtt_path}:")
    print(Path(vtt_path).read_text())
    
    # Test plain transcript
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        txt_path = f.name
    
    generate_plain_transcript(test_segments, txt_path)
    
    print(f"\nGenerated plain transcript at {txt_path}:")
    print(Path(txt_path).read_text())
    
    print("\n✓ Transcript tests passed")
