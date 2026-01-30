"""
RSS feed generator for Daily Tech Feed: Hacker News podcast.

Generates a valid RSS 2.0 feed with iTunes namespace for podcast directories.
Episodes are sourced from LanceDB (via storage module).
"""

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from typing import Optional

from .metadata import PODCAST_METADATA

# R2 / public URL configuration
R2_BASE_URL = "https://podcast.pdxh.org/dtfhn"
EPISODES_URL = f"{R2_BASE_URL}/episodes"
FEED_URL = f"{R2_BASE_URL}/feed.xml"

# iTunes XML namespace
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def _rfc2822_from_date(date_str: str) -> str:
    """Convert episode date string to RFC 2822 format for RSS pubDate.

    Handles both YYYY-MM-DD and YYYY-MM-DD-HHMM formats.
    """
    date_part = date_str[:10]
    dt = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    # If we have HHMM suffix, use it
    if len(date_str) > 10:
        time_part = date_str[11:]
        if len(time_part) == 4 and time_part.isdigit():
            dt = dt.replace(hour=int(time_part[:2]), minute=int(time_part[2:]))

    return formatdate(dt.timestamp(), usegmt=True)


def _format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS for itunes:duration."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _episode_mp3_url(episode_date: str) -> str:
    """Build the public URL for an episode MP3."""
    return f"{EPISODES_URL}/DTFHN-{episode_date}.mp3"


def _episode_mp3_filename(episode_date: str) -> str:
    """Build the filename for an episode MP3."""
    return f"DTFHN-{episode_date}.mp3"


def generate_feed(
    output_path: Optional[str] = None,
    episodes: Optional[list[dict]] = None,
) -> str:
    """
    Generate a podcast RSS feed XML string.

    Args:
        output_path: If provided, write the feed XML to this file path.
        episodes: List of episode dicts. If None, fetches from LanceDB.
            Each dict should have: episode_date, duration_seconds, transcript (optional),
            word_count (optional), mp3_size_bytes (optional).

    Returns:
        The feed XML as a string.
    """
    meta = PODCAST_METADATA

    # Fetch episodes from storage if not provided
    if episodes is None:
        from .storage import list_episodes
        episodes = list_episodes()

    # Register namespaces so serialization uses proper prefixes
    CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
    ET.register_namespace("itunes", ITUNES_NS)
    ET.register_namespace("content", CONTENT_NS)

    # Build RSS root — namespace declarations added automatically by register_namespace
    rss = ET.Element("rss", {"version": "2.0"})

    channel = ET.SubElement(rss, "channel")

    # === Show-level metadata ===
    ET.SubElement(channel, "title").text = meta["title"]
    ET.SubElement(channel, "link").text = meta["website"]
    ET.SubElement(channel, "description").text = meta["description_long"]
    ET.SubElement(channel, "language").text = meta["language"]
    ET.SubElement(channel, "copyright").text = meta["copyright"]
    ET.SubElement(channel, "generator").text = "dtfhn feed.py"

    # Last build date
    ET.SubElement(channel, "lastBuildDate").text = formatdate(
        datetime.now(timezone.utc).timestamp(), usegmt=True
    )

    # Atom self-link for feed validators
    atom_ns = "http://www.w3.org/2005/Atom"
    ET.register_namespace("atom", atom_ns)
    atom_link = ET.SubElement(channel, f"{{{atom_ns}}}link")
    atom_link.set("href", FEED_URL)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    # iTunes show-level tags
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = meta["author"]
    ET.SubElement(channel, f"{{{ITUNES_NS}}}summary").text = meta["description_long"]
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "true" if meta["explicit"] else "false"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}type").text = "episodic"

    # iTunes owner
    owner = ET.SubElement(channel, f"{{{ITUNES_NS}}}owner")
    ET.SubElement(owner, f"{{{ITUNES_NS}}}name").text = meta["author"]
    ET.SubElement(owner, f"{{{ITUNES_NS}}}email").text = meta["owner_email"]

    # iTunes categories (use attrib dict to avoid kwarg collision with .text)
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

    # iTunes image (placeholder — update when artwork exists)
    ET.SubElement(channel, f"{{{ITUNES_NS}}}image", href=f"{R2_BASE_URL}/artwork.jpg")

    # === Episode items ===
    for ep in episodes:
        ep_date = ep.get("episode_date", "")
        if not ep_date:
            continue

        # Skip test episodes
        if ep_date.startswith("test-"):
            continue

        item = ET.SubElement(channel, "item")
        ep_title = f"Daily Tech Feed - {ep_date}"

        ET.SubElement(item, "title").text = ep_title
        ET.SubElement(item, "link").text = meta["website"]
        ET.SubElement(item, "guid", isPermaLink="false").text = f"dtfhn-{ep_date}"
        ET.SubElement(item, "pubDate").text = _rfc2822_from_date(ep_date)

        # Description: use transcript snippet or fallback
        transcript = ep.get("transcript", "")
        if transcript:
            # First 500 chars as description
            desc = transcript[:500].strip()
            if len(transcript) > 500:
                desc += "..."
        else:
            desc = f"{meta['description_short']} Episode: {ep_date}."
        ET.SubElement(item, "description").text = desc

        # Enclosure (the MP3)
        mp3_url = _episode_mp3_url(ep_date)
        mp3_size = ep.get("mp3_size_bytes", 0)
        if not mp3_size:
            # Estimate from duration: ~128kbps = 16KB/s
            duration_s = ep.get("duration_seconds", 0) or 0
            mp3_size = int(duration_s * 16000) if duration_s else 0
        ET.SubElement(item, "enclosure", url=mp3_url, length=str(mp3_size), type="audio/mpeg")

        # iTunes episode tags
        duration_s = ep.get("duration_seconds", 0) or 0
        if duration_s:
            ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = _format_duration(duration_s)

        ET.SubElement(item, f"{{{ITUNES_NS}}}author").text = meta["author"]
        ET.SubElement(item, f"{{{ITUNES_NS}}}summary").text = desc
        ET.SubElement(item, f"{{{ITUNES_NS}}}explicit").text = "true" if meta["explicit"] else "false"
        ET.SubElement(item, f"{{{ITUNES_NS}}}episodeType").text = "full"

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
    parser.add_argument("-o", "--output", default=None, help="Output file path (default: stdout)")
    args = parser.parse_args()

    xml = generate_feed(output_path=args.output)
    if not args.output:
        print(xml)


if __name__ == "__main__":
    main()
