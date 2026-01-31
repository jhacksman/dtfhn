#!/usr/bin/env python3
"""
Upload DTFHN episode to Cloudflare R2 and regenerate RSS feed.

Uploads:
  1. Episode MP3 → dtfhn/episodes/DTFHN-{date}.mp3
  2. RSS feed   → dtfhn/feed.xml

The upload script also registers the episode in data/feed_episodes.json
(the manifest), then regenerates the feed from that manifest.

Usage:
  python3 scripts/upload_to_r2.py 2026-01-29-1448
  python3 scripts/upload_to_r2.py 2026-01-29-1448 --mp3 /path/to/episode.mp3
  python3 scripts/upload_to_r2.py 2026-01-29-1448 --title "DTF:HN for January 29, 2026"
  python3 scripts/upload_to_r2.py 2026-01-29-1448 --description "Coverage of..."
  python3 scripts/upload_to_r2.py --feed-only  # Just regenerate and upload feed

Environment variables required:
  CF_R2_ACCESS_KEY_ID     - R2 S3-compatible Access Key ID
  CF_R2_SECRET_ACCESS_KEY - R2 S3-compatible Secret Access Key
  CF_ACCOUNT_ID           - Cloudflare Account ID (optional, defaults to known value)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# R2 configuration
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "2b7b028350f44113131ef2aaf0155ca5")
R2_ENDPOINT = f"https://{CF_ACCOUNT_ID}.r2.cloudflarestorage.com"
R2_BUCKET = "dtf-podcasts"
R2_PREFIX = "dtfhn"


def get_s3_client():
    """Create boto3 S3 client for R2."""
    import boto3

    access_key = os.environ.get("CF_R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("CF_R2_SECRET_ACCESS_KEY")

    if not access_key or not secret_key:
        print("ERROR: Missing R2 credentials. Set these env vars:")
        print("  CF_R2_ACCESS_KEY_ID")
        print("  CF_R2_SECRET_ACCESS_KEY")
        print()
        print("Create R2 API tokens at:")
        print("  https://dash.cloudflare.com/ → R2 → Manage R2 API Tokens")
        print("  Choose 'S3 Auth' type (NOT Bearer token)")
        sys.exit(1)

    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def upload_file(s3_client, local_path: str, r2_key: str, content_type: str = "application/octet-stream"):
    """Upload a file to R2."""
    print(f"  Uploading {local_path} → s3://{R2_BUCKET}/{r2_key}")
    s3_client.upload_file(
        local_path,
        R2_BUCKET,
        r2_key,
        ExtraArgs={"ContentType": content_type},
    )
    print(f"  ✓ Uploaded ({Path(local_path).stat().st_size:,} bytes)")


def upload_bytes(s3_client, data: bytes, r2_key: str, content_type: str = "application/octet-stream"):
    """Upload bytes to R2."""
    print(f"  Uploading {len(data):,} bytes → s3://{R2_BUCKET}/{r2_key}")
    s3_client.put_object(
        Bucket=R2_BUCKET,
        Key=r2_key,
        Body=data,
        ContentType=content_type,
    )
    print(f"  ✓ Uploaded")


def generate_episode_description(episode_date: str) -> str | None:
    """Generate a description from the episode's stories.json.

    Format:
        Your Daily Tech Feed covering the top N stories on Hacker News for {date}.
        Featuring: {title1}, {title2}, {title3}, and more.

        Stories covered:
        1. {title1}
           {article_url}
           HN discussion: https://news.ycombinator.com/item?id={hn_id}
        2. {title2}
           ...

    The first line (prose summary) stays within ~600 chars for Spotify preview.
    Total description kept under 4,000 chars (Apple Podcasts limit).
    Plaintext only — no HTML, no markdown. Apps auto-linkify URLs.

    Returns None if stories.json is not found.
    """
    episode_dir = Path(__file__).resolve().parent.parent / "data" / "episodes" / episode_date
    stories_path = episode_dir / "stories.json"

    if not stories_path.exists():
        return None

    stories = json.loads(stories_path.read_text(encoding="utf-8"))
    if not stories:
        return None

    # Human-readable date from episode_date
    date_part = episode_date[:10]
    dt = datetime.strptime(date_part, "%Y-%m-%d")
    human_date = f"{dt.strftime('%B')} {dt.day}, {dt.year}"

    story_count = len(stories)
    titles = [s.get("title", "") for s in stories if s.get("title")]

    # Build prose summary (first line — what Spotify shows in 600-char preview)
    for num_titles in range(min(5, len(titles)), 0, -1):
        featured = ", ".join(titles[:num_titles])
        suffix = ", and more" if len(titles) > num_titles else ""
        prose = (
            f"Your Daily Tech Feed covering the top {story_count} stories "
            f"on Hacker News for {human_date}. "
            f"Featuring: {featured}{suffix}."
        )
        if len(prose) <= 600:
            break
    else:
        prose = f"Your Daily Tech Feed covering the top {story_count} stories on Hacker News for {human_date}."

    # Build numbered story list with URLs
    CHAR_LIMIT = 4000
    story_lines = []
    for i, story in enumerate(stories, 1):
        title = story.get("title", f"Story {i}")
        url = story.get("url", "")
        hn_id = story.get("id", "")

        entry = f"{i}. {title}"
        if url:
            entry += f"\n   {url}"
        if hn_id:
            entry += f"\n   HN discussion: https://news.ycombinator.com/item?id={hn_id}"

        story_lines.append(entry)

    # Assemble full description, truncating story list if over limit
    header = f"{prose}\n\nStories covered:\n"
    while story_lines:
        body = "\n\n".join(story_lines)
        full_desc = header + body
        if len(full_desc) <= CHAR_LIMIT:
            return full_desc
        # Remove last story to fit
        story_lines.pop()

    # Fallback: just the prose summary
    return prose


def generate_content_encoded(episode_date: str) -> str | None:
    """Generate an HTML-formatted description for <content:encoded>.

    Progressive enhancement: apps that support HTML get clickable links.
    The plain <description> also has URLs as plaintext fallback.

    Returns None if stories.json is not found.
    """
    episode_dir = Path(__file__).resolve().parent.parent / "data" / "episodes" / episode_date
    stories_path = episode_dir / "stories.json"

    if not stories_path.exists():
        return None

    stories = json.loads(stories_path.read_text(encoding="utf-8"))
    if not stories:
        return None

    date_part = episode_date[:10]
    dt = datetime.strptime(date_part, "%Y-%m-%d")
    human_date = f"{dt.strftime('%B')} {dt.day}, {dt.year}"

    story_count = len(stories)
    titles = [s.get("title", "") for s in stories if s.get("title")]

    # Prose summary
    for num_titles in range(min(5, len(titles)), 0, -1):
        featured = ", ".join(titles[:num_titles])
        suffix = ", and more" if len(titles) > num_titles else ""
        prose = (
            f"Your Daily Tech Feed covering the top {story_count} stories "
            f"on Hacker News for {human_date}. "
            f"Featuring: {featured}{suffix}."
        )
        if len(prose) <= 600:
            break
    else:
        prose = f"Your Daily Tech Feed covering the top {story_count} stories on Hacker News for {human_date}."

    # Build HTML story list
    import html as html_mod
    lines = [f"<p>{html_mod.escape(prose)}</p>", "<p><strong>Stories covered:</strong></p>", "<ol>"]

    for story in stories:
        title = html_mod.escape(story.get("title", "Untitled"))
        url = story.get("url", "")
        hn_id = story.get("id", "")

        li = f"<li>{title}"
        links = []
        if url:
            links.append(f'<a href="{html_mod.escape(url)}">Article</a>')
        if hn_id:
            hn_url = f"https://news.ycombinator.com/item?id={hn_id}"
            links.append(f'<a href="{hn_url}">HN Discussion</a>')
        if links:
            li += f"<br/>({' | '.join(links)})"
        li += "</li>"
        lines.append(li)

    lines.append("</ol>")
    return "\n".join(lines)


def find_mp3(episode_date: str, mp3_path: str = None) -> Path:
    """Find the MP3 file for an episode.

    Checks in order:
    1. Explicit --mp3 path
    2. data/episodes/{date}/DTFHN-{date}.mp3
    3. data/episodes/{date}/episode.mp3

    Returns the path or exits with error.
    """
    if mp3_path:
        p = Path(mp3_path)
        if p.exists():
            return p
        print(f"  ERROR: Specified MP3 not found: {mp3_path}")
        sys.exit(1)

    episode_dir = Path(__file__).resolve().parent.parent / "data" / "episodes" / episode_date
    candidates = [
        episode_dir / f"DTFHN-{episode_date}.mp3",
        episode_dir / "episode.mp3",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    print(f"  ERROR: No MP3 found for episode {episode_date}")
    print(f"  Looked in: {episode_dir}")
    sys.exit(1)


def get_mp3_duration(mp3_path: Path) -> int:
    """Get MP3 duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-show_entries",
                "format=duration", "-of", "csv=p=0", str(mp3_path),
            ],
            capture_output=True, text=True, check=True,
        )
        return int(float(result.stdout.strip()))
    except Exception as e:
        print(f"  Warning: Could not get duration via ffprobe: {e}")
        return 0


