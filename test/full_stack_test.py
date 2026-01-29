#!/usr/bin/env python3
"""
Full-stack test for Carlin podcast.
Uses REAL Hacker News top 10 stories.
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

# Config
OUTPUT_DIR = Path(__file__).parent / "output" / "full_episode"
TTS_URL = "http://192.168.0.134:7849/speak"
CLI_TIMEOUT = 180  # 3 min per call (real articles need more time)

HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

# Static intro/outro (from test_pipeline.py)
INTRO = """Welcome to another episode of News From The Edge, where we take a look at the 
absolute circus that passes for news these days. I'm your host, coming to you from beyond 
the grave, because apparently even death can't stop me from pointing out the obvious."""

OUTRO = """And that's all the time we have for today's descent into madness. Remember, 
the world is run by people who got C's in high school, and somehow we're all surprised 
when things go wrong. Until next time, try not to let the bastards grind you down."""

# Carlin system prompt
CARLIN_SYSTEM_PROMPT = """You are George Carlin writing a segment for your news commentary podcast.

## Carlin's Voice
- Observational, bemused, cynical
- Punch up at institutions, not down at people
- Profanity is spice, not the meal
- Short punchy sentences
- Find the absurdity, don't manufacture it

## Output
Write ONLY the script text. No preamble, no commentary, no markdown."""


# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class Comment:
    id: str
    author: str
    text: str
    depth: int


@dataclass
class Story:
    id: str
    title: str
    url: str
    score: int
    comment_count: int
    author: str
    article_text: str
    fetch_status: str
    comments: list[Comment] = field(default_factory=list)
    hn_text: str = ""


# =============================================================================
# HN API Functions
# =============================================================================
def fetch_hn_api(url: str) -> Any:
    """Fetch from HN API with retry."""
    for attempt in range(3):
        try:
            time.sleep(0.1)  # Rate limit
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  Retry {attempt + 1}/3: {e}")
            time.sleep(1)
    return None


def fetch_top_story_ids(limit: int = 10) -> list[int]:
    """Fetch top story IDs from HN."""
    print(f"Fetching top {limit} story IDs...")
    story_ids = fetch_hn_api(HN_TOP_STORIES_URL)
    if story_ids:
        return story_ids[:limit]
    return []


def fetch_item(item_id: int) -> dict | None:
    """Fetch a single item from HN."""
    url = HN_ITEM_URL.format(item_id=item_id)
    return fetch_hn_api(url)


def fetch_article_text(url: str) -> tuple[str, str]:
    """Extract article text from URL. Returns (text, status)."""
    if not url:
        return "", "no_url"
    
    try:
        time.sleep(0.5)  # Rate limit
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove script/style
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        
        # Get text from article or body
        article = soup.find("article")
        if article:
            text = article.get_text(separator=" ", strip=True)
        else:
            # Fallback to paragraphs
            paragraphs = soup.find_all("p")
            text = " ".join(p.get_text(strip=True) for p in paragraphs)
        
        # Clean up
        text = " ".join(text.split())
        
        if len(text) > 200:
            return text[:8000], "full"  # Truncate for token budget
        return "", "too_short"
        
    except Exception as e:
        print(f"    Article fetch failed: {e}")
        return "", "failed"


def fetch_comments(story_id: str, comment_ids: list[int], max_comments: int = 10) -> list[Comment]:
    """Fetch top-level comments for a story."""
    comments = []
    for cid in comment_ids[:max_comments]:
        item = fetch_item(cid)
        if not item or item.get("deleted") or item.get("dead"):
            continue
        
        text = item.get("text", "")
        if text:
            # Clean HTML from comment
            soup = BeautifulSoup(text, "html.parser")
            clean_text = soup.get_text(separator=" ", strip=True)
            
            comments.append(Comment(
                id=str(item.get("id", "")),
                author=item.get("by", "[deleted]"),
                text=clean_text[:500],  # Truncate long comments
                depth=0,
            ))
    
    return comments


