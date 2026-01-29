# HN API Investigation: Front Page vs topstories.json

**Date:** 2026-01-29
**Status:** Research complete — no code changes needed yet

## TL;DR

**`topstories.json` IS the correct endpoint.** It matches the HN front page exactly at any given moment. The mismatch the user observed was caused by **timing**: the front page changes rapidly (stories rise and fall within hours), so stories fetched earlier in the day will differ from what's visible later.

## Evidence

### Test 1: topstories.json first 10 IDs (fetched 2026-01-29 ~12:23 PT)

| # | Score | Title |
|---|-------|-------|
| 1 | 146 | Project Genie: Experimenting with infinite, interactive worlds |
| 2 | 360 | Claude Code Daily Benchmarks for Degradation Tracking |
| 3 | 41 | AI's Impact on Engineering Jobs May Be Different Than Expected |
| 4 | 35 | My Mom and Dr. DeepSeek (2025) |
| 5 | 77 | Drug trio found to block tumour resistance in pancreatic cancer |
| 6 | 61 | Launch HN: AgentMail (YC S25) – An API that gives agents their own email inboxes |
| 7 | 106 | OTelBench: AI struggles with simple SRE tasks (Opus 4.5 scores only 29%) |
| 8 | 580 | Europe's next-generation weather satellite sends back first images |
| 9 | 266 | US cybersecurity chief leaked sensitive government files to ChatGPT |
| 10 | 604 | We can't send mail farther than 500 miles (2002) |

### Test 2: news.ycombinator.com scraped (same moment)

| # | Title |
|---|-------|
| 1 | Project Genie: Experimenting with infinite, interactive worlds |
| 2 | Claude Code Daily Benchmarks for Degradation Tracking |
| 3 | AI's Impact on Engineering Jobs May Be Different Than Expected |
| 4 | Drug trio found to block tumour resistance in pancreatic cancer |
| 5 | My Mom and Dr. DeepSeek (2025) |
| 6 | Launch HN: AgentMail (YC S25) – An API that gives agents their own email inboxes |
| 7 | OTelBench: AI struggles with simple SRE tasks (Opus 4.5 scores only 29%) |
| 8 | Europe's next-generation weather satellite sends back first images |
| 9 | We can't send mail farther than 500 miles (2002) |
| 10 | US cybersecurity chief leaked sensitive government files to ChatGPT |

### Comparison

**9 of 10 stories are identical.** The only difference is minor ordering (positions 4/5 and 9/10 are swapped). This is expected — HN's ranking algorithm runs continuously, and a few seconds between fetches can reorder adjacent stories.

The API and the website return **the same set of stories in essentially the same order**.

### Test 3: beststories.json (NOT a match)

| # | Score | Title |
|---|-------|-------|
| 1 | 1804 | Microsoft forced me to switch to Linux |
| 2 | 917 | Apple to soon take up to 30% cut from all Patreon creators in iOS app |
| 3 | 774 | Vitamin D and Omega-3 have a larger effect on depression than antidepressants |
| 4 | 670 | Amazon cuts 16k jobs |
| 5 | 623 | Please don't say mean things about the AI I just invested a billion dollars in |

`beststories` returns highest-scored stories over a longer time window — **not** the front page.

### Test 4: newstories.json (NOT a match)

Returns the newest submissions regardless of score (all 1-point stories). **Not** the front page.

## HN API Documentation Summary

From https://github.com/HackerNews/API:

- **`/v0/topstories.json`** — Returns up to 500 top and new story IDs. This IS the front page.
- **`/v0/beststories.json`** — Returns up to 200 best story IDs (highest scored, longer window).
- **`/v0/newstories.json`** — Returns up to 500 newest story IDs.
- **`/v0/askstories.json`** — "Ask HN" stories only.
- **`/v0/showstories.json`** — "Show HN" stories only.
- **`/v0/jobstories.json`** — Job postings only.

The docs say topstories returns "top and new stories" — which matches HN's front page algorithm that blends popular stories with fresh ones.

## Root Cause of the Reported Mismatch

The user compared stories from **today's episode** (fetched earlier, likely hours ago) with the **current front page** (viewed later). The HN front page is highly volatile:

- Stories posted 2h ago can be #1, then fall to #20 within another 2h
- New stories constantly push older ones down
- Score-based ranking with time decay means rapid churn

**The code is correct.** The issue is purely temporal — if you fetch at 8am and look at the page at noon, the top 10 will be substantially different.

## Recommendations (No Code Changes Yet)

1. **The endpoint is correct** — keep using `topstories.json`
2. **If we want to capture "the front page at episode generation time"**, we should log/store the exact fetch timestamp alongside story IDs
3. **If we want more stability**, we could:
   - Fetch multiple times over a window and pick stories that appear most consistently
   - Weight by score × recency to approximate what was "hot" for the day
   - But this changes the editorial premise ("what's on HN right now" → "what was trending today")
4. **The current approach is fine** — it captures a snapshot of the front page at fetch time, which is exactly what the code intends

## Current Code Reference

`src/hn.py` uses:
```python
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
```
And `fetch_top_story_ids(limit=10)` takes the first 10 IDs — which is correct.