def format_episode_title(episode_date: str) -> str:
    """Format a clean episode title from the date string.

    '2026-01-29-1448' → 'DTF:HN for January 29, 2026'
    """
    date_part = episode_date[:10]
    dt = datetime.strptime(date_part, "%Y-%m-%d")
    return f"DTF:HN for {dt.strftime('%B')} {dt.day}, {dt.year}"


def format_pub_date(episode_date: str) -> str:
    """Format an ISO 8601 pub_date from the episode date string.

    '2026-01-29-1448' → '2026-01-29T14:48:00Z'
    """
    date_part = episode_date[:10]
    dt = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if len(episode_date) > 10:
        time_part = episode_date[11:]
        if len(time_part) == 4 and time_part.isdigit():
            dt = dt.replace(hour=int(time_part[:2]), minute=int(time_part[2:]))

    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def register_episode(
    episode_date: str,
    mp3_path: Path,
    title: str = None,
    description: str = None,
) -> list[dict]:
    """Register an episode in the manifest (data/feed_episodes.json).

    Computes filesize and duration from the MP3 file.
    Returns the updated manifest.
    """
    from src.feed import add_episode_to_manifest

    if not title:
        title = format_episode_title(episode_date)

    if not description:
        description = generate_episode_description(episode_date)

    content_encoded = generate_content_encoded(episode_date)

    mp3_filename = f"DTFHN-{episode_date}.mp3"
    filesize = mp3_path.stat().st_size
    duration = get_mp3_duration(mp3_path)
    pub_date = format_pub_date(episode_date)

    return add_episode_to_manifest(
        date=episode_date,
        title=title,
        mp3_filename=mp3_filename,
        filesize_bytes=filesize,
        duration_seconds=duration,
        pub_date=pub_date,
        description=description,
        content_encoded=content_encoded,
    )


