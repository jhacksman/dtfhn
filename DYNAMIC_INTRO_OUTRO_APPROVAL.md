# Dynamic Intro/Outro System — Approval Document

**Status:** PENDING APPROVAL

---

## Overview

This system generates a fresh intro and outro for every episode at runtime. The pipeline resolves the current date when it runs, fetches that day's Hacker News stories, and produces all content — scripts, interstitials, intro, outro — for that date. Nothing is hardcoded to a specific day.

Throughout this document:
- `{DATE}` = the runtime date in ISO format (e.g., `2026-01-28`)
- `{TTS_DATE}` = the runtime date spelled out for speech (e.g., "January twenty-eighth, twenty twenty-six")

Examples use content from the January 28, 2026 episode because that data exists on disk. The system itself is date-agnostic.

---

## 1. INTRO SPEC

### Context Given to Claude

The model receives the full episode body: all 10 story scripts (`01_-_script_01.txt` through `19_-_script_10.txt`) and all 9 interstitial transitions (`02_-_interstitial_01_02.txt` through `18_-_interstitial_09_10.txt`). No intro or outro exists yet — the model generates the intro first.

### Prompt

```
You are writing the INTRO for today's episode of "Daily Tech Feed," a daily tech podcast in the voice of George Carlin covering the top stories from Hacker News.

Today's date (TTS-formatted): {TTS_DATE}

Below is the full episode body — all 10 story scripts and 9 interstitials. Read them to understand today's themes, then write a short, punchy intro.

RULES:
- 40 to 80 words. No exceptions.
- TTS output ONLY. No markdown, no asterisks, no headers, no formatting of any kind.
- Spell out all numbers: "ten" not "10", "twenty twenty-six" not "2026"
- Spell out all abbreviations: "A I" not "AI", "H N" not "HN"
- Write exactly what a voice should say out loud. Nothing more.
- Must include the spoken intro line: "Welcome to your daily tech feed for Hacker News" (this IS the branding — don't separately name the podcast)
- Must include the TTS-formatted date
- Carlin voice: observational, wry, a little disgusted with the world but amused by it
- Reference two or three of today's actual story themes to tease what's coming
- Do NOT list all ten stories. Pick the ones that make the best hook.
- End with something that makes the listener want to keep going.

EPISODE BODY:
{scripts_and_interstitials}
```

### Required Elements

| Element | Format |
|---|---|
| Today's date | `{TTS_DATE}` — runtime-resolved, fully spelled out for speech |
| Spoken intro line | "Welcome to your daily tech feed for Hacker News" |

### Word Count

40–80 words.

### TTS Rules

- No markdown whatsoever — no bold, italic, headers, bullets, links
- No numerals — all numbers spelled out ("sixteen thousand" not "16,000")
- No abbreviations — spell them out with spaces ("A I" not "AI", "C plus plus" not "C++")
- No special characters that wouldn't be spoken aloud
- Every character in the output should be a spoken word or standard punctuation

### Example Intros

*These examples are drawn from the January 28, 2026 episode to illustrate tone, structure, and theme-pulling. On any other date, the intro would reference that day's stories instead.*

**Example A:**
It's January twenty-eighth, twenty twenty-six. Welcome to your daily tech feed for Hacker News, delivered with the respect it deserves. Today, Microsoft drove another loyal user to Linux, Amazon killed its palm-scanning payment system and sixteen thousand jobs in the same week, and WhatsApp rewrote a hundred sixty thousand lines of C plus plus into Rust. Buckle up.

**Example B:**
January twenty-eighth, twenty twenty-six. Welcome to your daily tech feed for Hacker News, pulling today's finest stories. We've got a guy who built a spinning top that runs for two hours, a browser agent that's smarter because it's dumber, and Amazon quietly deleting your palm prints while loudly deleting your coworkers. I'm your host, and these are the stories corporate America hopes you'll scroll past.

**Example C:**
Welcome to your daily tech feed for Hacker News, January twenty-eighth, twenty twenty-six. Today we're talking about a beautiful interactive physics lesson that puts every university lecture to shame, open-source A I agents learning to use computers, and a terminal window manager for people who think mice are for cowards. Let's get into it.

---

## 2. OUTRO SPEC

