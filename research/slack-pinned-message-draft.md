# DTFHN Slack Pinned Message Draft

## Primary Draft (Hackerspace Casual — Recommended)

```
📡 Daily Tech Feed: Hacker News (DTFHN)

Your daily ~20 min podcast covering the top 10 Hacker News stories — narrated by an AI George Carlin voice that doesn't pull punches.

🔧 How it works:
• Stories auto-fetched from the HN API
• Scripts written by Claude
• Audio rendered by Qwen3-TTS on local GPU hardware (3x RTX 3090)
• Zero human intervention from fetch to publish

📅 New episodes drop daily at 5 AM PT

🎧 Each episode has chapter markers — skip to the stories you care about. Every chapter links back to the HN discussion so you can dive deeper.

💻 It's fully open source: https://github.com/jhacksman/dtfhn

Built by PDX Hackerspace on an M4 Mac mini + GPU server. PRs welcome.

—
💬 Feedback, ideas, bugs? Drop 'em in the thread on any episode.
```

---

## Questions Before Finalizing

These need answers to lock in the final version:

1. **Posting schedule** — Is it strictly daily at 5 AM PT, or are there exceptions (weekends, holidays)? Should the pinned message commit to a specific time?

2. **Contribution instructions** — Should the pinned message tell members how to contribute? (e.g., "open an issue on GitHub", "suggest stories in-thread", "PRs welcome for X")

3. **Website / landing page** — Is there a dedicated site or podcast page to link to, or is GitHub the canonical home?

4. **AI transparency** — The draft is upfront about AI generation. Should it be? Some podcasts let the voice speak for itself. The Carlin voice is distinctive enough that people will figure it out, but being transparent is more on-brand for a hackerspace.

5. **Tone** — I went hackerspace casual. Want it more polished/professional? See Alt B below.

6. **Distribution** — Slack-only for now, or also Apple Podcasts / Spotify / RSS? If there are external links, they should go in the pinned message.

7. **Channel rules** — Any norms to set? (e.g., "don't spam", "keep discussion in episode threads", "no spoilers for the episode" — kidding on that last one)

---

## Alternative A: Ultra-Minimal

```
📡 DTFHN — Daily Tech Feed: Hacker News

Top 10 HN stories. ~20 min. AI-narrated (George Carlin voice). New episode every morning at 5 AM PT.

Each episode has chapter markers with HN discussion links.

Open source: https://github.com/jhacksman/dtfhn
```

Good if the channel speaks for itself and you don't want a wall of text pinned.

---

## Alternative B: Professional / Polished

```
📡 Welcome to Daily Tech Feed: Hacker News

This channel hosts DTFHN — a daily podcast that distills the top 10 stories from Hacker News into a ~20-minute briefing. Think of it as your morning tech news, delivered with personality.

What makes it unique:
• Fully automated pipeline — stories fetched, scripts generated, audio rendered with no human in the loop
• AI narration with a George Carlin–inspired voice via Qwen3-TTS
• Chapter markers in every episode with direct links to HN discussions
• Open source from top to bottom

New episodes are posted here daily at 5:00 AM PT.

📂 Source code: https://github.com/jhacksman/dtfhn
🏗️ Built by PDX Hackerspace

We'd love your feedback — reply in the thread on any episode, or open an issue on GitHub.
```

Better for external-facing or if non-hackerspace people will see the channel.

---

## Alternative C: Irreverent (Matching the Podcast's Tone)

```
📡 DTFHN — Daily Tech Feed: Hacker News

Every morning at 5 AM PT, a robot reads Hacker News so you don't have to.

An AI George Carlin tells you what matters from the top 10 HN stories in ~20 minutes. It's opinionated. It's automated. It runs on three overworked 3090s in a closet.

The whole thing — fetch, script, render, post — happens without a human touching it. Stories from HN API. Scripts by Claude. Voice by Qwen3-TTS. Duct tape by PDX Hackerspace.

Chapters + HN links in every episode. Skip around. Argue in the threads.

Source: https://github.com/jhacksman/dtfhn
```

Matches the podcast energy. Might be too much for a pinned message that people read once.

---

## Recommendation

Go with the **Primary Draft** (hackerspace casual). It's informative without being a novel, transparent about the tech without being clinical, and invites engagement without over-explaining. Adjust once the open questions are answered.