def upload_episode(s3_client, episode_date: str, mp3_path: Path):
    """Upload an episode MP3 to R2."""
    r2_key = f"{R2_PREFIX}/episodes/DTFHN-{episode_date}.mp3"
    upload_file(s3_client, str(mp3_path), r2_key, content_type="audio/mpeg")


def find_chapters(episode_date: str) -> Path | None:
    """Find the chapters JSON file for an episode."""
    episode_dir = Path(__file__).resolve().parent.parent / "data" / "episodes" / episode_date
    chapters_path = episode_dir / "chapters.json"
    if chapters_path.exists():
        return chapters_path
    return None


def upload_chapters(s3_client, episode_date: str, chapters_path: Path):
    """Upload a chapters JSON file to R2."""
    r2_key = f"{R2_PREFIX}/chapters/DTFHN-{episode_date}-chapters.json"
    upload_file(s3_client, str(chapters_path), r2_key, content_type="application/json")


def find_transcript(episode_date: str) -> Path | None:
    """Find the VTT transcript file for an episode.

    Returns the path or None if not found.
    """
    episode_dir = Path(__file__).resolve().parent.parent / "data" / "episodes" / episode_date
    vtt_path = episode_dir / "transcript.vtt"
    if vtt_path.exists():
        return vtt_path
    return None


