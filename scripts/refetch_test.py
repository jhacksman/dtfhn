#!/usr/bin/env python3
"""
Re-fetch all 10 stories to test the full fallback chain.
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scraper import fetch_article_text

def main():
    # Load existing stories
    stories_path = Path(__file__).parent.parent / "data/episodes/2026-01-27/stories.json"
    with open(stories_path) as f:
        stories = json.load(f)
    
    print(f"Re-fetching {len(stories)} stories...\n")
    print("=" * 80)
    
    results = []
    for i, story in enumerate(stories):
        story_id = story["id"]
        title = story["title"][:60] + "..." if len(story["title"]) > 60 else story["title"]
        url = story["url"]
        hn_text = story.get("hn_text", "")
        old_status = story.get("fetch_status", "unknown")
        old_len = len(story.get("article_text", ""))
        
        print(f"\n[{i+1}/{len(stories)}] {title}")
        print(f"  URL: {url}")
        print(f"  Old: {old_status} ({old_len} chars)")
        if hn_text:
            print(f"  HN text (has alt URLs): {len(hn_text)} chars")
        
        # Re-fetch with full fallback chain
        new_text, new_status = fetch_article_text(url, hn_text=hn_text)
        new_len = len(new_text)
        
        print(f"  New: {new_status} ({new_len} chars)")
        
        # Determine if improved, regressed, or same
        status_rank = {"title_only": 0, "failed": 0, "full_alt": 1, "full_archive": 2, "full_js": 3, "full": 4}
        old_rank = status_rank.get(old_status, 0)
        new_rank = status_rank.get(new_status, 0)
        
        if new_rank > old_rank:
            change = "IMPROVED ✓"
        elif new_rank < old_rank:
            change = "REGRESSED ✗"
        elif new_len > old_len + 100:
            change = "MORE CONTENT +"
        elif new_len < old_len - 100:
            change = "LESS CONTENT -"
        else:
            change = "SAME"
        
        print(f"  Result: {change}")
        
        # Preview of new content if it's new or changed
        if new_status != "title_only" and new_text:
            preview = new_text[:150].replace("\n", " ")
            print(f"  Preview: {preview}...")
        
        # Store result
        result = {
            "id": story_id,
            "title": story["title"],
            "url": url,
            "old_status": old_status,
            "old_length": old_len,
            "new_status": new_status,
            "new_length": new_len,
            "change": change,
            "article_text": new_text,
            "comments": story.get("comments", []),
            "score": story.get("score", 0),
            "comment_count": story.get("comment_count", 0),
            "author": story.get("author", ""),
            "hn_text": hn_text,
            "fetch_status": new_status,
        }
        results.append(result)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    improved = [r for r in results if "IMPROVED" in r["change"]]
    regressed = [r for r in results if "REGRESSED" in r["change"]]
    title_only = [r for r in results if r["new_status"] == "title_only"]
    
    print(f"\nImproved: {len(improved)}")
    for r in improved:
        print(f"  - {r['title'][:50]}: {r['old_status']} → {r['new_status']}")
    
    print(f"\nRegressed: {len(regressed)}")
    for r in regressed:
        print(f"  - {r['title'][:50]}: {r['old_status']} → {r['new_status']}")
    
    print(f"\nStill title_only: {len(title_only)}")
    for r in title_only:
        print(f"  - {r['title'][:50]} ({r['url'][:50]}...)")
    
    # Status breakdown
    print("\nStatus breakdown:")
    from collections import Counter
    status_counts = Counter(r["new_status"] for r in results)
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {status}: {count}")
    
    # Save results
    output_path = Path(__file__).parent.parent / "data/episodes/2026-01-27/stories_refetch.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to: {output_path}")
    
    return results


if __name__ == "__main__":
    main()
