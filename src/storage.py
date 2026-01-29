"""
Storage layer for Carlin Podcast.
Handles episodes and stories tables in LanceDB.

Schema v2: 2 tables
- episodes: One per day, contains MP3 binary
- stories: 10 per day, article + script + archive

WAV files are ephemeral - delete after MP3 is created.
"""

import gzip
import json
from datetime import datetime
from typing import Optional
import pyarrow as pa
import lancedb

from .embeddings import get_db, embed_text, embed_batch, search, EMBEDDING_DIM


# ============================================================================
# Schema Version
# ============================================================================

SCHEMA_VERSION = 2


# ============================================================================
# Table Schemas
# ============================================================================

EPISODES_SCHEMA = pa.schema([
    pa.field("episode_date", pa.string()),          # PK: "2025-01-27"
    pa.field("mp3_binary", pa.binary()),            # Final episode MP3
    pa.field("transcript", pa.string()),            # Full episode text
    pa.field("duration_seconds", pa.float32()),     # Total audio length
    pa.field("word_count", pa.int32()),             # Total words spoken
    pa.field("story_count", pa.int32()),            # Number of stories (default 10)
    pa.field("generated_at", pa.string()),          # ISO timestamp
    pa.field("schema_version", pa.int32()),         # For migrations
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),  # Transcript embedding
])

