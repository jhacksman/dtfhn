# Carlin Podcast - Professional Features Research

## Executive Summary

For your automated daily HN podcast with George Carlin voice, I recommend:
- **Primary format:** MP3 with ID3v2.4 tags (chapters embedded)
- **Transcripts:** WebVTT (best cross-platform support)
- **Chapters:** Both embedded ID3 CHAP frames AND external JSON
- **RSS:** Full Podcast 2.0 namespace support

This combination gives you maximum compatibility today while being future-proof.

---

## 1. Transcripts

### Format Support Matrix

| Format | MIME Type | Apple Podcasts | Spotify | Web Browsers | Word-Level Timing |
|--------|-----------|----------------|---------|--------------|-------------------|
| **WebVTT** | `text/vtt` | ✅ Primary | ✅ | ✅ Native | ✅ Optional |
| **SRT** | `application/x-subrip` | ✅ | ✅ | ⚠️ Needs JS | ✅ |
| **JSON** | `application/json` | ⚠️ Limited | ⚠️ | ✅ | ✅ |
| **HTML** | `text/html` | ⚠️ | ⚠️ | ✅ | ❌ Low-fidelity |
| **Plain Text** | `text/plain` | ⚠️ | ⚠️ | ✅ | ❌ |

### Recommendation: WebVTT

**Why WebVTT wins:**
1. Apple Podcasts uses it for ingest
2. Native browser `<track>` element support
3. Supports speaker names via `<v>` tags
4. Can be generated from your script text + timing data

**WebVTT Example:**
```vtt
WEBVTT

00:00:00.000 --> 00:00:05.000
<v George>Welcome to your daily tech feed for Hacker News, where we dissect the tech news...

00:00:05.000 --> 00:00:12.000
Today's top story from Hacker News: some corporation did something stupid again.
```

**Technical Notes:**
- Max line length: 65 characters (for caption display)
- CORS headers required for web-based players
- Speaker changes trigger new cue: `<v SpeakerName>`

### Embedding vs Separate Files

**Transcripts should be SEPARATE files, not embedded in MP3:**
- Referenced via `<podcast:transcript>` RSS tag
- Can be updated after publishing without re-uploading audio
- Multiple formats can be offered simultaneously
- Better SEO (searchable text)

---

## 2. Chapter Markers

### Two Systems (Use Both!)

#### A. ID3v2 Chapters (Embedded in MP3)

The ID3v2 spec defines two frame types:
- **CHAP** (Chapter): Individual chapter with start/end time, title, optional image
- **CTOC** (Table of Contents): References CHAP frames, defines hierarchy

**Structure:**
```
CTOC (top-level, ordered=true)
├── CHAP "ch1" (0:00 - 2:30) "Intro" [TIT2 sub-frame]
├── CHAP "ch2" (2:30 - 5:45) "Story 1: AI Breakthrough" [TIT2 + APIC]
├── CHAP "ch3" (5:45 - 9:00) "Interstitial" 
└── ... etc
```

**App Support for ID3 Chapters:**
| App | ID3 Chapters | Chapter Images |
|-----|--------------|----------------|
| Apple Podcasts | ✅ | ✅ |
| Overcast | ✅ | ✅ |
| Pocket Casts | ✅ | ✅ |
| Castro | ✅ | ✅ |
| Podcast Addict | ✅ | ✅ |
| Spotify | ❌ | ❌ |
| Google Podcasts | ❌ (defunct) | ❌ |

#### B. JSON Chapters (External File - Podcast 2.0)

**Benefits over ID3:**
- No audio file modification needed
- Editable after publishing
- Works in web browsers (no ID3 parsing)
- Supports URLs, locations, silent markers
- Growing app support

**JSON Chapter Example for Carlin Podcast:**
```json
{
  "version": "1.2.0",
  "title": "Daily Tech Feed - January 28, 2026",
  "podcastName": "Daily Tech Feed",
  "chapters": [
    {
      "startTime": 0,
      "title": "Intro"
    },
    {
      "startTime": 45,
      "title": "Story 1: AI Model Breaks Everything",
      "img": "https://example.com/chapters/story1.jpg",
      "url": "https://news.ycombinator.com/item?id=12345"
    },
    {
      "startTime": 180,
      "title": "Interstitial",
      "toc": false
    },
    {
      "startTime": 195,
      "title": "Story 2: Startup Implodes",
      "url": "https://news.ycombinator.com/item?id=12346"
    }
  ]
}
```