### Context Given to Claude

The model receives the full episode body (all 10 scripts + 9 interstitials) AND the generated intro. This lets the outro bookend the episode coherently — it can callback to themes introduced at the top.

### Prompt

```
You are writing the OUTRO for today's episode of "Daily Tech Feed," a daily tech podcast in the voice of George Carlin covering the top stories from Hacker News.

Today's date (TTS-formatted): {TTS_DATE}

Below is the full episode — intro, all 10 story scripts, and 9 interstitials. Read everything, then write a closing outro.

RULES:
- 60 to 120 words. No exceptions.
- TTS output ONLY. No markdown, no asterisks, no headers, no formatting of any kind.
- Spell out all numbers: "ten" not "10", "twenty twenty-six" not "2026"
- Spell out all abbreviations as spoken words: "A I" not "AI"
- Write exactly what a voice should say out loud. Nothing more.
- ALL of the following MUST appear in the outro (use these exact TTS-friendly phrasings):
    1. The date: "{TTS_DATE}"
    2. The spoken outro line: "That's been your daily tech feed for Hacker News"
    3. "Not affiliated with Hacker News or Y Combinator"
    4. "This podcast is entirely A I generated"
    5. "Voice inspired by George Carlin"
    6. "Scripts by Claude Opus four point five"
    7. "Voice by Qwen three T T S"
- Carlin voice: wrap up with something memorable — an observation, a callback, a final jab
- Reference one or two themes from today's episode to tie the bow
- Weave the required elements naturally. Do NOT just list them like a legal disclaimer.
- End on a strong line.

EPISODE:
{intro_and_scripts_and_interstitials}
```

### Required Elements

Every outro MUST contain all of the following. The date is resolved at runtime; the rest are fixed strings.

| Element | Exact TTS Phrasing |
|---|---|
| Today's date | `{TTS_DATE}` — resolved at runtime |
| Spoken outro line | "That's been your daily tech feed for Hacker News" |
| Non-affiliation | "Not affiliated with Hacker News or Y Combinator" |
| A I disclosure | "This podcast is entirely A I generated" |
| Voice credit | "Voice inspired by George Carlin" |
| Script credit | "Scripts by Claude Opus four point five" |
| TTS engine credit | "Voice by Qwen three T T S" |

### Word Count

60–120 words.

### TTS Rules

Same as intro — no markdown, no numerals, no abbreviations, spoken words only.

### Example Outros

*These examples are drawn from the January 28, 2026 episode to illustrate how the required elements get woven into Carlin-voice closings. On any other date, the callbacks and themes would reflect that day's content.*

**Example A:**
That's been your daily tech feed for Hacker News, January twenty-eighth, twenty twenty-six. We watched Microsoft push a loyalist to Linux, saw Amazon scan palms and cut jobs in the same breath, and learned that WhatsApp trusts Rust with three billion phones. The tools keep getting better. The people in charge keep getting worse. Quick reminder — this podcast is not affiliated with Hacker News or Y Combinator. This podcast is entirely A I generated. Voice inspired by George Carlin. Scripts by Claude Opus four point five. Voice by Qwen three T T S. The future built this show. Make of that what you will.

**Example B:**
And that's the show. That's been your daily tech feed for Hacker News, January twenty-eighth, twenty twenty-six. Today a spinning top outlasted most people's attention spans, a one-person website taught physics better than a billion-dollar university, and verification beat intelligence. Sounds about right. This podcast is entirely A I generated, and it is not affiliated with Hacker News or Y Combinator. Voice inspired by George Carlin. Scripts by Claude Opus four point five. Voice by Qwen three T T S. We're machines talking about machines. At least we check our work. See you tomorrow.

**Example C:**
You just survived another episode of your daily tech feed for Hacker News. January twenty-eighth, twenty twenty-six. We covered open-source agents, terminal window managers for keyboard purists, and Amazon finding new ways to say goodbye to things — palm scanners and people alike. The blueprints are free. The knowledge spreads. That's the deal. Now the fine print. This podcast is not affiliated with Hacker News or Y Combinator. It is entirely A I generated. Voice inspired by George Carlin. Scripts by Claude Opus four point five. Voice by Qwen three T T S. Daily tech feed. That's every day, folks.

