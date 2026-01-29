"""
ID3 metadata embedding for podcast MP3 files.
Adds standard tags (title, artist, album, genre, date, etc.)
separate from chapter markers (handled by chapters.py).
"""

from datetime import datetime
from typing import Optional

from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TCON, TDRC, TRCK, COMM


def embed_id3_metadata(
    mp3_path: str,
    episode_date: str,
    episode_number: Optional[int] = None,
    description: Optional[str] = None,
    cover_art_path: Optional[str] = None,
) -> None:
    """
    Embed standard ID3v2 metadata tags into an MP3 file.

    This handles basic identification tags. Chapter markers are handled
    separately by chapters.py's embed_chapters().

    Args:
        mp3_path: Path to the MP3 file
        episode_date: Date string "YYYY-MM-DD"
        episode_number: Optional episode/track number (defaults to day-of-year)
        description: Optional episode description for COMM tag
        cover_art_path: Optional path to cover art JPG/PNG for APIC tag

    Tags embedded:
        TIT2 (Title): "Daily Tech Feed - YYYY-MM-DD"
        TPE1 (Artist): "AI George Carlin"
        TPE2 (Album Artist): "Daily Tech Feed"
        TALB (Album): "Daily Tech Feed"
        TCON (Genre): "Technology"
        TDRC (Date): episode date
        TRCK (Track): episode number
        COMM (Comment): episode description (if provided)
    """
    # Load existing ID3 tags (preserves chapters)
    try:
        audio = ID3(mp3_path)
    except Exception:
        audio = ID3()

    # Parse date for derived fields
    dt = datetime.strptime(episode_date, "%Y-%m-%d")
    if episode_number is None:
        episode_number = dt.timetuple().tm_yday  # Day of year

    title = f"Daily Tech Feed - {episode_date}"

    # Core identification
    audio.add(TIT2(encoding=3, text=title))
    audio.add(TPE1(encoding=3, text="AI George Carlin"))
    audio.add(TPE2(encoding=3, text="Daily Tech Feed"))
    audio.add(TALB(encoding=3, text="Daily Tech Feed"))
    audio.add(TCON(encoding=3, text="Technology"))
    audio.add(TDRC(encoding=3, text=episode_date))
    audio.add(TRCK(encoding=3, text=str(episode_number)))

    # Optional description
    if description:
        audio.add(COMM(encoding=3, lang="eng", desc="", text=description))

    # TODO: APIC (Cover Art) — skip for now, no artwork yet
    # When artwork is available:
    #   from mutagen.id3 import APIC
    #   with open(cover_art_path, 'rb') as f:
    #       audio.add(APIC(encoding=3, mime='image/jpeg', type=3,
    #                       desc='Cover', data=f.read()))

    audio.save(mp3_path)
    print(f"  Embedded ID3 metadata: {title}")