**Note:** `"toc": false` creates a "silent" chapter - useful for interstitials where you want artwork to change but not clutter the chapter list.

**IMPORTANT:** The `url` field for each story chapter should use the **Hacker News discussion link** (`news.ycombinator.com/item?id=xxx`), NOT the original article URL. This directs listeners to the HN comments which are often more valuable than the article itself, and matches the podcast's "Carlin reads HN" concept.

---

## 3. MP3 Metadata (ID3 Tags)

### Essential Tags for Podcasts

| Tag | ID3 Frame | Purpose | Example |
|-----|-----------|---------|---------|
| Title | TIT2 | Episode title | "Jan 28: AI Chaos, Startup Death" |
| Artist | TPE1 | Show name | "Daily Tech Feed" |
| Album | TALB | Show name (again) | "Daily Tech Feed" |
| Album Artist | TPE2 | Show name | "Daily Tech Feed" |
| Year | TYER/TDRC | Release year | "2026" |
| Track Number | TRCK | Episode number | "127" |
| Genre | TCON | Always "Podcast" | "Podcast" |
| Comment | COMM | Episode description | "Today's top 10..." |
| Cover Art | APIC | 3000x3000 JPG | embedded image |
| Podcast URL | WOAS | Feed URL | "https://..." |
| Podcast Category | TCAT | iTunes category | "Technology" |

### Cover Art Requirements

| Platform | Min Size | Max Size | Format | Aspect |
|----------|----------|----------|--------|--------|
| Apple Podcasts | 1400x1400 | 3000x3000 | JPG/PNG | 1:1 |
| Spotify | 1400x1400 | 3000x3000 | JPG | 1:1 |
| General | 1400x1400 | 3000x3000 | JPG | 1:1 |

**Recommendation:** Embed 3000x3000 JPG, RGB, max 500KB

### ffmpeg Commands for ID3 Tags

```bash
# Basic metadata
ffmpeg -i input.mp3 \
  -metadata title="Episode Title" \
  -metadata artist="Daily Tech Feed" \
  -metadata album="Daily Tech Feed" \
  -metadata genre="Podcast" \
  -metadata track="127" \
  -metadata date="2026" \
  -metadata comment="Episode description here" \
  -codec copy output.mp3

# Add cover art
ffmpeg -i input.mp3 -i cover.jpg \
  -map 0 -map 1 \
  -codec copy \
  -metadata:s:v title="Album cover" \
  -metadata:s:v comment="Cover (front)" \
  -id3v2_version 4 \
  output.mp3
```

---

## 4. RSS/Podcast Feed

### Required Elements (Apple + Spotify)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" 
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <!-- Required Channel Elements -->
    <title>Daily Tech Feed</title>
    <link>https://example.com</link>
    <language>en-us</language>
    <description>George Carlin reads Hacker News</description>
    
    <!-- iTunes/Apple Required -->
    <itunes:author>Daily Tech Feed</itunes:author>
    <itunes:image href="https://example.com/cover-3000.jpg"/>
    <itunes:category text="Technology"/>
    <itunes:explicit>true</itunes:explicit>
    
    <!-- Podcast 2.0 Namespace -->
    <podcast:locked>no</podcast:locked>
    <podcast:guid>your-unique-guid-here</podcast:guid>
    
    <item>
      <!-- Required Item Elements -->
      <title>Jan 28: AI Chaos Edition</title>
      <enclosure url="https://example.com/ep127.mp3" 
                 length="24000000" 
                 type="audio/mpeg"/>
      <guid isPermaLink="false">ep127-2026-01-28</guid>
      <pubDate>Tue, 28 Jan 2026 06:00:00 -0800</pubDate>
      
      <!-- iTunes Item Elements -->
      <itunes:duration>1500</itunes:duration>
      <itunes:episode>127</itunes:episode>
      <itunes:episodeType>full</itunes:episodeType>
      <itunes:explicit>true</itunes:explicit>
      
      <!-- Podcast 2.0 Elements -->
      <podcast:transcript 
          url="https://example.com/ep127.vtt" 
          type="text/vtt"/>
      <podcast:chapters 
          url="https://example.com/ep127-chapters.json" 
          type="application/json+chapters"/>
    </item>
  </channel>
