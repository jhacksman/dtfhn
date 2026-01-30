"""
RSS feed generator for Daily Tech Feed: Hacker News podcast.

Generates a valid RSS 2.0 feed with iTunes namespace for podcast directories.
Episodes are sourced ONLY from the explicit manifest at data/feed_episodes.json.
No auto-discovery, no database scanning, no directory walking.
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from typing import Optional

from .metadata import PODCAST_METADATA

# Project root (dtfhn/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Manifest path
MANIFEST_PATH = PROJECT_ROOT / "data" / "feed_episodes.json"

# R2 / public URL configuration
R2_BASE_URL = "https://podcast.pdxh.org/dtfhn"
EPISODES_URL = f"{R2_BASE_URL}/episodes"
FEED_URL = f"{R2_BASE_URL}/feed.xml"
ARTWORK_URL = f"{R2_BASE_URL}/artwork.jpg"

# iTunes XML namespace
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"

# Default episode description when manifest entry lacks one
DEFAULT_EPISODE_DESCRIPTION = "Daily coverage of the top 10 stories on Hacker News."


def load_manifest() -> list[dict]:
    """Load the episode manifest from data/feed_episodes.json.

    Returns an empty list if the file doesn't exist or is empty.
    """
    if not MANIFEST_PATH.exists():
        return []
    text = MANIFEST_PATH.read_text(encoding="utf-8").strip()
    if not text:
        return []
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    return data


def save_manifest(episodes: list[dict]) -> None:
    """Save the episode manifest to data/feed_episodes.json."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(episodes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def add_episode_to_manifest(
    date: str,
    title: str,
    mp3_filename: str,
    filesize_bytes: int,
    duration_seconds: int,
    pub_date: str,
    description: Optional[str] = None,
) -> list[dict]:
    """Add an episode to the manifest. Prevents duplicates by date.

    Returns the updated manifest.
    """
    episodes = load_manifest()

    # Prevent duplicates
    existing_dates = {ep.get("date") for ep in episodes}
    if date in existing_dates:
        print(f"  Episode {date} already in manifest, skipping.")
        return episodes

    entry = {
        "date": date,
        "title": title,
        "description": description or DEFAULT_EPISODE_DESCRIPTION,
        "mp3_filename": mp3_filename,
        "filesize_bytes": filesize_bytes,
        "duration_seconds": duration_seconds,
        "pub_date": pub_date,
    }
    episodes.append(entry)

    # Sort by date descending (newest first)
    episodes.sort(key=lambda e: e.get("date", ""), reverse=True)

    save_manifest(episodes)
    print(f"  Added episode {date} to manifest ({len(episodes)} total)")
    return episodes


