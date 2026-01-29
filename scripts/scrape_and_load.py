#!/usr/bin/env python3
"""
Scrape top 10 HN stories and load into LanceDB.
"""

import sys
import json
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.hn import fetch_stories
from src.storage import (
    get_stories_table, store_stories_batch, get_stories_by_date, get_db, _table_names
)


def clear_test_data():
    """Clear any existing test/today data from stories table."""
    print("=" * 60)
    print("Step 1: Clearing old data")
    print("=" * 60)
    
    db = get_db()
    if "stories" not in _table_names(db):
        print("  No stories table exists yet - nothing to clear")
        return
    
    table = db.open_table("stories")
    count = table.count_rows()
    print(f"  Current stories count: {count}")
    
    if count > 0:
        # Delete the entire table and recreate
        db.drop_table("stories")
        print("  Dropped stories table to start fresh")


def fetch_and_store(episode_date: str):
    """Fetch top 10 stories and store in LanceDB."""
    print("\n" + "=" * 60)
    print("Step 2: Fetching top 10 HN stories")
    print("=" * 60)
    
    stories = fetch_stories(limit=10, verbose=True)
    
    if not stories:
        print("ERROR: No stories fetched!")
        return []
    
    print(f"\nFetched {len(stories)} stories")
    
    print("\n" + "=" * 60)
    print("Step 3: Storing in LanceDB")
    print("=" * 60)
    
    # Convert to storage format
    storage_records = []
    for idx, story in enumerate(stories, start=1):
        position = idx
        
        # Convert comments to dict format
        comments = [
            {"id": c.id, "author": c.author, "text": c.text, "depth": c.depth}
            for c in story.comments
        ]
        
        # Use HN text for Ask HN / Show HN posts without external URL
        article_text = story.article_text or story.hn_text or ""
        
        record = {
            "episode_date": episode_date,
            "position": position,
            "hn_id": story.id,
            "title": story.title,
            "url": story.url or f"https://news.ycombinator.com/item?id={story.id}",
            "author": story.author,
            "score": story.score,
            "article_text": article_text,
            "comments": comments,
            "raw_html": story.raw_html,
            "fetch_status": story.fetch_status,
        }
        storage_records.append(record)
        
        print(f"  Prepared story {position}: {story.title[:50]}...")
    
    # Store batch
    print(f"\n  Storing {len(storage_records)} stories with embeddings...")
    store_stories_batch(storage_records)
    print("  ✓ Batch stored successfully")
    
    return storage_records


def verify(episode_date: str):
    """Verify all stories were stored correctly."""
    print("\n" + "=" * 60)
    print("Step 4: Verifying stored data")
    print("=" * 60)
    
    stories = get_stories_by_date(episode_date)
    
    print(f"\n  Retrieved {len(stories)} stories from LanceDB")
    print("\n" + "-" * 90)
    print(f"{'Pos':>3} | {'ID':15} | {'Status':12} | {'Text Len':>8} | {'Cmts':>4} | {'Archive':>7} | Title")
    print("-" * 90)
    
    all_ok = True
    for story in stories:
        pos = story.get("position", "?")
        story_id = story.get("id", "?")
        status = story.get("fetch_status", "?")
        text_len = len(story.get("article_text", "") or "")
        comments = story.get("comments", [])
        comment_count = len(comments) if isinstance(comments, list) else 0
        archive = story.get("archive_gzip")
        archive_str = f"{len(archive):,}B" if archive else "None"
        title = story.get("title", "")[:40]
        
        # Check vector exists
        vector = story.get("article_vector")
        has_vector = vector is not None and len(vector) > 0
        
        if not has_vector:
            all_ok = False
            title += " [NO VECTOR!]"
        
        print(f"{pos:>3} | {story_id:15} | {status:12} | {text_len:>8} | {comment_count:>4} | {archive_str:>7} | {title}")
    
    print("-" * 90)
    
    if len(stories) == 10 and all_ok:
        print("\n✓ SUCCESS: All 10 stories loaded correctly with vectors!")
    else:
        print(f"\n⚠ WARNING: Expected 10 stories, got {len(stories)}")
        if not all_ok:
            print("  Some stories are missing vectors!")
    
    return stories


def main():
    # Use today's date
    episode_date = datetime.now().strftime("%Y-%m-%d-%H%M")
    print(f"\nEpisode date: {episode_date}")
    
    # Run pipeline
    clear_test_data()
    records = fetch_and_store(episode_date)
    
    if records:
        stories = verify(episode_date)
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        for story in stories:
            pos = story.get("position", "?")
            status = story.get("fetch_status", "?")
            text_len = len(story.get("article_text", "") or "")
            comments = story.get("comments", [])
            comment_count = len(comments) if isinstance(comments, list) else 0
            title = story.get("title", "")
            
            print(f"\n{pos}. {title}")
            print(f"   ID: {story.get('id')} | Status: {status}")
            print(f"   Article: {text_len:,} chars | Comments: {comment_count}")


if __name__ == "__main__":
    main()
