#!/usr/bin/env python3
"""
Upload DTFHN episode to Cloudflare R2 and regenerate RSS feed.

Uploads:
  1. Episode MP3 → dtfhn/episodes/DTFHN-{date}.mp3
  2. RSS feed   → dtfhn/feed.xml

Usage:
  python3 scripts/upload_to_r2.py 2026-01-29-1448
  python3 scripts/upload_to_r2.py 2026-01-29-1448 --mp3 /path/to/episode.mp3
  python3 scripts/upload_to_r2.py --feed-only  # Just regenerate and upload feed

Environment variables required:
  CF_R2_ACCESS_KEY_ID     - R2 S3-compatible Access Key ID
  CF_R2_SECRET_ACCESS_KEY - R2 S3-compatible Secret Access Key
  CF_ACCOUNT_ID           - Cloudflare Account ID (optional, defaults to known value)
"""

import argparse
import os
import sys
import tempfile
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


def upload_episode(s3_client, episode_date: str, mp3_path: str = None):
    """Upload an episode MP3 to R2.

    If mp3_path is not provided, tries:
    1. data/episodes/{date}/DTFHN-{date}.mp3
    2. data/episodes/{date}/episode.mp3
    3. LanceDB mp3_binary
    """
    r2_key = f"{R2_PREFIX}/episodes/DTFHN-{episode_date}.mp3"

    if mp3_path and Path(mp3_path).exists():
        upload_file(s3_client, mp3_path, r2_key, content_type="audio/mpeg")
        return

    # Try filesystem paths
    episode_dir = Path(__file__).resolve().parent.parent / "data" / "episodes" / episode_date
    candidates = [
        episode_dir / f"DTFHN-{episode_date}.mp3",
        episode_dir / "episode.mp3",
    ]
    for candidate in candidates:
        if candidate.exists():
            upload_file(s3_client, str(candidate), r2_key, content_type="audio/mpeg")
            return

    # Fall back to LanceDB
    print(f"  No MP3 file found on disk, trying LanceDB...")
    from src.storage import get_episode_mp3
    mp3_bytes = get_episode_mp3(episode_date)
    if mp3_bytes:
        upload_bytes(s3_client, mp3_bytes, r2_key, content_type="audio/mpeg")
        return

    print(f"  ERROR: No MP3 found for episode {episode_date}")
    sys.exit(1)


def upload_feed(s3_client):
    """Regenerate and upload the RSS feed."""
    from src.feed import generate_feed

    print("  Generating RSS feed...")
    xml_str = generate_feed()
    feed_bytes = xml_str.encode("utf-8")

    r2_key = f"{R2_PREFIX}/feed.xml"
    upload_bytes(s3_client, feed_bytes, r2_key, content_type="application/rss+xml; charset=utf-8")
    print(f"  ✓ Feed uploaded ({len(feed_bytes):,} bytes)")


def main():
    parser = argparse.ArgumentParser(description="Upload DTFHN episode to R2")
    parser.add_argument("episode_date", nargs="?", help="Episode date (YYYY-MM-DD or YYYY-MM-DD-HHMM)")
    parser.add_argument("--mp3", help="Path to MP3 file (auto-detected if omitted)")
    parser.add_argument("--feed-only", action="store_true", help="Only regenerate and upload feed")
    parser.add_argument("--no-feed", action="store_true", help="Skip feed regeneration")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without uploading")
    args = parser.parse_args()

    if not args.feed_only and not args.episode_date:
        parser.error("episode_date is required unless --feed-only is set")

    if args.dry_run:
        print("DRY RUN — no uploads will be performed")
        if args.episode_date:
            print(f"  Would upload: DTFHN-{args.episode_date}.mp3 → {R2_PREFIX}/episodes/")
        if not args.no_feed:
            print(f"  Would upload: feed.xml → {R2_PREFIX}/feed.xml")
        return

    s3 = get_s3_client()

    # Upload episode MP3
    if not args.feed_only:
        print(f"\n[1/2] Uploading episode: {args.episode_date}")
        upload_episode(s3, args.episode_date, args.mp3)

    # Upload feed
    if not args.no_feed:
        step = "2/2" if not args.feed_only else "1/1"
        print(f"\n[{step}] Uploading RSS feed")
        upload_feed(s3)

    print("\n✓ Done!")
    if args.episode_date:
        print(f"  Episode: https://podcast.pdxh.org/dtfhn/episodes/DTFHN-{args.episode_date}.mp3")
    print(f"  Feed:    https://podcast.pdxh.org/dtfhn/feed.xml")


if __name__ == "__main__":
    main()