def fetch_stories(limit: int = 10) -> list[Story]:
    """Fetch top HN stories with articles and comments."""
    story_ids = fetch_top_story_ids(limit)
    if not story_ids:
        print("ERROR: No story IDs fetched!")
        return []
    
    stories = []
    for idx, story_id in enumerate(story_ids):
        print(f"\nFetching story {idx + 1}/{limit}: {story_id}")
        
        item = fetch_item(story_id)
        if not item or item.get("type") != "story":
            print("  Skipping non-story item")
            continue
        
        title = item.get("title", "")
        url = item.get("url", "")
        print(f"  Title: {title[:60]}...")
        
        # Fetch article
        article_text, fetch_status = fetch_article_text(url)
        print(f"  Article: {fetch_status} ({len(article_text)} chars)")
        
        # Fetch comments
        comment_ids = item.get("kids", [])
        comments = fetch_comments(str(story_id), comment_ids)
        print(f"  Comments: {len(comments)}")
        
        story = Story(
            id=str(item.get("id", "")),
            title=title,
            url=url,
            score=item.get("score", 0),
            comment_count=item.get("descendants", 0),
            author=item.get("by", ""),
            article_text=article_text,
            fetch_status=fetch_status,
            comments=comments,
            hn_text=item.get("text", ""),
        )
        stories.append(story)
    
    return stories


# =============================================================================
# Script Generation
# =============================================================================
def call_claude(prompt: str) -> str:
    """Call Claude via CLI."""
    full_prompt = f"{CARLIN_SYSTEM_PROMPT}\n\n---\n\n{prompt}"
    
    result = subprocess.run(
        ["claude", "-p", full_prompt],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr or result.stdout}")
    
    return result.stdout.strip()


def generate_article_script(story: Story) -> str:
    """Generate 5-paragraph Carlin script for one story."""
    
    # Build content section
    if story.article_text:
        content = story.article_text[:4000]
    elif story.hn_text:
        content = f"[HN Post text]: {story.hn_text[:2000]}"
    else:
        content = f"[Title only - no article text available]"
    
    # Build comments section
    if story.comments:
        comments_text = "\n".join(f"- {c.text[:200]}" for c in story.comments[:6])
    else:
        comments_text = "- [No comments available]"
    
    prompt = f"""Write a 5-paragraph segment about this article:

ARTICLE: {story.title}
Score: {story.score} points | {story.comment_count} comments

{content}

COMMENTS FROM READERS:
{comments_text}

Structure:
1. What happened (the news)
2. Key players involved  
3. Why this matters (or why it's absurd)
4. Broader context
5. What the comments reveal about people

Write the script now."""

    return call_claude(prompt)


def generate_interstitial(script1: str, script2: str, article2_title: str) -> str:
    """Generate 1-2 sentence transition between articles."""
    prompt = f"""Write a 1-2 sentence transition between podcast segments.

PREVIOUS SEGMENT (just finished):
{script1[-500:]}

NEXT SEGMENT TOPIC: {article2_title}

Write a quick Carlin-style pivot. 15-30 words max. Just the transition, nothing else."""

    return call_claude(prompt)


# =============================================================================
# TTS and Audio
# =============================================================================
def text_to_speech(text: str, output_path: Path) -> bool:
    """Call TTS API and save WAV."""
    try:
        response = requests.post(
            TTS_URL,
            headers={"Content-Type": "application/json"},
            json={"text": text},
            timeout=300,  # 5 min timeout for long segments
        )
        response.raise_for_status()
        output_path.write_bytes(response.content)
        print(f"  → {output_path.name} ({len(response.content):,} bytes)")
        return True
    except Exception as e:
        print(f"  ERROR: TTS failed for {output_path.name}: {e}")
        return False


def stitch_wavs(wav_files: list[Path], output_path: Path) -> bool:
    """Concatenate WAV files using ffmpeg."""
    list_file = OUTPUT_DIR / "files.txt"
    with open(list_file, "w") as f:
        for wav in wav_files:
            f.write(f"file '{wav.absolute()}'\n")
    
    result = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy", str(output_path)
    ], capture_output=True)
    
    list_file.unlink()
    
    if result.returncode == 0:
        print(f"  → {output_path.name}")
        return True
    else:
        print(f"  ERROR: ffmpeg stitch failed: {result.stderr.decode()}")
        return False


def transcode_to_mp3(wav_path: Path, mp3_path: Path) -> bool:
    """Convert WAV to MP3."""
    result = subprocess.run([
        "ffmpeg", "-y", "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-qscale:a", "2",
        str(mp3_path)
    ], capture_output=True)
    
    if result.returncode == 0:
        print(f"  → {mp3_path.name}")
        return True
    else:
        print(f"  ERROR: ffmpeg transcode failed: {result.stderr.decode()}")
        return False


