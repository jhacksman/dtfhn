"""
Hacker News API client for Carlin Podcast.
Fetches top stories with article content and comments.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from .scraper import fetch_article_text as scrape_article

# HN API endpoints
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

# Rate limiting
API_DELAY = 0.1  # seconds between API calls
FETCH_DELAY = 0.5  # seconds between article fetches

# User agent for article fetching
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass
class Comment:
    """A HN comment."""
    id: str
    author: str
    text: str
    depth: int = 0


@dataclass
class Story:
    """A HN story with metadata, article content, and comments."""
    id: str
    title: str
    url: str
    score: int
    comment_count: int
    author: str
    article_text: str
    fetch_status: str  # "full", "full_js", "title_only", "failed", "no_url"
    raw_html: Optional[str] = None  # Raw HTML for archiving
    comments: list[Comment] = field(default_factory=list)
    hn_text: str = ""  # For Ask HN / Show HN posts with body text


def fetch_hn_api(url: str, retries: int = 3) -> Any:
    """Fetch from HN API with retry."""
    for attempt in range(retries):
        try:
            time.sleep(API_DELAY)
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"  HN API fetch failed after {retries} attempts: {e}")
    return None


def fetch_top_story_ids(limit: int = 10) -> list[int]:
    """Fetch top story IDs from HN."""
    story_ids = fetch_hn_api(HN_TOP_STORIES_URL)
    if story_ids:
        return story_ids[:limit]
    return []


def fetch_item(item_id: int) -> Optional[dict]:
    """Fetch a single item from HN."""
    url = HN_ITEM_URL.format(item_id=item_id)
    return fetch_hn_api(url)


def fetch_article_with_html(url: str, hn_text: str = "") -> tuple[str, str, Optional[str]]:
    """
    Fetch article text using the multi-tier scraper, plus raw HTML for archiving.

    Args:
        url: Article URL to fetch
        hn_text: HN post text that may contain alternative URLs

    Returns:
        Tuple of (extracted_text, status, raw_html)
        - status: "full", "full_js", "full_archive", "full_alt", "title_only", "no_url"
    """
    if not url:
        return "", "no_url", None

    # Fetch raw HTML for archiving (simple GET, may fail but that's okay)
    raw_html = None
    try:
        time.sleep(FETCH_DELAY)
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, timeout=15, headers=headers)
        if response.status_code == 200:
            raw_html = response.text
    except Exception:
        pass  # Raw HTML is optional, don't fail the whole fetch

    # Use the multi-tier scraper for actual content extraction
    text, status = scrape_article(url, hn_text=hn_text)
    
    # Truncate for token budget
    if text:
        text = text[:8000]
    
    return text, status, raw_html


def fetch_comments(comment_ids: list[int], max_comments: int = 10) -> list[Comment]:
    """
    Fetch top-level comments for a story.

    Args:
        comment_ids: List of comment IDs
        max_comments: Maximum comments to fetch

    Returns:
        List of Comment objects
    """
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


def fetch_stories(limit: int = 10, verbose: bool = True) -> list[Story]:
    """
    Fetch top HN stories with articles and comments.

    Args:
        limit: Number of stories to fetch
        verbose: Print progress

    Returns:
        List of Story objects
    """
    if verbose:
        print(f"Fetching top {limit} story IDs...")

    story_ids = fetch_top_story_ids(limit)
    if not story_ids:
        print("ERROR: No story IDs fetched!")
        return []

    stories = []
    for idx, story_id in enumerate(story_ids):
        if verbose:
            print(f"\nFetching story {idx + 1}/{limit}: {story_id}")

        item = fetch_item(story_id)
        if not item or item.get("type") != "story":
            if verbose:
                print("  Skipping non-story item")
            continue

        title = item.get("title", "")
        url = item.get("url", "")

        if verbose:
            print(f"  Title: {title[:60]}...")

        # Get HN post text (for Ask HN / Show HN posts, may contain alt URLs)
        hn_text = item.get("text", "")

        # Fetch article using multi-tier scraper
        article_text, fetch_status, raw_html = fetch_article_with_html(url, hn_text=hn_text)
        if verbose:
            print(f"  Article: {fetch_status} ({len(article_text)} chars)")

        # Fetch comments
        comment_ids = item.get("kids", [])
        comments = fetch_comments(comment_ids)
        if verbose:
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
            raw_html=raw_html,
            comments=comments,
            hn_text=item.get("text", ""),  # For Ask HN / Show HN
        )
        stories.append(story)

    return stories


def story_to_article_dict(story: Story, episode_date: str, story_number: int) -> dict:
    """
    Convert a Story to an article dict for storage.

    Args:
        story: Story object
        episode_date: Episode date string "YYYY-MM-DD"
        story_number: Position in episode (1-10)

    Returns:
        Dict ready for store_article() or store_articles_batch()
    """
    # Convert comments to list of dicts
    comments = [
        {"id": c.id, "author": c.author, "text": c.text, "depth": c.depth}
        for c in story.comments
    ]

    # Use HN text for Ask HN / Show HN posts without external URL
    content = story.article_text or story.hn_text or ""

    return {
        "episode_date": episode_date,
        "story_number": story_number,
        "source_id": f"hn-{story.id}",
        "source_url": story.url or f"https://news.ycombinator.com/item?id={story.id}",
        "title": story.title,
        "content": content,
        "comments": comments,
        "raw_html": story.raw_html,
        "fetch_status": story.fetch_status,
    }


if __name__ == "__main__":
    # Quick test
    print("Testing HN client...")
    stories = fetch_stories(limit=3, verbose=True)

    print(f"\nFetched {len(stories)} stories:")
    for s in stories:
        print(f"  - {s.title[:50]}... ({s.fetch_status}, {len(s.comments)} comments)")