def upload_transcript(s3_client, episode_date: str, vtt_path: Path):
    """Upload a transcript VTT file to R2."""
    r2_key = f"{R2_PREFIX}/transcripts/DTFHN-{episode_date}.vtt"
    upload_file(s3_client, str(vtt_path), r2_key, content_type="text/vtt")


def upload_feed(s3_client):
    """Regenerate and upload the RSS feed."""
    from src.feed import generate_feed

    print("  Generating RSS feed from manifest...")
    xml_str = generate_feed()
    feed_bytes = xml_str.encode("utf-8")

    r2_key = f"{R2_PREFIX}/feed.xml"
    upload_bytes(s3_client, feed_bytes, r2_key, content_type="application/rss+xml; charset=utf-8")
    print(f"  ✓ Feed uploaded ({len(feed_bytes):,} bytes)")


def main():
    parser = argparse.ArgumentParser(description="Upload DTFHN episode to R2")
    parser.add_argument("episode_date", nargs="?", help="Episode date (YYYY-MM-DD or YYYY-MM-DD-HHMM)")
    parser.add_argument("--mp3", help="Path to MP3 file (auto-detected if omitted)")
    parser.add_argument("--title", help="Episode title (auto-generated if omitted)")
    parser.add_argument("--description", help="Episode description for the feed")
    parser.add_argument("--feed-only", action="store_true", help="Only regenerate and upload feed")
    parser.add_argument("--no-feed", action="store_true", help="Skip feed regeneration")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without uploading")
    args = parser.parse_args()

    if not args.feed_only and not args.episode_date:
        parser.error("episode_date is required unless --feed-only is set")

    if args.dry_run:
        print("DRY RUN — no uploads will be performed")
        if args.episode_date:
            mp3 = find_mp3(args.episode_date, args.mp3)
            print(f"  Would upload: {mp3} → {R2_PREFIX}/episodes/DTFHN-{args.episode_date}.mp3")
            print(f"  Would register in manifest: data/feed_episodes.json")
        if not args.no_feed:
            print(f"  Would upload: feed.xml → {R2_PREFIX}/feed.xml")
        return

    s3 = get_s3_client()

    # Upload episode MP3
    if not args.feed_only:
        print(f"\n[1/5] Finding episode MP3: {args.episode_date}")
        mp3_path = find_mp3(args.episode_date, args.mp3)
        print(f"  Found: {mp3_path}")

        print(f"\n[2/5] Registering episode in manifest")
        register_episode(
            args.episode_date,
            mp3_path,
            title=args.title,
            description=args.description,
        )

        print(f"\n[3/5] Uploading episode: {args.episode_date}")
        upload_episode(s3, args.episode_date, mp3_path)

        print(f"\n[4/5] Uploading chapters: {args.episode_date}")
        chapters_path = find_chapters(args.episode_date)
        if chapters_path:
            upload_chapters(s3, args.episode_date, chapters_path)
        else:
            print(f"  No chapters.json found for {args.episode_date}, skipping.")

        print(f"\n[5/5] Uploading transcript: {args.episode_date}")
        vtt_path = find_transcript(args.episode_date)
        if vtt_path:
            upload_transcript(s3, args.episode_date, vtt_path)
        else:
            print(f"  No transcript.vtt found for {args.episode_date}, skipping.")
    else:
        print()

    # Upload feed
    if not args.no_feed:
        step = "Feed" if args.feed_only else "Feed update"
        print(f"\n[{step}] Uploading RSS feed")
        upload_feed(s3)

    print("\n✓ Done!")
    if args.episode_date:
        print(f"  Episode: https://podcast.pdxh.org/dtfhn/episodes/DTFHN-{args.episode_date}.mp3")
    print(f"  Feed:    https://podcast.pdxh.org/dtfhn/feed.xml")


if __name__ == "__main__":
    main()
