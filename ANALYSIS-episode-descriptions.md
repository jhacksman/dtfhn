# Analysis: Episode Descriptions with Article Links

**Date:** 2026-01-31
**Status:** Analysis only — no implementation

---

## 1. Episode Description with Links — Feasibility and Format

### Current State

The `generate_episode_description()` function in `scripts/upload_to_r2.py` generates descriptions like:

> "Your Daily Tech Feed covering the top 10 stories on Hacker News for January 31, 2026. Featuring: Antirender: remove the glossy shine on architectural renderings, Euro firms must ditch Uncle Sam's clouds and go EU-native, Sumerian Star Map Recorded the Impact of an Asteroid (2024), ..."

- Current description is **428 characters** (well within all limits)
- It lists up to 5 story titles, then ", and more"
- Stored in `data/feed_episodes.json` as `description` field
- Used in both `<description>` and `<itunes:summary>` RSS tags

### Does the Code Have Access to Story URLs?

**Yes.** `generate_episode_description()` already reads `stories.json`, which contains both `title` and `url` for every story. Adding URLs to the description requires zero new data plumbing — it's just a format change in the string construction.

The `stories.json` format:
```json
{
  "id": "46829147",
  "title": "Antirender: remove the glossy shine on architectural renderings",
  "url": "https://antirender.com/",
  "score": 1378,
  ...
}
```

### Platform Limits and Rendering

| Platform | Description Limit | HTML Support | Link Auto-Detection |
|----------|------------------|-------------|---------------------|
| **Apple Podcasts** | ~4,000 chars displayed | Limited HTML in `<content:encoded>`. `<description>` is plain text. | **Yes** — auto-links plaintext URLs |
| **Spotify** | ~600 chars visible, truncates after | No HTML rendering | **Yes** — auto-links plaintext URLs |
| **Overcast** | Very generous, shows full description | Some HTML | **Yes** — auto-links URLs |
| **Pocket Casts** | ~4,000+ chars | Limited HTML | **Yes** — auto-links URLs |
| **RSS spec** | No hard limit | HTML in `<content:encoded>`, plain text in `<description>` | N/A |

**Key insight:** Most podcast apps auto-detect and linkify plaintext URLs. You do NOT need HTML `<a>` tags. Plain `https://` URLs will become clickable in Apple Podcasts, Overcast, Pocket Casts, and most other apps.

**Spotify is the constraint** — it only shows ~600 characters before truncation, and many users won't tap "more." However, Spotify is probably not the primary audience for a Hacker News podcast.

### HTML Links vs Plaintext URLs

- **`<description>` tag:** Should be plain text per RSS spec. Most aggregators strip HTML from this field.
- **`<content:encoded>` tag:** Supports HTML (including `<a href>`). Apple Podcasts will render these. This is the proper place for rich descriptions.
- **`<itunes:summary>` tag:** Plain text only. Apple strips HTML.

**Recommendation:** Use plain text URLs in `<description>`. Optionally, add `<content:encoded>` with HTML links as a progressive enhancement. Most apps will auto-link the plaintext URLs anyway.

---

## 2. Transcript Links — Is It Possible?

### VTT Spec and URLs

The WebVTT spec supports **cue payload markup** including:
- `<b>`, `<i>`, `<u>` — styling
- `<v Speaker>` — voice tags (already used)
- `<c.classname>` — CSS classes
- `<lang>` — language

**WebVTT does NOT support `<a>` href links.** There is no hyperlink element in the VTT spec.

### Apple Podcasts Transcript Rendering

Apple Podcasts displays VTT transcripts as synchronized text (word-by-word highlighting). It does **not** render URLs as clickable links, even if they appear in the text. The transcript view is purely a text-following experience — no interactive elements.

### Other Transcript Formats

- **SRT:** Even more limited than VTT. No markup at all.
- **TTML (Timed Text Markup Language):** Supports richer markup but podcasting apps don't use it.
- **JSON transcript (Podcasting 2.0):** Could theoretically include metadata, but apps don't render links from it.

### Verdict: Dead End

Transcript links are **not feasible**. VTT doesn't support them, Apple Podcasts doesn't render them, and no podcast app treats transcript text as interactive. Not worth pursuing.

---

## 3. Character Budget Analysis

### Real Data (2026-01-31 episode, 9 stories)

| Format | Characters |
|--------|-----------|
| Current description (5 titles, no URLs) | 428 |
| Title + article URL, double-spaced | **1,151** |
| Title + HN URL, double-spaced | **943** |
| Bullet format (• Title — URL) | **1,179** |

### Platform Fit

| Format | Apple (4000) | Spotify (600) | Overcast (4000+) |
|--------|:---:|:---:|:---:|
| Current (no URLs) | ✅ | ✅ | ✅ |
| Article URLs (~1,150) | ✅ | ❌ (truncated) | ✅ |
| HN URLs (~950) | ✅ | ❌ (truncated) | ✅ |