</rss>
```

### Podcast 2.0 Tags Worth Implementing

| Tag | Purpose | Priority |
|-----|---------|----------|
| `<podcast:transcript>` | Link transcript files | High |
| `<podcast:chapters>` | Link JSON chapters | High |
| `<podcast:guid>` | Unique podcast identifier | High |
| `<podcast:locked>` | Prevent feed hijacking | Medium |
| `<podcast:soundbite>` | Highlight clips for discovery | Medium |
| `<podcast:person>` | Credit contributors | Low |
| `<podcast:value>` | Lightning payments | Future |

---

## 5. Enhanced Podcast Formats

### MP3 vs M4A/AAC Comparison

| Feature | MP3 | M4A/AAC |
|---------|-----|---------|
| Universal playback | ✅ | ⚠️ Good but not universal |
| Chapter support | ✅ ID3v2 CHAP | ✅ Native (better!) |
| File size (same quality) | Baseline | 20-30% smaller |
| Streaming optimization | Good | Better |
| Apple Podcasts | ✅ | ✅ |
| Spotify | ✅ | ✅ |
| Legacy devices | ✅ Best | ⚠️ May have issues |

**Verdict:** Stick with MP3. The universal compatibility outweighs M4A's benefits, especially for a new podcast. M4A's native chapter support is nicer, but JSON chapters work everywhere.

### Podcast 2.0 Features to Consider Later

1. **Value4Value (V4V):** Lightning Network micropayments while listening
2. **Soundbites:** 30-60 second clips for discovery
3. **Social Interact:** Link to discussion threads
4. **Live Items:** For live streaming (not relevant for you)

---

## 6. Accessibility

### What Makes a Podcast Accessible

| Feature | Deaf/HoH | Blind/Low Vision | Cognitive |
|---------|----------|------------------|-----------|
| Transcript | ✅ Essential | ✅ Helpful | ✅ Helpful |
| Chapter markers | ⚠️ | ✅ Navigation | ✅ |
| Clear audio | ⚠️ | ✅ Essential | ✅ |
| Consistent format | ⚠️ | ✅ | ✅ Essential |

### Transcript Best Practices for Accessibility

1. **Include speaker identification** (WebVTT `<v>` tags)
2. **Add non-speech audio descriptions** `[music]` `[laughter]`
3. **Use proper punctuation** for screen reader flow
4. **Provide plain text version** alongside VTT for SEO/search

### WCAG Compliance Notes

- Transcripts fulfill WCAG 1.2.1 (Audio-only content)
- Synchronized captions would be WCAG 1.2.2 (live) / 1.2.3 (prerecorded)
- Your VTT files with timing satisfy this

---

## 7. Feature Matrix: Possible vs Supported

| Feature | Technically Possible | Widely Supported | Our Priority |
|---------|---------------------|------------------|--------------|
| MP3 audio | ✅ | ✅ Universal | ✅ Do it |
| ID3 basic tags | ✅ | ✅ Universal | ✅ Do it |
| Cover art embedded | ✅ | ✅ Universal | ✅ Do it |
| ID3 chapters | ✅ | ⚠️ Most apps except Spotify | ✅ Do it |
| JSON chapters | ✅ | ⚠️ Growing (Podcast 2.0 apps) | ✅ Do it |
| WebVTT transcript | ✅ | ⚠️ Apple, some others | ✅ Do it |
| SRT transcript | ✅ | ⚠️ Various | ⚠️ Optional |
| RSS feed | ✅ | ✅ Required | ✅ Do it |
| Podcast 2.0 namespace | ✅ | ⚠️ Growing | ✅ Do it |
| M4A format | ✅ | ⚠️ Good but not universal | ❌ Skip |
| Value4Value | ✅ | ❌ Niche | ❌ Skip for now |

---

## 8. Recommended Implementation

### Phase 1: Core (Do Now)

1. **MP3 Generation** with proper ID3v2.4 tags
   - Title, artist, album, episode number, date
   - 3000x3000 cover art embedded
   - Genre: "Podcast"

2. **ID3 Chapter Markers**
   - One CHAP frame per segment (intro, 10 stories, 9 interstitials, outro)
   - TIT2 sub-frames for chapter titles
   - CTOC frame referencing all chapters

3. **WebVTT Transcript**
   - Generated from your script
   - Speaker tag: `<v George>`
   - Timestamps from your segment boundaries

4. **JSON Chapters File**
   - Include HN links as URLs
   - Per-story images if you generate them

### Phase 2: Distribution (Next)

5. **RSS Feed**
   - Full Apple/Spotify compliance
   - Podcast 2.0 namespace
   - `<podcast:transcript>` and `<podcast:chapters>` tags

6. **Hosting**
   - Static file hosting for audio + chapters + transcripts
   - CORS headers for web players

### Phase 3: Enhancements (Later)

7. **Soundbites** - Best 60-second clips for discovery
8. **Plain text transcript** - For SEO
9. **Per-chapter artwork** - Story-specific images

---

## 9. Technical Implementation Notes

### Libraries & Tools

**Python:**
- `mutagen` - ID3 tag manipulation (including chapters)
- `eyed3` - Simpler ID3 interface

**Node.js:**
- `node-id3` - Full ID3v2 support including CHAP
- `music-metadata` - Reading tags

**Command Line:**
- `ffmpeg` - Audio processing + basic tags
- `mp3chaps` - Chapter manipulation
- `id3v2` - Tag editing

### ffmpeg Chapter Embedding (MP4 only, sadly)

ffmpeg's native chapter support only works for MP4/MKV containers, not MP3. For MP3 chapters, use `mutagen` in Python or `node-id3`.

### Python Example with Mutagen

```python
from mutagen.id3 import ID3, CHAP, CTOC, TIT2, CTOCFlags