# =============================================================================
# Main
# =============================================================================
def main():
    start_time = datetime.now()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("CARLIN PODCAST - FULL STACK TEST (REAL HN DATA)")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Step 1: Fetch real HN stories
    print("\n[1/8] FETCHING HN STORIES...")
    stories = fetch_stories(limit=10)
    
    if len(stories) < 10:
        print(f"WARNING: Only got {len(stories)} stories")
    
    # Save stories for debugging
    stories_data = [
        {
            "id": s.id,
            "title": s.title,
            "url": s.url,
            "score": s.score,
            "fetch_status": s.fetch_status,
            "article_chars": len(s.article_text),
            "comments": len(s.comments),
        }
        for s in stories
    ]
    (OUTPUT_DIR / "stories.json").write_text(json.dumps(stories_data, indent=2))
    print(f"\nFetched {len(stories)} stories")
    
    # Step 2: Generate article scripts
    print("\n[2/8] GENERATING ARTICLE SCRIPTS...")
    scripts = []
    for i, story in enumerate(stories):
        print(f"\n  Script {i + 1}/{len(stories)}: {story.title[:50]}...")
        try:
            script = generate_article_script(story)
            scripts.append(script)
            (OUTPUT_DIR / f"script_{i + 1}.txt").write_text(script)
            print(f"    Done ({len(script)} chars)")
        except Exception as e:
            print(f"    ERROR: {e}")
            scripts.append(f"[Script generation failed for: {story.title}]")
    
    # Step 3: Generate interstitials
    print("\n[3/8] GENERATING INTERSTITIALS...")
    interstitials = []
    for i in range(len(scripts) - 1):
        print(f"  Interstitial {i + 1}-{i + 2}...")
        try:
            interstitial = generate_interstitial(
                scripts[i],
                scripts[i + 1],
                stories[i + 1].title if i + 1 < len(stories) else "Next topic"
            )
            interstitials.append(interstitial)
            (OUTPUT_DIR / f"interstitial_{i + 1}_{i + 2}.txt").write_text(interstitial)
            print(f"    Done ({len(interstitial)} chars)")
        except Exception as e:
            print(f"    ERROR: {e}")
            interstitials.append("Moving on to the next story...")
    
    # Step 4: Build segment list
    print("\n[4/8] ASSEMBLING SEGMENTS...")
    segments = []
    segments.append(("00_intro", INTRO))
    
    for i, script in enumerate(scripts):
        segments.append((f"{(i * 2 + 1):02d}_script_{i + 1}", script))
        if i < len(interstitials):
            segments.append((f"{(i * 2 + 2):02d}_interstitial_{i + 1}_{i + 2}", interstitials[i]))
    
    segments.append((f"{len(segments):02d}_outro", OUTRO))
    
    print(f"  {len(segments)} segments total:")
    print(f"    - 1 intro")
    print(f"    - {len(scripts)} scripts")
    print(f"    - {len(interstitials)} interstitials")
    print(f"    - 1 outro")
    
    # Step 5: TTS each segment
    print("\n[5/8] GENERATING AUDIO (TTS)...")
    wav_files = []
    for name, text in segments:
        wav_path = OUTPUT_DIR / f"{name}.wav"
        if text_to_speech(text, wav_path):
            wav_files.append(wav_path)
    
    if len(wav_files) != len(segments):
        print(f"WARNING: Only {len(wav_files)}/{len(segments)} WAVs generated")
    
    # Step 6: Stitch WAVs
    print("\n[6/8] STITCHING AUDIO...")
    episode_wav = OUTPUT_DIR / "episode.wav"
    if not stitch_wavs(wav_files, episode_wav):
        print("ERROR: Stitching failed!")
        return
    
    # Step 7: Transcode to MP3
    print("\n[7/8] TRANSCODING TO MP3...")
    episode_mp3 = OUTPUT_DIR / "episode.mp3"
    if not transcode_to_mp3(episode_wav, episode_mp3):
        print("ERROR: Transcode failed!")
        return
    
    # Step 8: Send to Signal
    print("\n[8/8] SENDING TO SIGNAL...")
    # Signal sending will be done via clawdbot message tool
    
    end_time = datetime.now()
    duration = end_time - start_time
    
    print("\n" + "=" * 70)
    print("COMPLETE!")
    print(f"Duration: {duration}")
    print(f"Output: {episode_mp3}")
    print(f"Size: {episode_mp3.stat().st_size / 1024 / 1024:.1f} MB")
    print("=" * 70)
    
    return str(episode_mp3)


if __name__ == "__main__":
    main()