### URL Length Variability

Article URLs vary wildly:
- Short: `https://antirender.com/` (24 chars)
- Long: `https://blog.globalping.io/we-have-ipinfo-at-home-or-how-to-geolocate-ips-in-your-cli-using-latency/` (100 chars)

HN URLs are consistent: `https://news.ycombinator.com/item?id=46829147` (46 chars each)

With 10 stories × 46 chars = 460 chars for HN URLs alone. Add titles (~50 chars avg × 10 = 500) + formatting = **~1,000-1,200 chars** total.

### Truncation Strategy for Spotify

**Option A: Accept Spotify truncation.** Put a header line first ("Stories covered:"), then list stories. Spotify shows the first ~600 chars (roughly 4-5 stories with URLs), with a "more" button for the rest. Apple and Overcast show everything.

**Option B: Two-tier description.** First 600 chars = prose summary (current format). After that = full story list with URLs. Spotify users see the summary; Apple users see both.

**Option C: HN URLs only.** Shorter than article URLs, consistent length. Gets ~6-7 stories visible on Spotify.

**Recommended: Option B** — best of both worlds. Spotify gets a clean summary, Apple/Overcast users get the full link list.

---

## 4. Recommended Approach

### Proposed Description Format

```
Your Daily Tech Feed covering the top 10 stories on Hacker News for January 31, 2026.

Stories covered:

1. Antirender: remove the glossy shine on architectural renderings
   https://antirender.com/

2. Euro firms must ditch Uncle Sam's clouds and go EU-native
   https://www.theregister.com/2026/01/30/euro_firms_must_ditch_us/

3. Sumerian Star Map Recorded the Impact of an Asteroid (2024)
   https://archaeologyworlds.com/5500-year-old-sumerian-star-map-recorded/

[... all stories ...]
```

**Why this format:**
- Numbered list is scannable
- URL on its own line = easy tap target on mobile
- Header line stays within Spotify's 600-char window
- Article URLs (not HN URLs) — users want the actual article, not the HN comment page
- Chapters already link to HN discussion; description links to the article itself

### Files to Change

1. **`scripts/upload_to_r2.py`** — Modify `generate_episode_description()`:
   - Change from "Featuring: title1, title2, ..." to numbered list with URLs
   - Keep the opening prose line as-is (for Spotify preview)
   - Include ALL stories (not just first 5)
   - Remove the 600-char Spotify limit enforcement (accept truncation)

2. **`src/feed.py`** — No changes needed. It already uses the `description` field from the manifest as-is. Both `<description>` and `<itunes:summary>` are set from this field.

3. **Optional enhancement:** Add `<content:encoded>` support to `feed.py` for HTML-formatted descriptions with `<a href>` links. This is a progressive enhancement — not required since most apps auto-link URLs.

### Estimated Effort

- **Core change:** ~30 minutes. Modify `generate_episode_description()` format string.
- **Optional HTML enhancement:** ~1 hour. Add `<content:encoded>` to `feed.py` episode items.
- **Backfill existing episodes:** ~15 minutes. Re-run description generation for 2026-01-29 and 2026-01-30 episodes and re-upload feed.

### Gotchas

1. **Spotify truncation is inevitable.** Any format with all URLs will exceed 600 chars. This is fine — Spotify has a "more" button, and Spotify is unlikely the primary platform for HN listeners.

2. **Don't put URLs in `<itunes:summary>`** if you add `<content:encoded>`. Apple prefers `<content:encoded>` for rich text and `<itunes:summary>` for plain text. But since we're using plaintext URLs (not HTML), using the same text for both is fine.

3. **Re-upload feed after changing descriptions.** Existing episodes in `feed_episodes.json` already have descriptions baked in. You'll need to either:
   - Manually update the JSON, or
   - Delete the entry, re-run upload_to_r2.py (which re-generates the description)

4. **Story count varies.** Some episodes have 9 stories (like 2026-01-31), others have 10. The format handles both naturally since it's a numbered list.

5. **`content:encoded` namespace is already registered** in `feed.py` (`CONTENT_NS`), but never used for episode items. Adding it would be straightforward.

---

## Summary

| Question | Answer |
|----------|--------|
| Can we add URLs to descriptions? | **Yes, trivially.** Data already available. |
| Will URLs be clickable? | **Yes** — Apple, Overcast, Pocket Casts auto-link plaintext URLs |
| Will it fit on Spotify? | **No** — but truncation with "more" button is acceptable |
| Can we put links in VTT transcripts? | **No** — VTT spec doesn't support links, Apple doesn't render them |
| What needs to change? | `generate_episode_description()` in `upload_to_r2.py` (~30 min) |
| Any blockers? | None. This is a low-risk, high-value change. |
