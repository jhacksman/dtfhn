# Research Report: Podcast Metadata, Chapters, and Transcripts

**Project:** DTF:HN (Daily Tech Feed for Hacker News)  
**Date:** 2026-01-28  
**Scope:** MP3 metadata, chapter markers, transcripts, RSS feed requirements

---

## Table of Contents

1. [Chapters](#1-chapters)
2. [Transcripts](#2-transcripts)
3. [MP3 Metadata / ID3 Tags](#3-mp3-metadata--id3-tags)
4. [RSS Feed Requirements](#4-rss-feed-requirements)
5. [Current Implementation Gap Analysis](#5-current-implementation-gap-analysis)
6. [Recommendations](#6-recommendations)

---

## 1. Chapters

### 1.1 Chapter Format Landscape

There are three chapter systems in the podcast world:

#### A. ID3v2 CHAP/CTOC Frames (Embedded in MP3)

The ID3v2.3/v2.4 spec defines two frame types for chapters:

- **CHAP frame:** Individual chapter with element_id, start_time (ms), end_time (ms), and optional sub-frames (TIT2 for title, APIC for image, WXXX for URL)
- **CTOC frame:** Table of contents that references CHAP frames by element_id. Flags indicate if it's top-level and/or ordered.

**How it works:**
```
CTOC (element_id="toc", flags=TOP_LEVEL|ORDERED)
  ├── child_element_ids: ["ch0", "ch1", "ch2", ...]
  └── sub_frames: [TIT2("Table of Contents")]

CHAP (element_id="ch0", start=0ms, end=45000ms)
  └── sub_frames: [TIT2("Intro")]

CHAP (element_id="ch1", start=45000ms, end=180000ms)
  └── sub_frames: [TIT2("Story 1: ..."), WXXX(url="https://...")]
```

**App support for ID3 CHAP/CTOC:**

| App | ID3 Chapters | Chapter Images (APIC) | Chapter URLs (WXXX) |
|-----|:---:|:---:|:---:|
| **Apple Podcasts** | ✅ | ✅ | ✅ |
| **Overcast** | ✅ | ✅ | ✅ |
| **Pocket Casts** | ✅ | ✅ | ✅ |
| **Castro** | ✅ | ✅ | ✅ |
| **Podcast Addict** | ✅ | ✅ | ✅ |
| **Podverse** | ✅ | ✅ | ✅ |
| **Spotify** | ❌ | ❌ | ❌ |
| **Amazon Music** | ❌ | ❌ | ❌ |
| **YouTube Music** | N/A | N/A | N/A |

**Key takeaway:** ID3 chapters work in every major podcast app *except* Spotify. Spotify completely ignores ID3 chapter data. They have their own internal chapter system that's not accessible to third-party podcasters.

#### B. Podcast 2.0 JSON Chapters (External File)

Defined by the Podcast Index namespace. An external JSON file linked via `<podcast:chapters>` RSS tag.

**Spec (from podcastindex.org/namespace/1.0):**
- MIME type: `application/json+chapters`
- Version field: `"1.2.0"` (current)
- Each chapter has: `startTime` (required, seconds), `title` (required), `img` (optional URL), `url` (optional URL), `toc` (optional bool, default true)
- `toc: false` creates a "silent chapter" — artwork changes without appearing in chapter list
- No `endTime` needed — each chapter runs until the next one starts

**JSON Chapters example:**
```json
{
  "version": "1.2.0",
  "chapters": [
    {"startTime": 0, "title": "Intro"},
    {"startTime": 45, "title": "Story 1: Title", "url": "https://news.ycombinator.com/item?id=..."},
    {"startTime": 180, "title": "Story 2: Title", "url": "https://news.ycombinator.com/item?id=..."}
  ]
}
```

**App support for JSON Chapters:**

| App | JSON Chapters | Notes |
|-----|:---:|-------|
| **Podcast Addict** | ✅ | Full support |
| **Podverse** | ✅ | Full support |
| **Castamatic** | ✅ | Full support |
| **Fountain** | ✅ | Full support |
| **CurioCaster** | ✅ | Full support |
| **Podfriend** | ✅ | Full support |
| **Apple Podcasts** | ❌ | Uses ID3 only |
| **Overcast** | ❌ | Uses ID3 only |
| **Pocket Casts** | ❌ | Uses ID3 only |
| **Spotify** | ❌ | Neither format |
| **Castro** | ❌ | Uses ID3 only |

**Key takeaway:** JSON chapters are supported by Podcast 2.0 apps but NOT by the big players (Apple, Overcast, Pocket Casts). ID3 chapters have far wider reach among mainstream apps.

#### C. MP4/Enhanced Podcast Chapters (Legacy)

Apple's old "Enhanced Podcast" format used M4A/AAC containers with native chapter atoms. This is **dead** — Apple deprecated it years ago. Not worth implementing.

### 1.2 Best Practice for 2025/2026

**Do BOTH: Embed ID3 chapters in MP3 AND serve JSON chapters externally.**

- ID3 chapters → Apple Podcasts, Overcast, Pocket Casts, Castro, Podcast Addict
- JSON chapters → Podcast 2.0 apps, web players, future-proofing
- Combined → maximum reach

This is a negligible cost since we already generate both.

### 1.3 Chapter Content Best Practices

- **Use actual story titles** as chapter names, not "Story 1", "Story 2"
- **Include HN discussion URLs** in chapter entries (both WXXX in ID3 and url in JSON)
- **Skip interstitials** from chapter list (our current approach is correct)
- **Per-chapter artwork** is a nice-to-have but low priority for automated generation

---

## 2. Transcripts

### 2.1 Apple Podcasts Transcript Support

Apple Podcasts supports transcripts in two ways:

1. **Auto-generated:** Apple automatically generates transcripts using speech recognition for podcasts in supported languages. These appear in the Apple Podcasts app (iOS 17.4+, macOS Sonoma+).
2. **Publisher-provided:** Publishers can provide transcripts via the `<podcast:transcript>` RSS tag. Apple prefers **SRT** format but also accepts **VTT**. When a publisher provides a transcript, it replaces Apple's auto-generated version.

**Apple's preferred format:** SRT (`application/x-subrip`)  
**Also accepted:** VTT (`text/vtt`)

### 2.2 Spotify Transcript Support

Spotify generates its own transcripts internally using speech recognition. As of 2025/2026, **Spotify does NOT ingest publisher-provided transcripts** from RSS feeds. They ignore `<podcast:transcript>` entirely.

This may change, but currently there's nothing we can do to provide Spotify with our transcript.

### 2.3 Podcast 2.0 `<podcast:transcript>` Tag

From the official spec:

```xml
<podcast:transcript url="https://example.com/ep.vtt" type="text/vtt" />
<podcast:transcript url="https://example.com/ep.srt" type="application/x-subrip" rel="captions" />
<podcast:transcript url="https://example.com/ep.json" type="application/json" />
<podcast:transcript url="https://example.com/ep.txt" type="text/plain" />
```

**Attributes:**
- `url` (required): URL of the transcript file
- `type` (required): MIME type
- `language` (optional): Language code (defaults to RSS `<language>`)
- `rel` (optional): If `rel="captions"`, the file is treated as closed captions (assumes time codes present)

**Multiple tags allowed** — you can provide transcripts in several formats simultaneously.

### 2.4 Format Comparison for Widest Support

| Format | Apple Podcasts | Podcast 2.0 Apps | Web Browsers | SEO Value |
|--------|:---:|:---:|:---:|:---:|
| **VTT** | ✅ | ✅ | ✅ (native `<track>`) | Medium |
| **SRT** | ✅ (preferred) | ✅ | ⚠️ (needs JS) | Medium |
| **JSON** | ⚠️ | ✅ | ✅ (with code) | Low |
| **Plain text** | ⚠️ | ✅ | ✅ | ✅ High |

**Recommendation:** Provide **VTT as primary** (broadest native support) and **plain text as secondary** (SEO, accessibility). Consider adding SRT as a third option since Apple prefers it.

### 2.5 Embedded vs External

**Transcripts should ALWAYS be external files**, referenced via RSS. Reasons:
- Can be updated after publishing without re-uploading audio
- Multiple formats can be offered simultaneously
- No impact on MP3 file size
- Better for search engines (crawlable text)
- This is what the `<podcast:transcript>` tag is designed for

There is no standard for embedding transcripts *inside* an MP3 file. The ID3 spec has no transcript frame.

---

## 3. MP3 Metadata / ID3 Tags

### 3.1 Essential ID3 Tags for Podcast Episodes

| Tag | ID3 Frame | Value for DTF:HN | Priority |
|-----|-----------|-------------------|:---:|
| Title | TIT2 | "Daily Tech Feed - 2026-01-28" | **Required** |
| Artist | TPE1 | "Daily Tech Feed" | **Required** |
| Album | TALB | "Daily Tech Feed" | **Required** |
| Album Artist | TPE2 | "Daily Tech Feed" | Recommended |
| Year/Date | TDRC (v2.4) | "2026-01-28" | Recommended |
| Track Number | TRCK | Episode number | Recommended |
| Genre | TCON | "Podcast" | Recommended |
| Comment | COMM | Episode summary/description | Optional |
| Cover Art | APIC | 3000×3000 JPG | **Required** |
| Podcast URL | WOAF | Feed URL | Optional |
| Encoding | TENC | "DTF:HN Pipeline" | Optional |

### 3.2 What Apps Actually Read from ID3 vs RSS

**Apple Podcasts:**
- Episode title: **RSS `<title>` wins** over ID3 TIT2
- Episode artwork: **RSS `<itunes:image>` wins** over ID3 APIC, but ID3 APIC is used as fallback
- Duration: **RSS `<itunes:duration>` wins** over ID3 TLEN
- Chapters: **ID3 CHAP/CTOC** — this is the ONLY way to get chapters in Apple Podcasts
- All other metadata: RSS takes priority

**Spotify:**
- Ignores almost all ID3 tags
- Uses RSS metadata exclusively for display
- Does NOT read ID3 chapters
- Does NOT read ID3 artwork (uses RSS `<itunes:image>`)

**Overcast, Pocket Casts, etc.:**
- Display info: RSS takes priority
- Chapters: ID3 CHAP/CTOC (some also support JSON chapters)
- Artwork: RSS first, ID3 fallback

### 3.3 ID3 vs RSS Conflicts

**Rule of thumb:** RSS metadata always wins for display purposes. ID3 tags serve as:
1. Fallback when RSS is unavailable (direct MP3 download/share)
2. The ONLY mechanism for chapter markers in most apps
3. Artwork fallback for offline/downloaded episodes

**Keep them in sync.** If RSS says the title is "Daily Tech Feed - 2026-01-28" but ID3 says "Episode 127", some apps may flash the wrong title briefly during download.

### 3.4 Episode Artwork

**Embed artwork in the MP3 AND include it in RSS.**

- RSS `<itunes:image>`: Used by all apps for display. Required to be 1400×1400 to 3000×3000 JPG/PNG.
- ID3 APIC: Fallback for direct file access, offline players, non-podcast media players.

**Our recommendation:** 
- Show-level artwork: 3000×3000 JPG, same image used everywhere
- Episode-level artwork: Optional. If we want per-episode art, provide via RSS `<itunes:image>` at the `<item>` level AND embed in ID3 APIC
- Keep APIC under ~500KB to avoid bloating the MP3

---

## 4. RSS Feed Requirements

### 4.1 Apple Podcasts Required RSS Tags

**Channel-level (required):**
```xml
<title>Daily Tech Feed</title>
<description>AI-generated daily podcast covering the top stories from Hacker News</description>
<language>en-us</language>
<itunes:author>Daily Tech Feed</itunes:author>
<itunes:image href="https://example.com/cover-3000.jpg"/>
<itunes:category text="Technology"/>
<itunes:explicit>true</itunes:explicit>
<link>https://example.com</link>
```

**Item-level (required per episode):**
```xml
<title>Daily Tech Feed - 2026-01-28</title>
<enclosure url="https://example.com/episodes/2026-01-28.mp3" 
           length="15000000" type="audio/mpeg"/>
<guid isPermaLink="false">dtfhn-2026-01-28</guid>
<pubDate>Wed, 28 Jan 2026 06:00:00 -0800</pubDate>
<itunes:duration>1260</itunes:duration>
<itunes:explicit>true</itunes:explicit>
<itunes:episodeType>full</itunes:episodeType>
```

**Additional Apple requirements (from official docs):**
- RSS 2.0 compliant
- Publicly accessible (no auth)
- HTTP HEAD and byte-range requests supported
- Each episode needs unique `<guid>` that never changes
- ASCII filenames and URLs only (a-z, A-Z, 0-9, percent-encoded)
- Case-sensitive XML tags
- RFC 2822 date format
- Proper XML entity encoding (`&amp;`, `&apos;`, etc.)
- At least one episode published

### 4.2 Spotify Required RSS Tags

Spotify's requirements are very similar to Apple's. The minimum set:

**Channel-level:**
```xml
<title>
<description>
<itunes:image> (1400×1400 to 3000×3000)
<language>
<itunes:category>
<itunes:author>
<itunes:explicit>
```

**Item-level:**
```xml
<title>
<enclosure> (url, length, type)
<guid>
<pubDate>
<itunes:duration>
```

Spotify accepts the same iTunes namespace tags as Apple. No Spotify-specific namespace exists.

### 4.3 Podcast 2.0 Namespace Tags Worth Using

| Tag | Purpose | Priority for DTF:HN |
|-----|---------|:---:|
| `<podcast:transcript>` | Link to transcript files (VTT, SRT, TXT) | **High** |
| `<podcast:chapters>` | Link to JSON chapters file | **High** |
| `<podcast:guid>` | Unique podcast identifier (UUID v5) | **High** |
| `<podcast:locked>` | Prevent unauthorized feed moves | **Medium** |
| `<podcast:person>` | Credit contributors | Low |
| `<podcast:soundbite>` | Highlight clips for discovery | Medium |
| `<podcast:value>` | Lightning/cryptocurrency payments | Low (future) |
| `<podcast:socialInteract>` | Link to discussion threads | Medium (could link to HN) |
| `<podcast:medium>` | Declare content type | Low (default is "podcast") |
| `<podcast:updateFrequency>` | Signal daily publication schedule | Medium |

### 4.4 Minimum Viable RSS Feed

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Daily Tech Feed</title>
    <link>https://dtfhn.com</link>
    <description>AI-generated daily podcast covering the top stories from Hacker News, delivered with sharp commentary and zero corporate polish.</description>
    <language>en-us</language>
    <itunes:author>Daily Tech Feed</itunes:author>
    <itunes:image href="https://dtfhn.com/cover-3000.jpg"/>
    <itunes:category text="Technology">
      <itunes:category text="Tech News"/>
    </itunes:category>
    <itunes:explicit>true</itunes:explicit>
    <itunes:type>episodic</itunes:type>
    
    <!-- Podcast 2.0 -->
    <podcast:locked>no</podcast:locked>
    <podcast:guid><!-- UUID v5 from feed URL --></podcast:guid>
    
    <item>
      <title>Daily Tech Feed - 2026-01-28</title>
      <description>Today's top 10 stories from Hacker News: Microsoft forces Linux switch, Interactive airfoil explainer, Amazon kills palm payments...</description>
      <enclosure url="https://dtfhn.com/episodes/2026-01-28.mp3"
                 length="15234567" type="audio/mpeg"/>
      <guid isPermaLink="false">dtfhn-2026-01-28</guid>
      <pubDate>Wed, 28 Jan 2026 06:00:00 -0800</pubDate>
      <itunes:duration>1260</itunes:duration>
      <itunes:episode>1</itunes:episode>
      <itunes:episodeType>full</itunes:episodeType>
      <itunes:explicit>true</itunes:explicit>
      
      <!-- Podcast 2.0 -->
      <podcast:transcript url="https://dtfhn.com/episodes/2026-01-28/transcript.vtt" 
                          type="text/vtt"/>
      <podcast:transcript url="https://dtfhn.com/episodes/2026-01-28/transcript.txt" 
                          type="text/plain"/>
      <podcast:chapters url="https://dtfhn.com/episodes/2026-01-28/chapters.json" 
                        type="application/json+chapters"/>
    </item>
  </channel>
</rss>
```

---

## 5. Current Implementation Gap Analysis

### 5.1 What We Have

| Component | File | Status |
|-----------|------|--------|
| ID3 chapter embedding | `src/chapters.py` → `embed_chapters()` | ✅ Working |
| JSON chapters generation | `src/chapters.py` → `generate_chapters_json()` | ✅ Working |
| WebVTT transcript | `src/transcript.py` → `generate_vtt()` | ✅ Working |
| Plain text transcript | `src/transcript.py` → `generate_plain_transcript()` | ✅ Working |
| Chapter data from segments | `src/chapters.py` → `segments_to_chapters()` | ✅ Working |
| Segment storage with timing | `src/storage.py` | ✅ Working |

### 5.2 Gaps Identified

#### GAP 1: Chapters JSON Missing Story Titles (CRITICAL)
**Current:** `chapters.json` has generic titles: "Story 1", "Story 2", etc.
**Should have:** Actual HN story titles: "Story 1: Microsoft forced me to switch to Linux"

Looking at the 2026-01-28 chapters.json:
```json
{"startTime": 20.579083, "title": "Story 1"}
```

The `segments_to_chapters()` function tries to use `seg.get("title")` but falls back to `f"Story {seg.get('story_position', '?')}"`. The segments in storage don't include the story title — only `story_position`. The title comes from the stories table, not the segments table.

**Fix:** When generating chapters, join segments with stories data to get actual titles and URLs.

#### GAP 2: Chapters JSON Missing HN URLs (CRITICAL)
**Current:** No URLs in chapter entries.
**Should have:** HN discussion URLs for each story chapter.

Same root cause as GAP 1 — segments don't carry URL data. Need to pull from stories table.

#### GAP 3: No ID3 Basic Metadata (HIGH)
**Current:** Only chapter frames are embedded. No TIT2, TPE1, TALB, APIC, etc.
**Should have:** Full ID3 tag set — title, artist, album, cover art, genre, date, track number.

The `embed_chapters()` function only handles CHAP/CTOC frames. We need a separate `embed_id3_metadata()` function (or extend the existing one).

#### GAP 4: No Cover Artwork (HIGH)
**Current:** No show artwork exists.
**Should have:** 3000×3000 JPG cover art, embedded in MP3 and hosted for RSS.

This is a hard requirement for Apple Podcasts and Spotify submission.

#### GAP 5: No RSS Feed (HIGH)
**Current:** No RSS feed generation.
**Should have:** Complete RSS feed with iTunes and Podcast 2.0 namespace.

This is the distribution mechanism — without it, we can't submit to any podcast directory.

#### GAP 6: No File Hosting (HIGH)
**Current:** MP3 stored as binary in LanceDB. Chapters/transcripts as local files.
**Should have:** Public URLs for MP3, chapters.json, transcript.vtt, transcript.txt, cover art.

Episodes need to be served over HTTPS with proper CORS headers, byte-range support, and HTTP HEAD support.

#### GAP 7: No Episode Description Generation (MEDIUM)
**Current:** No episode summary/description.
**Should have:** A text description listing the stories covered, for RSS `<description>` and ID3 COMM.

#### GAP 8: No SRT Transcript (LOW)
**Current:** VTT and plain text only.
**Should have:** SRT as well, since Apple Podcasts prefers it.

SRT is trivially derived from VTT — the format differences are minor (timestamp format, no `<v>` tags).

#### GAP 9: VTT Has Single-Cue-Per-Segment Structure (LOW)
**Current:** Each segment (up to ~3 minutes of text) is a single VTT cue.
**Should have:** Shorter cues (5-15 seconds) for karaoke-style follow-along.

For Apple Podcasts' "Read along with transcripts" feature to highlight the currently-spoken text, cues need to be much shorter — ideally sentence-level. Our current VTT has 21 cues for a 21-minute episode, with individual cues containing entire multi-paragraph scripts. This makes the read-along feature useless.

**Fix:** Split segment text into sentences and estimate timing proportionally (word count ratio). This would give ~100-200 cues instead of 21. Much better for transcript follow-along.

### 5.3 What's Working Well

- **Chapter structure is correct:** Skipping interstitials, including intro/scripts/outro
- **Mutagen usage is correct:** CHAP + CTOC with proper flags, millisecond timing
- **VTT format is correct:** Proper timestamps, `<v Speaker>` tags
- **Plain text transcript:** Section markers [INTRO], [STORY N: Title], [TRANSITION], [OUTRO]
- **Podcast 2.0 JSON format:** Correct version, structure, `podcastName`, `title`
- **Two-phase timing:** Estimated → actual timing approach is sound

---

## 6. Recommendations

### Priority 1: Fix Chapter Content (Easy, High Impact)

**What:** Pass story titles and HN URLs into chapter generation.

**How:** Modify the chapter generation pipeline to join segments with stories data:
```python
# In the finalization step, fetch stories for the episode date
stories = get_stories_by_date(episode_date)
story_lookup = {s['position']: s for s in stories}

# When building chapters, enrich segments with story data
for seg in segments:
    if seg['segment_type'] == 'script':
        story = story_lookup.get(seg['story_position'])
        if story:
            seg['title'] = story['title']
            seg['url'] = f"https://news.ycombinator.com/item?id={story['hn_id']}"
```

**Effort:** ~30 minutes  
**Impact:** Chapters become actually useful instead of "Story 1", "Story 2"

### Priority 2: Add ID3 Basic Metadata (Easy, High Impact)

**What:** Embed standard ID3 tags in the MP3 alongside chapters.

**How:** Add to `chapters.py` or create `src/metadata.py`:
```python
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TCON, TRCK, COMM, APIC

def embed_id3_metadata(mp3_path, title, episode_number, date, description, cover_art_path=None):
    audio = ID3(mp3_path)
    audio.add(TIT2(encoding=3, text=title))
    audio.add(TPE1(encoding=3, text="Daily Tech Feed"))
    audio.add(TALB(encoding=3, text="Daily Tech Feed"))
    audio.add(TPE2(encoding=3, text="Daily Tech Feed"))
    audio.add(TDRC(encoding=3, text=date))
    audio.add(TCON(encoding=3, text="Podcast"))
    audio.add(TRCK(encoding=3, text=str(episode_number)))
    audio.add(COMM(encoding=3, lang='eng', desc='', text=description))
    if cover_art_path:
        with open(cover_art_path, 'rb') as f:
            audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=f.read()))
    audio.save(mp3_path)
```

**Effort:** ~1 hour  
**Impact:** MP3 files identify themselves properly in any media player

### Priority 3: Create Cover Artwork (Medium, Required for Distribution)

**What:** Design a 3000×3000 JPG show cover.

**Requirements:**
- Minimum 1400×1400, recommended 3000×3000
- JPG or PNG, sRGB color space
- Readable at small sizes (podcast app thumbnails are tiny)
- Include show name prominently
- Under 500KB for ID3 embedding (original can be larger for RSS)

**Effort:** Variable (design task)  
**Impact:** Required for Apple/Spotify submission

### Priority 4: Build RSS Feed Generator (Medium, Required for Distribution)

**What:** Python module that generates a valid RSS feed from episode data.

**How:** Create `src/feed.py` that:
1. Reads all episodes from storage
2. Generates RSS XML with iTunes + Podcast 2.0 namespace
3. Includes `<podcast:transcript>` and `<podcast:chapters>` tags
4. Outputs `feed.xml`

**Effort:** ~4 hours  
**Impact:** This is the distribution pipeline — nothing else matters without it

### Priority 5: Set Up File Hosting (Medium, Required for Distribution)

**What:** Public HTTPS hosting for MP3s, transcripts, chapters, artwork, and RSS feed.

**Options:**
- **S3 + CloudFront** — Standard, reliable, pay-per-use
- **Cloudflare R2** — No egress fees (important for audio files!)
- **GitHub Pages** — Free, but 1GB limit and no byte-range support
- **Backblaze B2 + Cloudflare** — Cheapest option with free egress through CF

**Requirements:**
- HTTPS required (Podcast 2.0 spec mandates it)
- HTTP HEAD requests supported
- Byte-range requests supported (Apple requirement)
- CORS headers for web players
- Proper Content-Type headers

**Recommendation:** Cloudflare R2 for zero egress costs. At 21 minutes/day in 128kbps MP3 (~20MB/day), egress costs matter as the audience grows.

**Effort:** ~4 hours  
**Impact:** Makes everything accessible to the world

### Priority 6: Improve VTT Granularity (Medium, Medium Impact)

**What:** Split transcript into sentence-level cues instead of segment-level.

**How:** Split each segment's text into sentences, then distribute the segment's duration proportionally by word count:
```python
import re

def split_to_sentences(text):
    return re.split(r'(?<=[.!?])\s+', text)

def generate_fine_vtt(segments, output_path, speaker="George Carlin"):
    cues = []
    for seg in segments:
        sentences = split_to_sentences(seg['text'])
        total_words = sum(len(s.split()) for s in sentences)
        offset = seg['start_offset_seconds']
        for sent in sentences:
            word_ratio = len(sent.split()) / total_words
            duration = seg['duration_seconds'] * word_ratio
            cues.append((offset, offset + duration, sent))
            offset += duration
    # Write VTT from cues...
```

**Effort:** ~2 hours  
**Impact:** Apple Podcasts "read along" feature becomes usable

### Priority 7: Generate Episode Descriptions (Easy, Medium Impact)

**What:** Auto-generate a text summary of each episode for RSS `<description>`.

**How:** Collect story titles into a brief episode summary:
```
Today's top 10 stories from Hacker News: Microsoft forces Linux switch, Interactive airfoil explainer, Amazon kills palm payments, [...]
```

Could also be LLM-generated for more interesting descriptions.

**Effort:** ~1 hour  
**Impact:** Better discoverability and RSS compliance

### Priority 8: Add SRT Transcript (Easy, Low Impact)

**What:** Generate SRT alongside VTT.

**How:** SRT is almost identical to VTT:
- No `WEBVTT` header
- Sequential numbering for each cue
- Timestamps use `,` instead of `.` for milliseconds
- No `<v Speaker>` tags

**Effort:** ~30 minutes  
**Impact:** Marginal — Apple accepts VTT too

---

## Summary: What to Keep, Add, Change

### ✅ Keep (Working Correctly)
- ID3 CHAP/CTOC embedding via mutagen
- JSON chapters following Podcast 2.0 spec v1.2.0
- WebVTT transcript with `<v Speaker>` tags
- Plain text transcript with section markers
- Segments → chapters conversion (skipping interstitials)
- Two-phase timing (estimated → actual)

### ➕ Add (New Capabilities Needed)
1. Story titles + HN URLs in chapters (both JSON and ID3)
2. ID3 basic metadata (title, artist, album, artwork, genre, date)
3. Cover artwork (3000×3000 JPG)
4. RSS feed generator (`src/feed.py`)
5. File hosting (S3/R2/etc.)
6. Episode description generation
7. Sentence-level VTT cues

### 🔄 Change (Existing Code Modifications)
1. `segments_to_chapters()` — needs to accept story data for titles/URLs
2. `embed_chapters()` — should also embed basic ID3 metadata
3. `generate_vtt()` — needs finer granularity option for sentence-level cues
4. `generate_chapters_json()` — needs to include URLs from story data
5. Pipeline finalization — needs to pass story data through to chapter/transcript generation

### 📋 Implementation Order
1. **Fix chapter content** (titles + URLs) — 30 min
2. **Add ID3 metadata** — 1 hour  
3. **Create cover artwork** — variable
4. **Build RSS feed generator** — 4 hours
5. **Set up file hosting** — 4 hours
6. **Improve VTT granularity** — 2 hours
7. **Generate episode descriptions** — 1 hour
8. **Add SRT transcript** — 30 min

Items 1-2 are quick wins that improve existing episodes. Items 3-5 are required for public distribution. Items 6-8 are polish.