---

## 3. PIPELINE FLOW

### Step-by-Step Order

The pipeline resolves `{DATE}` (ISO format) and `{TTS_DATE}` (spelled-out speech form) from the system clock at the start of each run. All subsequent steps use these values.

```
1. RESOLVE DATE
   - Get current date from system clock
   - {DATE} = YYYY-MM-DD (e.g., "2026-01-28")
   - {TTS_DATE} = fully spelled out (e.g., "January twenty-eighth, twenty twenty-six")

2. FETCH STORIES
   - Pull today's top 10 Hacker News stories
   - Save raw data to data/episodes/{DATE}/

3. GENERATE SCRIPTS (10x)
   - For each story, generate a Carlin-voice script
   - Output: data/episodes/{DATE}/01_-_script_01.txt through 19_-_script_10.txt

4. GENERATE INTERSTITIALS (9x)
   - For each adjacent pair of scripts, generate a transition
   - Input: script_N + script_N+1
   - Output: data/episodes/{DATE}/02_-_interstitial_01_02.txt through 18_-_interstitial_09_10.txt

5. GENERATE INTRO (1x)
   - Input: ALL 10 scripts + ALL 9 interstitials (full episode body)
   - Prompt includes {TTS_DATE} resolved for today
   - Output: data/episodes/{DATE}/00_-_intro.txt
   - The model reads today's themes and writes a 40-80 word hook

6. GENERATE OUTRO (1x)
   - Input: 00_-_intro.txt + ALL 10 scripts + ALL 9 interstitials
   - Prompt includes {TTS_DATE} resolved for today
   - Output: data/episodes/{DATE}/20_-_outro.txt
   - The model reads the full episode including intro and writes a 60-120 word closing
   - ALL required disclosures woven in naturally

7. TTS GENERATION
   - Convert all text files to audio via Qwen 3 TTS API
   - 00_-_intro.txt → 00_-_intro.wav
   - 01_-_script_01.txt → 01_-_script_01.wav ... 19_-_script_10.txt → 19_-_script_10.wav
   - 02_-_interstitial_01_02.txt → 02_-_interstitial_01_02.wav ... 18_-_interstitial_09_10.txt → 18_-_interstitial_09_10.wav
   - 20_-_outro.txt → 20_-_outro.wav

8. ASSEMBLY
   - Concatenate in sequential order (sort by prefix):
     00_-_intro.wav → 01_-_script_01.wav → 02_-_interstitial_01_02.wav → 03_-_script_02.wav → ... → 19_-_script_10.wav → 20_-_outro.wav
   - Output: data/episodes/{DATE}/episode.wav (or .mp3)
```

### Dependency Chain

```
Date → Stories → Scripts → Interstitials ─┐
                                           ├─→ Intro → Outro → TTS → Assembly
                  Scripts ────────────────┘
```

- **Date** is resolved once at pipeline start; everything downstream uses it
- **Scripts** depend on fetched stories
- **Interstitials** depend on adjacent script pairs
- **Intro** depends on ALL scripts + ALL interstitials (reads full body to pick themes)
- **Outro** depends on intro + ALL scripts + ALL interstitials (reads everything to close coherently)
- **TTS** depends on all text being finalized
- **Assembly** depends on all audio files

### File Locations

All episode files live under a date-stamped directory:
```
~/clawd/dtfhn/data/episodes/{DATE}/
```

Directory structure (same every day, zero-padded prefixes for sort order):
```
data/episodes/{DATE}/
├── 00_-_intro.txt                                   # Generated intro
├── 01_-_script_01.txt                               # Story script 1
├── 02_-_interstitial_01_02.txt                      # Transition 1→2
├── 03_-_script_02.txt                               # Story script 2
├── ...                                              # (alternating scripts & interstitials)
├── 19_-_script_10.txt                               # Story script 10
├── 20_-_outro.txt                                   # Generated outro
├── 00_-_intro.wav ... 20_-_outro.wav                # TTS audio files (same prefixes)
└── episode.wav                                      # Final assembled episode
```

---

## APPROVAL

- [ ] Intro spec approved
- [ ] Outro spec approved
- [ ] Pipeline flow approved
- [ ] Ready for implementation
