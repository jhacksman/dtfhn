# DTFHN Podcast Distribution Research

> Researched: 2026-01-29
> Context: Daily ~20 min AI-generated podcast covering top 10 HN stories, George Carlin voice, generated at 5 AM daily via cron

---

## 1. Podcast Directories — Which Ones Matter?

### Tier 1 (Must Have)
| Directory | Market Share | Submission | Notes |
|-----------|-------------|------------|-------|
| **Apple Podcasts** | ~30-40% of listeners | Submit RSS feed via [Podcasts Connect](https://podcastsconnect.apple.com) | One-time submission; auto-updates from RSS. Review takes 1-5 days. |
| **Spotify** | ~30-35% of listeners | Submit via [Spotify for Podcasters](https://podcasters.spotify.com) (formerly Anchor) | One-time RSS submission. Can also host directly. |
| **YouTube / YouTube Music** | Growing rapidly | Submit RSS feed via [YouTube Studio](https://studio.youtube.com) → Podcasts | YouTube now ingests podcast RSS feeds directly. Audio-only is fine — they generate a static video. |

### Tier 2 (Important)
| Directory | Submission | Notes |
|-----------|------------|-------|
| **Amazon Music / Audible** | [Submit RSS](https://podcasters.amazon.com) | One-time submission. Growing audience, especially Alexa/Echo users. |
| **iHeartRadio** | [Submit RSS](https://www.iheart.com/content/submit-your-podcast/) | Large US radio audience. |
| **Overcast** | Auto-indexes from Apple Podcasts | No separate submission needed. Popular with tech audience — very relevant for HN content. |
| **Pocket Casts** | [Submit RSS](https://pocketcasts.com/submit) | Popular with Android/tech users. Direct RSS submission. |
| **Castro** | Auto-indexes from Apple Podcasts | iOS-only, popular with power users. |
| **Podcast Index** | [Submit RSS](https://podcastindex.org/add) | Open index powering many apps (Fountain, Podverse, etc.). Submit for max reach. |

### Tier 3 (Nice to Have)
| Directory | Notes |
|-----------|-------|
| **TuneIn** | Submit via email/form. Smaller audience. |
| **Pandora** | Shares backend with iHeartRadio now. |
| **Deezer** | European focus. RSS submission. |
| **Samsung Podcasts** | Uses Spotify's catalog. |
| **Podchaser** | Discovery/review platform. Submit RSS. |

### Dead/Deprecated
- **Google Podcasts** — Officially shut down in April 2024. Migrated to YouTube Music. Dead.
- **Stitcher** — Shut down August 2023. Dead.
- **Breaker** — Acquired by Twitter/X, shut down. Dead.

### Key Insight
Most directories just need your RSS feed URL submitted once. After that, they poll for new episodes automatically. **The RSS feed is the single source of truth.** Get the feed right, and distribution is essentially "submit URL to 5-8 places once, then forget."

---

## 2. Hosting Platforms — Comparison

### Platforms with APIs (Critical for Automation)

| Platform | Price | API? | API Episode Upload? | Notes |
|----------|-------|------|---------------------|-------|
| **Transistor.fm** | $19/mo (starter) | ✅ Full REST API | ✅ Yes — upload audio + create/publish episode | **Best option for automation.** JSON:API spec. Upload audio via presigned URL, create episode, publish. API key auth. Rate limit: 10 req/10 sec. [API docs](https://developers.transistor.fm) |
| **Buzzsprout** | $12/mo (3hr/mo) | ✅ REST API | ✅ Yes — create episodes with audio URL | Token auth. Can POST episodes with audio_url pointing to external file. [API docs](https://github.com/Buzzsprout/buzzsprout-api). Limitation: 3hr/mo on cheap plan (we need ~10hr/mo for daily 20min). $18/mo for 6hr, $24/mo for 12hr. |
| **Podbean** | $14/mo (unlimited) | ✅ OAuth2 API | ✅ Yes — upload + publish | Full API with episode publishing. OAuth2 flow (more complex). Unlimited audio storage/bandwidth. [Developer portal](https://developers.podbean.com). |
| **RSS.com** | $12.99/mo | ✅ API | ✅ Yes | API available. Less documented than Transistor/Buzzsprout. |
| **Simplecast** | $15/mo | ✅ API | ✅ Yes | Good API, used by larger shows. |
| **Captivate** | $19/mo | ✅ API | ✅ Yes | API available for episode management. |

### Platforms WITHOUT Useful APIs

| Platform | Price | Notes |
|----------|-------|-------|
| **Spotify for Podcasters** (fka Anchor) | Free | No programmatic upload API. Web dashboard only. Free hosting but manual. |
| **Libsyn** | $5-$20/mo | Legacy platform. No modern API for episode creation. FTP upload possible but clunky. |

### Recommendation for DTFHN

**Transistor.fm** is the strongest choice:
1. Full API with episode creation + audio upload
2. Auto-distributes to Apple, Spotify, YouTube, etc.
3. Simple API key auth (no OAuth dance)
4. Built-in analytics
5. YouTube auto-posting feature
6. $19/mo unlimited episodes
7. Well-documented, actively maintained API

**Runner-up: Buzzsprout** — Solid API, but hour-based pricing is annoying for daily shows.

**Budget option: Self-host RSS + use Podbean for directory submission** — See section 4.

---

## 3. RSS Feed Requirements

### Minimum Valid Podcast RSS Feed

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:podcast="https://podcastindex.org/namespace/1.0"
  xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <!-- Required Channel Tags -->
  <title>Daily Tech Feed: Hacker News</title>
  <link>https://dtfhn.com</link>
  <description>Daily ~20 minute AI-generated podcast covering the top 10 Hacker News stories, delivered with irreverent wit.</description>
  <language>en-us</language>

  <!-- Apple Required Tags -->
  <itunes:type>episodic</itunes:type>
  <itunes:author>DTFHN</itunes:author>
  <itunes:owner>
    <itunes:name>DTFHN</itunes:name>
    <itunes:email>hello@dtfhn.com</itunes:email>
  </itunes:owner>
  <itunes:image href="https://dtfhn.com/artwork.jpg"/>
  <itunes:category text="Technology">
    <itunes:category text="Tech News"/>
  </itunes:category>
  <itunes:explicit>true</itunes:explicit>

  <!-- Podcast Index Tags (modern, open standard) -->
  <podcast:locked>no</podcast:locked>
  <podcast:guid>unique-guid-here</podcast:guid>

  <!-- Episodes -->
  <item>
    <title>Episode 42 — Jan 29, 2026</title>
    <description>Today's top stories from Hacker News...</description>
    <pubDate>Wed, 29 Jan 2026 06:00:00 -0800</pubDate>
    <enclosure url="https://cdn.dtfhn.com/episodes/2026-01-29.mp3"
               length="19200000"
               type="audio/mpeg"/>
    <guid isPermaLink="false">dtfhn-2026-01-29</guid>
    <itunes:duration>1200</itunes:duration>
    <itunes:episodeType>full</itunes:episodeType>
    <itunes:explicit>true</itunes:explicit>
    <itunes:summary>Today's top stories from Hacker News...</itunes:summary>
  </item>
</channel>
</rss>
```

### Apple Podcasts Specific Requirements
- **Artwork:** Minimum 1400×1400px, maximum 3000×3000px. JPEG or PNG. sRGB color space. Must be square.
- **RSS 2.0 compliant** with `itunes:` namespace
- **Enclosure tag:** Must include `url`, `length` (file size in bytes), and `type` (audio/mpeg for MP3)
- **GUID:** Must be globally unique and never change
- **Dates:** RFC 2822 format (e.g., `Wed, 6 Jul 2014 13:00:00 -0700`)
- **HTTP HEAD and byte-range requests** must be supported by hosting server (S3/R2/CDN all support this)
- **ASCII filenames/URLs** only
- **Case-sensitive XML tags** — `<itunes:category text="Technology">` not `technology`
- **XML entities:** Use `&amp;` `&apos;` `&lt;` `&gt;` — NOT `&rsquo;` or HTML entities
- At least one episode required before submission

### Audio Format Best Practices
- **MP3** (most compatible) or **M4A/AAC**
- **Bitrate:** 64-128 kbps for speech (96 kbps mono is sweet spot for talk shows)
- **Sample rate:** 44.1 kHz
- **Mono** for single-speaker content (our use case)
- **ID3 tags** embedded in MP3 (title, artist, album, artwork)

---

## 4. Self-Hosting Option

### Architecture: S3/R2 + Static RSS XML

Yes, fully viable. Many podcasts self-host successfully.

```
┌─────────────────────────────────────────────┐
│  5 AM Cron Job                              │
│  1. Generate episode content (LLM)          │
│  2. Generate audio (TTS on quato)           │
│  3. Encode to MP3                           │
│  4. Upload MP3 to R2/S3                     │
│  5. Regenerate RSS XML                      │
│  6. Upload RSS XML to R2/S3                 │
│  7. (Optional) Ping directories             │
└─────────────────────────────────────────────┘

Storage: Cloudflare R2 (free egress!) or AWS S3
CDN: Cloudflare (if R2) or CloudFront (if S3)
RSS: Static XML file, regenerated daily
Domain: dtfhn.com → R2 bucket with custom domain
```

### Cost Comparison
| Component | Cloudflare R2 | AWS S3 + CloudFront |
|-----------|---------------|---------------------|
| Storage (1GB/mo) | Free (10GB free tier) | ~$0.02/mo |
| Bandwidth | **Free** (R2 has zero egress fees) | $0.085/GB |
| Custom domain | Free (Cloudflare) | ~$1/mo |
| **Total (1000 listeners)** | **~$0/mo** | **~$5-10/mo** |

### Cloudflare R2 Self-Host Setup
1. Create R2 bucket `dtfhn-podcast`
2. Enable public access with custom domain `cdn.dtfhn.com`
3. Upload MP3s to `episodes/YYYY-MM-DD.mp3`
4. Generate and upload `feed.xml` to bucket root
5. Point `https://cdn.dtfhn.com/feed.xml` as RSS feed URL
6. R2 supports HTTP HEAD and byte-range requests ✅

### Pros of Self-Hosting
- **$0/mo** with R2 (vs $19/mo for Transistor)
- Full control over RSS feed format
- No vendor lock-in
- Can generate RSS programmatically (just template a XML file)
- No upload limits or hour caps

### Cons of Self-Hosting
- No built-in analytics (need to parse access logs or add analytics pixel)
- Must manually submit RSS to each directory
- No web player / episode page (build your own or skip)
- Must handle RSS validation yourself
- No automatic YouTube posting

### Hybrid Approach (Recommended)
Self-host audio on R2 + use a cheap hosting platform just for RSS feed management and directory distribution. Or: self-host everything and submit RSS URL to directories manually (one-time effort).

---

## 5. YouTube Distribution

### YouTube Podcasts (RSS Ingestion)
- YouTube now accepts podcast RSS feeds directly
- Go to YouTube Studio → Content → Podcasts → "Submit RSS feed"
- YouTube auto-creates a playlist and generates video from audio + your podcast artwork
- Episodes appear as regular videos in a "Podcast" playlist
- Audio-only is fine — YouTube adds a static image background

### YouTube Data API (Programmatic Upload)
- YouTube Data API v3 allows automated video upload
- Can upload audio-as-video (generate a simple video: static image + audio waveform)
- OAuth2 required (more complex than API key)
- Daily upload quota: 6 videos/day by default
- **Tools:** `ffmpeg` to mux static image + audio into MP4, then upload via API

### YouTube Upload Script Pattern
```bash
# Convert audio to video with static artwork
ffmpeg -loop 1 -i artwork.jpg -i episode.mp3 \
  -c:v libx264 -tune stillimage -c:a aac \
  -b:a 192k -pix_fmt yuv420p -shortest output.mp4

# Upload via YouTube API (using google-api-python-client)
python upload_to_youtube.py --file=output.mp4 \
  --title="DTFHN — Jan 29, 2026" \
  --description="Top 10 HN stories..."
```

### Recommendation
Use RSS ingestion first (zero maintenance). If you want custom thumbnails or descriptions per episode, use the API approach later.

---

## 6. Social/Community Channels

### Telegram
- Create a Telegram Channel (broadcast-only)
- Bot API supports `sendAudio` with MP3 files up to 50MB
- Can send episode link + show notes daily
- **Fully automatable** via Telegram Bot API
- Great for tech audience

### Discord
- Create a Discord server or channel
- Bot can upload audio files (max 25MB without Nitro, 100MB with boost)
- 20-min MP3 at 96kbps ≈ 14MB — fits within limit ✅
- Better: Post link to episode + show notes
- **Fully automatable** via Discord.js/discord.py

### X/Twitter
- Post episode link + key highlights
- Twitter Spaces doesn't support pre-recorded content
- Can use Twitter API for automated posting
- Include audiogram clip (30-60 sec video snippet) for engagement

### Reddit
- Post to r/hackernews, r/technology, r/programming
- Reddit API for automated posting (be careful of spam rules)
- Better: Manual posting or very light touch

### Hacker News (Show HN)
- Can't automate (would be spam)
- Do a "Show HN" launch post once
- Occasional posts linking to particularly interesting episodes

### Newsletter/Email
- Weekly or daily email with episode link + show notes
- Buttondown, Resend, or Mailchimp
- Can automate with API

---

## 7. Similar Podcasts — What They Use

### HN-Adjacent / Daily Tech News Podcasts

| Podcast | Type | Platform/Distribution |
|---------|------|----------------------|
| **The Changelog** | Weekly, human-hosted | Self-hosted (Fastly CDN), all major directories |
| **Hacker News Recap** | Various | Spotify, Apple Podcasts |
| **TLDR Newsletter** | Daily text → audio | Spotify, Apple (uses standard hosting) |
| **TechMeme Ride Home** | Daily 20 min | Art19 (enterprise hosting), all directories |
| **Daily Tech News Show** | Daily | Patreon + Spotify + Apple, Libsyn hosting |
| **NotebookLM podcasts** | AI-generated | Google's own infra, not publicly distributed as podcast feed |
| **Perplexity Daily Podcast** | AI-generated daily | Standard podcast directories, likely custom infra |

### Key Observations
- TechMeme Ride Home is closest comp (daily, ~20 min, tech news) — uses enterprise hosting (Art19/iHeart)
- Most daily tech podcasts use standard hosting platforms
- AI-generated podcasts are new — no established pattern yet
- Self-hosting with CDN is common among tech-savvy creators

---

## 8. Automation — API Capabilities Matrix

### The Critical Question: Can We Publish Daily at 5 AM Without Human Intervention?

| Platform | Auth | Upload Audio | Create Episode | Auto-Publish | Verdict |
|----------|------|-------------|----------------|-------------|---------|
| **Transistor** | API Key | ✅ Presigned URL upload | ✅ POST /v1/episodes | ✅ Set status=published | **Best. Simple auth, full automation.** |
| **Buzzsprout** | Token | ✅ Via audio_url | ✅ POST /episodes.json | ✅ Set published | **Good. Simple. Hour caps annoying.** |
| **Podbean** | OAuth2 | ✅ Upload API | ✅ Publish endpoint | ✅ Yes | **Full-featured but OAuth2 is heavier.** |
| **Simplecast** | API Key | ✅ Yes | ✅ Yes | ✅ Yes | **Good option.** |
| **Self-hosted R2** | N/A | ✅ R2 API/wrangler | ✅ Generate XML | ✅ Just upload | **Full control. Zero cost.** |
| **Spotify for Podcasters** | None | ❌ No API | ❌ Dashboard only | ❌ Manual | **Not viable for automation.** |
| **Libsyn** | FTP | ⚠️ FTP upload | ❌ Limited | ❌ Clunky | **Not recommended.** |

### Transistor API Workflow (Recommended)

```bash
# Step 1: Get presigned upload URL
curl -X POST https://api.transistor.fm/v1/episodes/authorize_upload \
  -H "x-api-key: YOUR_KEY" \
  -d "filename=2026-01-29.mp3"
# Returns: { upload_url, content_type, audio_url }

# Step 2: Upload audio to presigned URL
curl -X PUT "$UPLOAD_URL" \
  -H "Content-Type: audio/mpeg" \
  --data-binary @episode.mp3

# Step 3: Create and publish episode
curl -X POST https://api.transistor.fm/v1/episodes \
  -H "x-api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "episode": {
      "show_id": "YOUR_SHOW_ID",
      "title": "DTFHN — Jan 29, 2026",
      "summary": "Top 10 HN stories for today...",
      "description": "<p>Full show notes with links...</p>",
      "audio_url": "'$AUDIO_URL'",
      "status": "published",
      "explicit": true,
      "type": "full"
    }
  }'
```

### Self-Hosted R2 Workflow (Budget)

```python
import boto3
from datetime import datetime
from jinja2 import Template

# Upload MP3
s3 = boto3.client('s3',
    endpoint_url='https://YOUR_ACCT.r2.cloudflarestorage.com',
    aws_access_key_id='R2_KEY',
    aws_secret_access_key='R2_SECRET'
)
s3.upload_file('episode.mp3', 'dtfhn-podcast',
    f'episodes/{date}.mp3',
    ExtraArgs={'ContentType': 'audio/mpeg'})

# Regenerate RSS feed
feed_xml = render_rss_template(episodes)  # Jinja2 template
s3.put_object(Bucket='dtfhn-podcast', Key='feed.xml',
    Body=feed_xml, ContentType='application/rss+xml')
```

---

## 9. Recommended Strategy

### Phase 1: Launch (Week 1)
1. **Self-host on Cloudflare R2** — $0/mo, full control
2. Generate RSS feed programmatically (Python script)
3. Submit RSS to: Apple Podcasts, Spotify, YouTube, Amazon Music, Pocket Casts, Podcast Index
4. Set up Telegram channel for direct distribution
5. One-time directory submissions (30 min of work)

### Phase 2: Upgrade if Needed (Month 2+)
If analytics/management becomes painful:
1. Move to **Transistor.fm** ($19/mo) for better analytics + managed distribution
2. Use their API for daily publishing
3. They handle RSS feed generation, web player, and YouTube auto-posting

### Phase 3: Growth
1. Add YouTube API upload with custom thumbnails
2. Newsletter/email distribution
3. Social media clips (audiograms)
4. Cross-post highlights to X/Twitter

### Why Start Self-Hosted?
- Zero cost while validating the concept
- Full control over the pipeline
- Easy to migrate (just redirect the RSS feed URL)
- Daily 20-min episodes × 30 days = ~600 min = 10 hours of audio/mo = ~850MB at 96kbps
- R2 handles this trivially with zero egress costs

---

## 10. Open Questions

1. **Explicit content flag** — George Carlin voice will likely include adult language. Mark as explicit? (Yes, safer.)
2. **Copyright/TOS** — AI-generated voice mimicking a real (deceased) person. Legal gray area. May need disclaimer.
3. **Apple review** — Will Apple approve an AI-generated podcast? They have content guidelines. Should be fine as long as it's clearly labeled.
4. **Analytics without hosting platform** — Could use Podcast Analytics prefix service (like OP3.dev, Podtrac, Chartable) for download tracking with self-hosted feed.
5. **Episode numbering** — Date-based (`DTFHN — Jan 29, 2026`) vs sequential (`Episode 42`)?