audio = ID3("episode.mp3")

# Add chapters
chapters = [
    ("ch0", 0, 45000, "Intro"),
    ("ch1", 45000, 180000, "Story 1: AI Chaos"),
    ("ch2", 180000, 195000, "Interstitial"),
    # ... etc
]

chapter_ids = []
for chap_id, start_ms, end_ms, title in chapters:
    audio.add(CHAP(
        element_id=chap_id,
        start_time=start_ms,
        end_time=end_ms,
        sub_frames=[TIT2(encoding=3, text=title)]
    ))
    chapter_ids.append(chap_id)

# Add table of contents
audio.add(CTOC(
    element_id="toc",
    flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
    child_element_ids=chapter_ids,
    sub_frames=[TIT2(encoding=3, text="Table of Contents")]
))

audio.save()
```

### WebVTT Generation Example

```python
def generate_vtt(segments):
    """
    segments: list of (start_sec, end_sec, text)
    """
    lines = ["WEBVTT", ""]
    
    for start, end, text in segments:
        start_ts = format_timestamp(start)
        end_ts = format_timestamp(end)
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"<v George>{text}")
        lines.append("")
    
    return "\n".join(lines)

def format_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"
```

---

## 10. Priority Order

### Must Have (v1.0)
1. Clean MP3 with ID3v2.4 tags
2. Embedded cover art
3. Embedded ID3 chapters
4. WebVTT transcript file

### Should Have (v1.1)
5. JSON chapters file
6. RSS feed with Podcast 2.0 tags
7. Plain text transcript

### Nice to Have (v2.0)
8. Per-chapter artwork
9. Soundbites
10. Multiple transcript formats

---

## Summary

Your tech stack for a professional podcast:

```
episode.mp3           # Audio with ID3 tags + chapters
episode.vtt           # WebVTT transcript
episode-chapters.json # JSON chapters (Podcast 2.0)
cover.jpg             # 3000x3000 artwork
feed.xml              # RSS with podcast namespace
```

All easily generated programmatically. The George Carlin voice + HN content is the magic; this infrastructure just makes it discoverable and professional.