def _rfc2822_from_iso(iso_str: str) -> str:
    """Convert ISO 8601 date string to RFC 2822 format for RSS pubDate."""
    # Handle both "2026-01-29T14:48:00Z" and plain dates
    if "T" in iso_str:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(iso_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return formatdate(dt.timestamp(), usegmt=True)


def _format_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS for itunes:duration."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def generate_feed(output_path: Optional[str] = None) -> str:
    """
    Generate a podcast RSS feed XML string from the episode manifest.

    Args:
        output_path: If provided, write the feed XML to this file path.

    Returns:
        The feed XML as a string.
    """
    meta = PODCAST_METADATA
    episodes = load_manifest()

    # Register namespaces
    CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
    ATOM_NS = "http://www.w3.org/2005/Atom"
    ET.register_namespace("itunes", ITUNES_NS)
    ET.register_namespace("content", CONTENT_NS)
    ET.register_namespace("atom", ATOM_NS)

    # Build RSS root
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    # === Show-level metadata ===
    ET.SubElement(channel, "title").text = meta["title"]
    ET.SubElement(channel, "link").text = meta["website"]
    ET.SubElement(channel, "description").text = meta["description_long"]
    ET.SubElement(channel, "language").text = meta["language"]
    ET.SubElement(channel, "copyright").text = meta["copyright"]
    ET.SubElement(channel, "generator").text = "dtfhn feed.py"

    ET.SubElement(channel, "lastBuildDate").text = formatdate(
        datetime.now(timezone.utc).timestamp(), usegmt=True
    )

    # Atom self-link for feed validators
    atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", FEED_URL)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    # iTunes show-level tags
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = meta["author"]
    ET.SubElement(channel, f"{{{ITUNES_NS}}}summary").text = meta["description_long"]
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = (
        "true" if meta["explicit"] else "false"
    )
    ET.SubElement(channel, f"{{{ITUNES_NS}}}type").text = "episodic"

    # iTunes owner
    owner = ET.SubElement(channel, f"{{{ITUNES_NS}}}owner")
    ET.SubElement(owner, f"{{{ITUNES_NS}}}name").text = meta["author"]
    ET.SubElement(owner, f"{{{ITUNES_NS}}}email").text = meta["owner_email"]

    # iTunes categories
    primary_parts = meta["category_primary"].split(" > ")
    cat_primary = ET.SubElement(channel, f"{{{ITUNES_NS}}}category")
    cat_primary.set("text", primary_parts[0])
    if len(primary_parts) > 1:
        sub = ET.SubElement(cat_primary, f"{{{ITUNES_NS}}}category")
        sub.set("text", primary_parts[1])

    secondary_parts = meta["category_secondary"].split(" > ")
    cat_secondary = ET.SubElement(channel, f"{{{ITUNES_NS}}}category")
    cat_secondary.set("text", secondary_parts[0])
    if len(secondary_parts) > 1:
        sub = ET.SubElement(cat_secondary, f"{{{ITUNES_NS}}}category")
        sub.set("text", secondary_parts[1])

    # iTunes image
    ET.SubElement(channel, f"{{{ITUNES_NS}}}image", href=ARTWORK_URL)

    # === Episode items (from manifest only) ===
    for ep in episodes:
        date = ep.get("date", "")
        if not date:
            continue

        item = ET.SubElement(channel, "item")

        # Title from manifest (clean, human-readable)
        title = ep.get("title", f"DTF:HN for {date}")
        ET.SubElement(item, "title").text = title

        # Episode page URL: dasherize title to match Starpod slug convention
        import re
        episode_slug = title.lower()
        episode_slug = re.sub(r"[^a-z0-9\s-]", "", episode_slug)
        episode_slug = "-".join(episode_slug.split())
        ET.SubElement(item, "link").text = f"{meta['website']}/{episode_slug}"
        ET.SubElement(item, "guid", isPermaLink="false").text = f"dtfhn-{date}"

        # pubDate from manifest ISO string
        pub_date = ep.get("pub_date", "")
        if pub_date:
            ET.SubElement(item, "pubDate").text = _rfc2822_from_iso(pub_date)

        # Description from manifest (NOT from transcripts or scripts)
        description = ep.get("description", DEFAULT_EPISODE_DESCRIPTION)
        ET.SubElement(item, "description").text = description

        # Enclosure (the MP3)
        mp3_filename = ep.get("mp3_filename", f"DTFHN-{date}.mp3")
        mp3_url = f"{EPISODES_URL}/{mp3_filename}"
        filesize = ep.get("filesize_bytes", 0)
        ET.SubElement(
            item, "enclosure",
            url=mp3_url,
            length=str(filesize),
            type="audio/mpeg",
        )

        # Episode artwork (falls back to show artwork)
        ET.SubElement(item, f"{{{ITUNES_NS}}}image", href=ARTWORK_URL)

        # iTunes episode tags
        duration = ep.get("duration_seconds", 0)
        if duration:
            ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = _format_duration(
                duration
            )

        ET.SubElement(item, f"{{{ITUNES_NS}}}author").text = meta["author"]
        ET.SubElement(item, f"{{{ITUNES_NS}}}summary").text = description
        ET.SubElement(item, f"{{{ITUNES_NS}}}explicit").text = (
            "true" if meta["explicit"] else "false"
        )
        ET.SubElement(item, f"{{{ITUNES_NS}}}episodeType").text = "full"

        # Season = year, Episode = day of year
        date_part = date[:10]
        try:
            ep_dt = datetime.strptime(date_part, "%Y-%m-%d")
            ET.SubElement(item, f"{{{ITUNES_NS}}}season").text = str(ep_dt.year)
            ET.SubElement(item, f"{{{ITUNES_NS}}}episode").text = str(ep_dt.timetuple().tm_yday)
        except ValueError:
            pass

    # Serialize
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += ET.tostring(rss, encoding="unicode", xml_declaration=False)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml_str, encoding="utf-8")
        print(f"  Feed written to {output_path} ({len(episodes)} episodes)")

    return xml_str


def main():
    """CLI entry point: generate feed to stdout or file."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate DTFHN podcast RSS feed")
    parser.add_argument(
        "-o", "--output", default=None, help="Output file path (default: stdout)"
    )
    args = parser.parse_args()

    xml = generate_feed(output_path=args.output)
    if not args.output:
        print(xml)


if __name__ == "__main__":
    main()