STORIES_SCHEMA = pa.schema([
    pa.field("id", pa.string()),                    # PK: "2025-01-27-01"
    pa.field("episode_date", pa.string()),          # Links to episodes
    pa.field("position", pa.int32()),               # Story order 1-10
    pa.field("hn_id", pa.string()),                 # HN story ID
    pa.field("title", pa.string()),                 # Article title
    pa.field("url", pa.string()),                   # Original article URL
    pa.field("author", pa.string()),                # HN submitter
    pa.field("score", pa.int32()),                  # HN points
    pa.field("archive_gzip", pa.binary()),          # Gzipped raw HTML
    pa.field("fetch_status", pa.string()),          # "full", "full_js", "title_only", "failed"
    pa.field("article_text", pa.string()),          # Extracted article text
    pa.field("comments_json", pa.string()),         # JSON array of comment dicts
    pa.field("script", pa.string()),                # Generated Carlin script
    pa.field("script_word_count", pa.int32()),      # Words in script
    pa.field("interstitial_next", pa.string()),     # Transition to next story (null for #10)
    pa.field("article_vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
    pa.field("script_vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
    pa.field("schema_version", pa.int32()),
])


SEGMENTS_SCHEMA = pa.schema([
    # Identity
    pa.field("id", pa.string()),                    # "YYYY-MM-DD-intro", "YYYY-MM-DD-script-01", etc.
    pa.field("episode_date", pa.string()),          # Links to episodes table
    
    # Segment info
    pa.field("segment_type", pa.string()),          # "intro", "script", "interstitial", "outro"
    pa.field("position", pa.int32()),               # 0 for intro, 1-10 for scripts, 1-9 for interstitials, 99 for outro
    pa.field("story_position", pa.int32()),         # Which story (1-10), null for intro/outro
    
    # Content
    pa.field("text", pa.string()),                  # The text that was spoken
    pa.field("word_count", pa.int32()),             # Words in this segment
    
    # Audio metadata
    pa.field("duration_seconds", pa.float32()),     # Length of audio
    pa.field("start_offset_seconds", pa.float32()), # Start position in final MP3
    
    # TTS metadata
    pa.field("tts_model", pa.string()),             # e.g., "f5-tts"
    pa.field("voice", pa.string()),                 # e.g., "george_carlin"
    pa.field("generated_at", pa.string()),          # ISO timestamp
    
    # Schema version
    pa.field("schema_version", pa.int32()),
])


# ============================================================================
# Table Accessors
# ============================================================================

def get_episodes_table() -> lancedb.table.Table:
    """Get or create the episodes table."""
    db = get_db()
    if "episodes" in db.table_names():
        return db.open_table("episodes")
    return db.create_table("episodes", schema=EPISODES_SCHEMA)


def get_stories_table() -> lancedb.table.Table:
    """Get or create the stories table."""
    db = get_db()
    if "stories" in db.table_names():
        return db.open_table("stories")
    return db.create_table("stories", schema=STORIES_SCHEMA)


def get_segments_table() -> lancedb.table.Table:
    """Get or create the segments table."""
    db = get_db()
    if "segments" in db.table_names():
        return db.open_table("segments")
    return db.create_table("segments", schema=SEGMENTS_SCHEMA)


# ============================================================================
# Utility Functions
# ============================================================================

def compress_html(raw_html: Optional[str]) -> Optional[bytes]:
    """Compress raw HTML to gzip bytes for storage."""
    if not raw_html:
        return None
    return gzip.compress(raw_html.encode("utf-8"))


def decompress_html(archive_gzip: Optional[bytes]) -> Optional[str]:
    """Decompress gzipped HTML from storage."""
    if not archive_gzip:
        return None
    return gzip.decompress(archive_gzip).decode("utf-8")


def make_story_id(episode_date: str, position: int) -> str:
    """Create story ID from date and position."""
    return f"{episode_date}-{position:02d}"


def make_segment_id(
    episode_date: str,
    segment_type: str,
    story_position: Optional[int] = None,
    next_story_position: Optional[int] = None,
) -> str:
    """
    Create segment ID from date and type.
    
    Formats:
    - Intro: "2026-01-27-intro"
    - Scripts: "2026-01-27-script-01" through "2026-01-27-script-10"
    - Interstitials: "2026-01-27-inter-01-02" (between story 1 and 2)
    - Outro: "2026-01-27-outro"
    """
    if segment_type == "intro":
        return f"{episode_date}-intro"
    elif segment_type == "outro":
        return f"{episode_date}-outro"
    elif segment_type == "script":
        if story_position is None:
            raise ValueError("story_position required for script segment")
        return f"{episode_date}-script-{story_position:02d}"
    elif segment_type == "interstitial":
        if story_position is None or next_story_position is None:
            raise ValueError("story_position and next_story_position required for interstitial")
        return f"{episode_date}-inter-{story_position:02d}-{next_story_position:02d}"
    else:
        raise ValueError(f"Unknown segment type: {segment_type}")


# ============================================================================
# Episode CRUD
# ============================================================================

def store_episode(
    episode_date: str,
    mp3_binary: bytes,
    transcript: str,
    duration_seconds: float,
    story_count: int = 10,
) -> None:
    """
    Store an episode with its MP3 and transcript.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"
        mp3_binary: Final MP3 as bytes
        transcript: Full episode text
        duration_seconds: Total audio length
        story_count: Number of stories (default 10)
    """
    table = get_episodes_table()
    vector = embed_text(transcript)
    word_count = len(transcript.split())
    generated_at = datetime.now().isoformat()

    table.add([{
        "episode_date": episode_date,
        "mp3_binary": mp3_binary,
        "transcript": transcript,
        "duration_seconds": duration_seconds,
        "word_count": word_count,
        "story_count": story_count,
        "generated_at": generated_at,
        "schema_version": SCHEMA_VERSION,
        "vector": vector,
    }])


def get_episode(episode_date: str) -> Optional[dict]:
    """
    Get an episode by date.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"

    Returns:
        Episode dict or None if not found
    """
    table = get_episodes_table()
    results = table.search().where(
        f"episode_date = '{episode_date}'", prefilter=True
    ).limit(1).to_list()
    return results[0] if results else None


def get_episode_mp3(episode_date: str) -> Optional[bytes]:
    """
    Get just the MP3 binary for an episode.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"

    Returns:
        MP3 bytes or None if not found
    """
    episode = get_episode(episode_date)
    return episode["mp3_binary"] if episode else None


def episode_exists(episode_date: str) -> bool:
    """Check if an episode exists."""
    return get_episode(episode_date) is not None


def search_episodes(query: str, top_k: int = 10) -> list[dict]:
    """
    Search episodes by semantic similarity to transcript.

    Args:
        query: Text to search for
        top_k: Number of results

    Returns:
        List of episode dicts with _distance score (mp3_binary excluded for performance)
    """
    table = get_episodes_table()
    results = search(table, query, top_k)
    # Remove large binary from search results
    for r in results:
        r.pop("mp3_binary", None)
    return results


def list_episodes() -> list[dict]:
    """
    List all episodes (without MP3 binary).

    Returns:
        List of episode dicts sorted by date descending
    """
    table = get_episodes_table()
    results = table.to_arrow().to_pylist()
    # Remove large binary from list results
    for r in results:
        r.pop("mp3_binary", None)
    results.sort(key=lambda x: x["episode_date"], reverse=True)
    return results


# ============================================================================
# Story CRUD
# ============================================================================

def store_story(
    episode_date: str,
    position: int,
    hn_id: str,
    title: str,
    url: str,
    author: str = "",
    score: int = 0,
    article_text: str = "",
    comments: Optional[list[dict]] = None,
    raw_html: Optional[str] = None,
    fetch_status: str = "title_only",
    script: str = "",
    interstitial_next: Optional[str] = None,
) -> None:
    """
    Store a story with embeddings.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"
        position: Story order (1-10)
        hn_id: HN story ID
        title: Article title
        url: Original article URL
        author: HN submitter
        score: HN points
        article_text: Extracted article text
        comments: List of comment dicts
        raw_html: Raw HTML to archive (will be gzip compressed)
        fetch_status: How content was fetched
        script: Generated Carlin script
        interstitial_next: Transition to next story (null for #10)
    """
    table = get_stories_table()

    story_id = make_story_id(episode_date, position)
    comments_json = json.dumps(comments or [])
    archive_gzip = compress_html(raw_html)
    script_word_count = len(script.split()) if script else 0

    # Generate embeddings
    article_embed_text = f"{title}\n\n{article_text}" if article_text else title
    article_vector = embed_text(article_embed_text)
    script_vector = embed_text(script) if script else [0.0] * EMBEDDING_DIM

    table.add([{
        "id": story_id,
        "episode_date": episode_date,
        "position": position,
        "hn_id": hn_id,
        "title": title,
        "url": url,
        "author": author,
        "score": score,
        "archive_gzip": archive_gzip,
        "fetch_status": fetch_status,
        "article_text": article_text,
        "comments_json": comments_json,
        "script": script,
        "script_word_count": script_word_count,
        "interstitial_next": interstitial_next,
        "article_vector": article_vector,
        "script_vector": script_vector,
        "schema_version": SCHEMA_VERSION,
    }])


def store_stories_batch(stories: list[dict]) -> None:
    """
    Store multiple stories in a batch.

    Args:
        stories: List of dicts with story fields
    """
    if not stories:
        return

    table = get_stories_table()

    # Prepare texts for batch embedding
    article_texts = []
    script_texts = []
    for s in stories:
        article_text = s.get("article_text", "")
        title = s.get("title", "")
        article_embed = f"{title}\n\n{article_text}" if article_text else title
        article_texts.append(article_embed)
        script_texts.append(s.get("script", "") or "")

    article_vectors = embed_batch(article_texts)
    script_vectors = embed_batch(script_texts)

    records = []
    for i, s in enumerate(stories):
        story_id = make_story_id(s["episode_date"], s["position"])
        script = s.get("script", "") or ""
        
        # Use zero vector for empty scripts
        script_vec = script_vectors[i] if script else [0.0] * EMBEDDING_DIM

        records.append({
            "id": story_id,
            "episode_date": s["episode_date"],
            "position": s["position"],
            "hn_id": s["hn_id"],
            "title": s["title"],
            "url": s["url"],
            "author": s.get("author", ""),
            "score": s.get("score", 0),
            "archive_gzip": compress_html(s.get("raw_html")),
            "fetch_status": s.get("fetch_status", "title_only"),
            "article_text": s.get("article_text", ""),
            "comments_json": json.dumps(s.get("comments", [])),
            "script": script,
            "script_word_count": len(script.split()) if script else 0,
            "interstitial_next": s.get("interstitial_next"),
            "article_vector": article_vectors[i],
            "script_vector": script_vec,
            "schema_version": SCHEMA_VERSION,
        })

    table.add(records)


def update_story_script(
    episode_date: str,
    position: int,
    script: str,
    interstitial_next: Optional[str] = None,
) -> None:
    """
    Update a story's script and interstitial.

    Note: LanceDB doesn't support true updates, so this adds a new row.
    Query functions should handle potential duplicates by taking the latest.
    """
    # Get existing story
    story = get_story(episode_date, position)
    if not story:
        raise ValueError(f"Story not found: {episode_date}-{position:02d}")

    # Re-store with updated script
    store_story(
        episode_date=episode_date,
        position=position,
        hn_id=story["hn_id"],
        title=story["title"],
        url=story["url"],
        author=story.get("author", ""),
        score=story.get("score", 0),
        article_text=story.get("article_text", ""),
        comments=json.loads(story.get("comments_json", "[]")),
        raw_html=decompress_html(story.get("archive_gzip")),
        fetch_status=story.get("fetch_status", "title_only"),
        script=script,
        interstitial_next=interstitial_next,
    )


def get_story(episode_date: str, position: int) -> Optional[dict]:
    """
    Get a specific story.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"
        position: Story order (1-10)

    Returns:
        Story dict or None if not found
    """
    table = get_stories_table()
    story_id = make_story_id(episode_date, position)
    results = table.search().where(
        f"id = '{story_id}'", prefilter=True
    ).limit(1).to_list()

    if results:
        r = results[0]
        if "comments_json" in r:
            r["comments"] = json.loads(r["comments_json"])
    return results[0] if results else None


def get_stories_by_date(episode_date: str, include_archive: bool = False) -> list[dict]:
    """
    Get all stories for an episode date.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"
        include_archive: If True, decompress and include raw HTML

    Returns:
        List of story dicts sorted by position
    """
    table = get_stories_table()
    results = table.search().where(
        f"episode_date = '{episode_date}'", prefilter=True
    ).limit(100).to_list()

    for r in results:
        if "comments_json" in r:
            r["comments"] = json.loads(r["comments_json"])
        if include_archive and r.get("archive_gzip"):
            r["raw_html"] = decompress_html(r["archive_gzip"])

    return sorted(results, key=lambda x: x.get("position", 0))


def story_exists(episode_date: str, position: int) -> bool:
    """Check if a story slot is already filled."""
    return get_story(episode_date, position) is not None


def search_stories(
    query: str,
    top_k: int = 10,
    vector_column: str = "article_vector"
) -> list[dict]:
    """
    Search stories by semantic similarity.

    Args:
        query: Text to search for
        top_k: Number of results
        vector_column: "article_vector" or "script_vector"

    Returns:
        List of story dicts with _distance score
    """
    table = get_stories_table()
    query_vector = embed_text(query)
    results = table.search(query_vector, vector_column_name=vector_column).limit(top_k).to_list()

    for r in results:
        if "comments_json" in r:
            r["comments"] = json.loads(r["comments_json"])

    return results


def get_existing_hn_ids() -> set[str]:
    """Get set of HN IDs already in the database."""
    try:
        db = get_db()
        if "stories" not in db.table_names():
            return set()
        table = db.open_table("stories")
        arrow_table = table.to_arrow()
        if arrow_table.num_rows == 0:
            return set()
        return set(arrow_table.column("hn_id").to_pylist())
    except Exception:
        return set()


# ============================================================================
# Segment CRUD
# ============================================================================

def store_segment(
    episode_date: str,
    segment_type: str,
    position: int,
    text: str,
    duration_seconds: float,
    start_offset_seconds: float = 0.0,
    story_position: Optional[int] = None,
    next_story_position: Optional[int] = None,
    tts_model: str = "f5-tts",
    voice: str = "george_carlin",
) -> str:
    """
    Store a segment with metadata.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"
        segment_type: "intro", "script", "interstitial", or "outro"
        position: Ordering position (0=intro, 1-10=scripts, 11-19=interstitials, 99=outro)
        text: The text that was spoken
        duration_seconds: Length of audio
        start_offset_seconds: Start position in final MP3
        story_position: Which story (1-10), None for intro/outro
        next_story_position: For interstitials, the next story number
        tts_model: TTS model used (default "f5-tts")
        voice: Voice used (default "george_carlin")

    Returns:
        The segment ID
    """
    table = get_segments_table()
    
    segment_id = make_segment_id(
        episode_date, segment_type, story_position, next_story_position
    )
    word_count = len(text.split()) if text else 0
    generated_at = datetime.now().isoformat()

    table.add([{
        "id": segment_id,
        "episode_date": episode_date,
        "segment_type": segment_type,
        "position": position,
        "story_position": story_position,
        "text": text,
        "word_count": word_count,
        "duration_seconds": duration_seconds,
        "start_offset_seconds": start_offset_seconds,
        "tts_model": tts_model,
        "voice": voice,
        "generated_at": generated_at,
        "schema_version": SCHEMA_VERSION,
    }])
    
    return segment_id


def store_segments_batch(segments: list[dict]) -> list[str]:
    """
    Store multiple segments in a batch.

    Args:
        segments: List of dicts with segment fields:
            - episode_date (required)
            - segment_type (required): "intro", "script", "interstitial", "outro"
            - position (required): ordering position
            - text (required): spoken text
            - duration_seconds (required)
            - start_offset_seconds (optional, default 0.0)
            - story_position (optional): for script/interstitial
            - next_story_position (optional): for interstitial
            - tts_model (optional, default "f5-tts")
            - voice (optional, default "george_carlin")

    Returns:
        List of segment IDs created
    """
    if not segments:
        return []

    table = get_segments_table()
    generated_at = datetime.now().isoformat()
    
    records = []
    segment_ids = []
    
    for s in segments:
        segment_id = make_segment_id(
            s["episode_date"],
            s["segment_type"],
            s.get("story_position"),
            s.get("next_story_position"),
        )
        segment_ids.append(segment_id)
        text = s.get("text", "") or ""
        
        records.append({
            "id": segment_id,
            "episode_date": s["episode_date"],
            "segment_type": s["segment_type"],
            "position": s["position"],
            "story_position": s.get("story_position"),
            "text": text,
            "word_count": len(text.split()) if text else 0,
            "duration_seconds": s["duration_seconds"],
            "start_offset_seconds": s.get("start_offset_seconds", 0.0),
            "tts_model": s.get("tts_model", "f5-tts"),
            "voice": s.get("voice", "george_carlin"),
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
        })

    table.add(records)
    return segment_ids


def get_segment(segment_id: str) -> Optional[dict]:
    """
    Get a segment by its ID.

    Args:
        segment_id: Segment ID (e.g., "2026-01-27-intro")

    Returns:
        Segment dict or None if not found
    """
    table = get_segments_table()
    results = table.search().where(
        f"id = '{segment_id}'", prefilter=True
    ).limit(1).to_list()
    return results[0] if results else None


def get_episode_segments(episode_date: str) -> list[dict]:
    """
    Get all segments for an episode, ordered by position.

    Args:
        episode_date: Episode date string "YYYY-MM-DD" or "YYYY-MM-DD-HHMM"

    Returns:
        List of segment dicts sorted by position (all 21 segments for a complete episode)
    """
    table = get_segments_table()
    results = table.search().where(
        f"episode_date = '{episode_date}'", prefilter=True
    ).limit(100).to_list()

    return sorted(results, key=lambda x: x.get("position", 0))


# ============================================================================
# Migration from v1 Schema
# ============================================================================

def migrate_from_v1() -> dict:
    """
    Migrate from v1 schema (articles + scripts tables) to v2 (episodes + stories).

    Returns:
        Dict with migration stats
    """
    db = get_db()
    stats = {"articles_migrated": 0, "scripts_merged": 0, "errors": []}

    # Check for old tables
    if "articles" not in db.table_names():
        return {"status": "no_migration_needed", "reason": "articles table not found"}

    # Read old data
    old_articles = db.open_table("articles").to_arrow().to_pylist()
    old_scripts = {}
    if "scripts" in db.table_names():
        for s in db.open_table("scripts").to_arrow().to_pylist():
            key = (s["episode_date"], s["story_number"])
            old_scripts[key] = s

    # Ensure new tables exist
    get_stories_table()

    # Migrate articles to stories
    for article in old_articles:
        try:
            episode_date = article["episode_date"]
            story_number = article["story_number"]
            
            # Get matching script
            script_data = old_scripts.get((episode_date, story_number), {})

            # Extract HN ID from source_id (e.g., "hn-12345" -> "12345")
            source_id = article.get("source_id", "")
            hn_id = source_id.replace("hn-", "") if source_id.startswith("hn-") else source_id

            store_story(
                episode_date=episode_date,
                position=story_number,
                hn_id=hn_id,
                title=article["title"],
                url=article.get("source_url", ""),
                article_text=article.get("content", ""),
                comments=json.loads(article.get("comments_json", "[]")),
                raw_html=decompress_html(article.get("archive_gzip")),
                fetch_status=article.get("fetch_status", "title_only"),
                script=script_data.get("script_text", ""),
            )
            stats["articles_migrated"] += 1
            if script_data:
                stats["scripts_merged"] += 1

        except Exception as e:
            stats["errors"].append(f"{article.get('source_id', 'unknown')}: {e}")

    return stats


# ============================================================================
# Backward Compatibility (deprecated, use new functions)
# ============================================================================

def get_articles_table():
    """Deprecated: Use get_stories_table instead."""
    return get_stories_table()


def get_scripts_table():
    """Deprecated: Scripts are now part of stories table."""
    return get_stories_table()


def get_existing_source_ids() -> set[str]:
    """Deprecated: Use get_existing_hn_ids instead."""
    hn_ids = get_existing_hn_ids()
    return {f"hn-{id}" for id in hn_ids}


# ============================================================================
# Test
# ============================================================================

if __name__ == "__main__":
    import tempfile
    import os

    print("Testing storage layer v2...")
    print("=" * 50)

    episode_date = "2025-01-28"

    # Test story storage
    print("\n1. Testing story storage...")
    store_story(
        episode_date=episode_date,
        position=1,
        hn_id="12345",
        title="Test Article About AI",
        url="https://example.com/ai-article",
        author="testuser",
        score=100,
        article_text="This is a test article about artificial intelligence.",
        comments=[{"author": "commenter1", "text": "Great article!"}],
        raw_html="<html><body>Test HTML</body></html>",
        fetch_status="full",
        script="You know what's funny about AI? Everything!",
        interstitial_next="Speaking of AI, let me tell you about the next thing...",
    )
    print("   ✓ Story stored")

    # Verify story retrieval
    story = get_story(episode_date, 1)
    assert story is not None, "Story not found"
    assert story["hn_id"] == "12345"
    assert story["title"] == "Test Article About AI"
    assert story["script"] == "You know what's funny about AI? Everything!"
    assert "comments" in story
    print("   ✓ Story retrieved and verified")

    # Test story search
    print("\n2. Testing story search...")
    results = search_stories("artificial intelligence", top_k=5)
    assert len(results) > 0, "No search results"
    print(f"   ✓ Found {len(results)} results for 'artificial intelligence'")

    # Test script search
    results = search_stories("funny", top_k=5, vector_column="script_vector")
    assert len(results) > 0, "No script search results"
    print(f"   ✓ Found {len(results)} results for 'funny' in scripts")

    # Test episode storage
    print("\n3. Testing episode storage...")
    test_mp3 = b"FAKE_MP3_DATA_FOR_TESTING_" * 1000  # ~26KB fake MP3
    test_transcript = "This is the full episode transcript. " * 100

    store_episode(
        episode_date=episode_date,
        mp3_binary=test_mp3,
        transcript=test_transcript,
        duration_seconds=1234.5,
        story_count=1,
    )
    print("   ✓ Episode stored")

    # Verify episode retrieval
    episode = get_episode(episode_date)
    assert episode is not None, "Episode not found"
    assert episode["mp3_binary"] == test_mp3, "MP3 binary mismatch"
    assert episode["duration_seconds"] == 1234.5
    print("   ✓ Episode retrieved and verified")
    print(f"   ✓ MP3 binary round-trip: {len(test_mp3)} bytes")

    # Test MP3 retrieval
    mp3_bytes = get_episode_mp3(episode_date)
    assert mp3_bytes == test_mp3, "MP3 retrieval mismatch"
    print("   ✓ get_episode_mp3() works")

    # Test list episodes (should exclude mp3_binary)
    print("\n4. Testing episode listing...")
    episodes = list_episodes()
    assert len(episodes) > 0
    assert "mp3_binary" not in episodes[0], "mp3_binary should be excluded from list"
    print(f"   ✓ Listed {len(episodes)} episodes (mp3_binary excluded)")

    # Test episode search
    results = search_episodes("episode transcript", top_k=5)
    assert len(results) > 0
    assert "mp3_binary" not in results[0], "mp3_binary should be excluded from search"
    print(f"   ✓ Episode search works (mp3_binary excluded)")

    print("\n" + "=" * 50)
    print("All tests passed! ✓")
