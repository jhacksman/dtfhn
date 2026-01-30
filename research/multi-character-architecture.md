# Multi-Character Architecture: Audit & Proposal

> Research date: 2025-07-14
> Status: Proposal (no code changes)

---

## Part 1: Audit — Where Carlin Lives Today

### Summary

Carlin persona is implemented through **two mechanisms**: a character bible file (`CARLIN.md`) loaded at runtime, and **hardcoded Carlin-specific content scattered throughout prompts and code**. CARLIN.md is the source of truth for *values and tone*, but it is NOT the single source of truth for the full character. Significant character-specific content is baked into `generator.py` prompt templates and throughout the codebase in comments, docstrings, and constants.

### File-by-File Map

#### `CARLIN.md` — Character Bible (values + tone)
- Core philosophy (pro-tech, pro-AI, accelerationist)
- What he mocks / supports
- Tone calibration with wrong/right examples
- Open source stance
- Voice reminders (observational, punch up, profanity as punctuation)
- **NOT included**: speaking rate, intro/outro structure, TTS voice name, credit lines

#### `src/generator.py` — THE MOTHERLODE of Hardcoded Carlin
| Location | Carlin-Specific Content |
|----------|------------------------|
| Module docstring | "Script generation for Carlin Podcast" |
| `CARLIN_MD_PATH` | Hardcoded path to `CARLIN.md` |
| `load_carlin_voice()` | Loads `CARLIN.md`, has inline fallback text mentioning Carlin by name |
| `generate_script()` prompt | `## CHARACTER VOICE\n{carlin_voice}` — loads from CARLIN.md ✓ |
| `generate_script()` prompt | "OPEN SOURCE LITMUS TEST" section references "the Carlin character" |
| `generate_interstitial()` prompt | "Write a quick Carlin-style pivot" — **hardcoded string** |
| `INTRO_PROMPT` | "in the voice of George Carlin" — **hardcoded** |
| `INTRO_PROMPT` | "I'm your [descriptor] host, A I George Carlin" — **hardcoded intro structure** |
| `INTRO_PROMPT` | Static line: "You're listening to D T F H N for {tts_date}" |
| `OUTRO_PROMPT` | "in the voice of George Carlin" — **hardcoded** |
| `OUTRO_PROMPT` | Credits: "Voice inspired by George Carlin" — **hardcoded** |
| `OUTRO_PROMPT` | Credits: "Scripts by Claude Opus four point five" — **hardcoded** |
| `OUTRO_PROMPT` | Credits: "Voice by Qwen three T T S" — **hardcoded** |
| `_INTRO_STATIC_PREFIX` | "You're listening to D T F H N" — **hardcoded safety net** |
| `_OUTRO_STATIC_SUFFIX` | "We'll see you back here tomorrow." — **hardcoded** |
| `generate_intro()` | Enforces intro starts with static prefix |
| `generate_outro()` | Enforces outro ends with static suffix |

#### `src/pipeline.py` — Orchestrator
| Location | Carlin-Specific Content |
|----------|------------------------|
| Module docstring | "Episode pipeline orchestrator for Carlin Podcast" |
| `WORDS_PER_MINUTE = 165` | Calibrated to Carlin's fast speaking rate |
| `run_episode_pipeline()` | Prints "CARLIN PODCAST - EPISODE {date}" |
| Import of `generate_*` functions | All Carlin-flavored via generator.py |

#### `src/tts.py` — TTS Interface
| Location | Carlin-Specific Content |
|----------|------------------------|
| Module docstring | "Carlin podcast" |
| `TTS_VOICE = "george_carlin"` | **Hardcoded default voice** |
| All `text_to_speech*` functions | Default `voice=TTS_VOICE` parameter |

#### `src/transcript.py` — WebVTT Generation
| Location | Carlin-Specific Content |
|----------|------------------------|
| Module docstring | "WebVTT transcript generation for Carlin Podcast" |
| `generate_vtt()` | `speaker: str = "George Carlin"` — **hardcoded default** |
| VTT output | `<v George Carlin>` speaker tags |

#### `src/metadata.py` — ID3 Tags
| Location | Carlin-Specific Content |
|----------|------------------------|
| `embed_id3_metadata()` | `TPE1 = "Jack Hacksman"` — artist (not character-specific per se) |
| Title format | `"Daily Tech Feed - {date}"` — show name, not character |

#### `src/chapters.py` — Chapter Markers
- No direct Carlin references. Character-agnostic.

#### `src/storage.py` — LanceDB Storage
| Location | Carlin-Specific Content |
|----------|------------------------|
| Module docstring | "Storage layer for Carlin Podcast" |
| Schema comment | `"Generated Carlin script"` |
| `voice` field | Default `"george_carlin"` in `store_segment()` |
| Segments batch | Default `"george_carlin"` fallback |

#### `scripts/generate_episode_audio.py` — Audio Generation
| Location | Carlin-Specific Content |
|----------|------------------------|
| `build_segment_metadata()` | `"tts_model": "f5-tts"`, `"voice": "george_carlin"` — **hardcoded** |

#### `scripts/generate_missing_wavs.py` — WAV Recovery
| Location | Carlin-Specific Content |
|----------|------------------------|
| TTS request body | `"voice": "george_carlin"` — **hardcoded** |

#### `scripts/run_episode.sh` — Pipeline Runner
- No character references. Character-agnostic shell wrapper.

#### `src/__init__.py` — Package Init
| Location | Carlin-Specific Content |
|----------|------------------------|
| Docstring | "Carlin Podcast" |
| Exports `TTS_VOICE` | From tts.py |

### Audit Conclusion

**CARLIN.md is ~30% of the character definition.** It covers values, tone, and editorial stance. The remaining ~70% is scattered:
- **Intro/outro structure** (generator.py prompts — lines like "I'm your host AI George Carlin")
- **Credits** (hardcoded in OUTRO_PROMPT)
- **TTS voice name** (tts.py constant, propagated everywhere)
- **Speaker name** (transcript.py default parameter)
- **Speaking rate** (pipeline.py WPM constant)
- **Prompt phrasing** ("Carlin-style pivot", "in the voice of George Carlin")

A new character can't be added by just writing a new `.md` file. You'd need to touch **at minimum 6 files** with hardcoded Carlin references.

---

## Part 2: Multi-Character Architecture Design

### Design Principles

1. **One file per character** — all character-specific config in one place
2. **Shared values are NOT character-specific** — the podcast's editorial stance (pro-open-source, pro-tech, anti-gatekeepers) belongs to the SHOW, not the character
3. **Characters are voice/personality skins** over the same editorial core
4. **Pipeline selects character at invocation time** — CLI flag, not runtime detection
5. **TTS voice is a character property** — each character maps to a TTS voice name on the server

### What's Character-Specific vs Shared

#### Character-Specific (per-character file)
- **Display name**: "George Carlin", "Stephen Fry", "Philip J. Fry"
- **TTS voice name**: `george_carlin`, `stephen_fry`, `philip_j_fry`
- **Speaking style/personality**: tone, vocabulary, catchphrases, comedy style
- **Speaking rate (WPM)**: Carlin ~165, Fry (Stephen) ~140, Fry (Philip) ~155
- **Host intro line template**: "I'm your [descriptor] host, A I George Carlin" vs "I'm [descriptor], Stephen Fry" vs different structures entirely
- **Host descriptor style**: Carlin gets "dead"/"posthumous" variants; Stephen Fry gets erudite/witty variants; Philip J. Fry gets dumb/confused variants
- **Credit delivery style**: how they rattle off credits
- **Interstitial style**: "Carlin-style pivot" vs "Fry-style aside" vs "confused Fry non-sequitur"
- **Tone calibration examples**: right/wrong take examples per character
- **TTS model name**: for segment metadata (f5-tts, etc.)

#### Shared Across ALL Characters (show-level)
- **Editorial values**: pro-open-source, pro-tech, anti-gatekeepers, punch up not down
- **Open source litmus test**: every character must call out proprietary lock-in
- **Show name**: "Daily Tech Feed" / "D T F H N"
- **Static intro line**: "You're listening to D T F H N for {date}."
- **Static outro lines**: "This has been your daily tech feed..." / "We'll see you back here tomorrow."
- **Credit facts** (not delivery): AI-generated, not affiliated with HN/YC
- **Segment structure**: intro → 10 scripts → 9 interstitials → outro
- **Word targets**: ~4000 words, ~400/story
- **Segment naming**: zero-padded convention
- **Pipeline mechanics**: fetch → store → generate → TTS

### Proposed File Structure

```
dtfhn/
├── characters/
│   ├── _shared.md          # Show-level values, editorial stance, static lines
│   ├── george_carlin.md    # Full Carlin character definition
│   ├── stephen_fry.md      # Stephen Fry character definition
│   └── philip_j_fry.md    # Philip J. Fry character definition
├── CARLIN.md               # DEPRECATED — kept as redirect to characters/george_carlin.md
├── src/
│   ├── character.py        # NEW — character loading and config
│   ├── generator.py        # Refactored — parameterized by character
│   ├── pipeline.py         # Refactored — accepts character selection
│   ├── tts.py              # Refactored — voice from character config
│   ├── transcript.py       # Refactored — speaker from character config
│   └── ...
└── scripts/
    ├── run_episode.sh      # Accepts --character flag
    └── generate_episode_audio.py  # Reads character from manifest
```

### Character File Format

Each character `.md` file would have a structured format that can be parsed AND used as raw prompt context:

```markdown
# Character: George Carlin

## Config
- tts_voice: george_carlin
- tts_model: f5-tts
- speaking_rate_wpm: 165
- display_name: George Carlin
- speaker_tag: George Carlin

## Host Intro Template
"I'm your [descriptor] host, A I George Carlin."
Descriptor style: Wide open — absurd, vulgar, pop culture, profane, surreal. NOT limited to "dead" synonyms. Examples: "posthumously rendered," "cyberfucked," "seven-words-you-can't-say-on-television," "digitally exhumed," "silicon-based."

## Personality & Voice
[The bulk of what's currently in CARLIN.md — philosophy, tone, what they mock/support, voice reminders]

## Tone Calibration
[Right/wrong take examples specific to this character]

## Interstitial Style
Quick, punchy transitions. Carlin-style pivots. 15-30 words.

## Credit Delivery
Rattle them off with attitude. Fast, irreverent.
```

### `_shared.md` — Show-Level Values

```markdown
# Daily Tech Feed — Shared Values

## Editorial Stance (ALL characters MUST follow)
- Pro-technology, pro-AI, pro-open-source
- Mock luddites, gatekeepers, corporate doublespeak
- Punch UP at institutions, NEVER down at workers/builders
- Open source litmus test is NON-NEGOTIABLE

## Static Lines (verbatim, every episode)
- Intro line 1: "You're listening to D T F H N for {tts_date}."
- Outro line 2: "This has been your daily tech feed for Hacker News for {tts_date}."
- Outro final: "We'll see you back here tomorrow."

## Credit Facts (delivery varies by character)
- "This podcast is entirely A I generated."
- "Scripts by Claude Opus four point five."
- "Voice by [character's TTS model name]."
- "Not affiliated with Hacker News or Y Combinator."
- "Voice inspired by [character display name]."

## Open Source Litmus Test
[The full litmus test block currently in generate_script()]
```

### `src/character.py` — NEW Module

```python
"""Character configuration for DTFHN podcast."""

from dataclasses import dataclass
from pathlib import Path

CHARACTERS_DIR = Path(__file__).parent.parent / "characters"
DEFAULT_CHARACTER = "george_carlin"

@dataclass
class Character:
    """All character-specific configuration."""
    slug: str               # e.g., "george_carlin"
    display_name: str       # e.g., "George Carlin"
    tts_voice: str          # e.g., "george_carlin" (TTS server voice name)
    tts_model: str          # e.g., "f5-tts"
    speaking_rate_wpm: int  # e.g., 165
    speaker_tag: str        # For VTT: "George Carlin"
    personality_prompt: str # Full personality text for LLM prompts
    shared_values: str      # Show-level values (same for all characters)
    intro_template: str     # How intro is structured for this character
    credit_line: str        # "Voice inspired by {display_name}"

def load_character(slug: str = DEFAULT_CHARACTER) -> Character:
    """Load character config from characters/ directory."""
    char_path = CHARACTERS_DIR / f"{slug}.md"
    shared_path = CHARACTERS_DIR / "_shared.md"
    # Parse structured sections from markdown...
    ...

def list_characters() -> list[str]:
    """List available character slugs."""
    return [p.stem for p in CHARACTERS_DIR.glob("*.md") if not p.stem.startswith("_")]
```

### Code Changes Required

#### `src/generator.py` — Major Refactor

1. **Remove** `CARLIN_MD_PATH`, `load_carlin_voice()`
2. **Add** `character: Character` parameter to all generate functions
3. **Parameterize** `INTRO_PROMPT` and `OUTRO_PROMPT`:
   - Replace "in the voice of George Carlin" → `"in the voice of {character.display_name}"`
   - Replace hardcoded intro structure → `character.intro_template`
   - Replace hardcoded credits → build from `character` + `_shared.md`
4. **Parameterize** `generate_interstitial()`:
   - Replace "Carlin-style pivot" → `"{character.display_name}-style transition"`
   - Or better: each character file includes interstitial style guidance
5. **`generate_script()`**: Replace `{carlin_voice}` → `{character.personality_prompt}` + `{character.shared_values}`
6. **Open source litmus test**: Move to `_shared.md`, inject from shared values (it's a show value, not a character trait)

#### `src/pipeline.py` — Moderate Refactor

1. **Add** `character: str = "george_carlin"` parameter to `run_episode_pipeline()`
2. **Load character** at pipeline start, pass to all generator calls
3. **Replace** `WORDS_PER_MINUTE = 165` → `character.speaking_rate_wpm`
4. **Store character slug** in manifest JSON (so audio generation knows which voice to use)
5. **Print** character name in pipeline output instead of "CARLIN PODCAST"

#### `src/tts.py` — Minor Refactor

1. **Keep** `TTS_VOICE` as fallback default
2. **All functions already accept `voice` parameter** — just need callers to pass it
3. No structural changes needed — already parameterized correctly

#### `src/transcript.py` — Minor Refactor

1. **Change** `speaker` default from `"George Carlin"` to accept from caller
2. Pipeline passes `character.speaker_tag`

#### `src/metadata.py` — Minor Change

1. **TPE1 (Artist)** stays "Jack Hacksman" (show creator, not character)
2. **Possibly add** character name to episode description/comment

#### `src/storage.py` — No Structural Changes

1. **`voice` field** already exists in segments schema — just pass correct value
2. Consider adding `character` field to episodes table for queryability

#### `scripts/generate_episode_audio.py` — Moderate Refactor

1. **Read character from manifest** (set by pipeline)
2. **Pass voice to TTS** from manifest's character config
3. **Replace** hardcoded `"george_carlin"` in `build_segment_metadata()`

#### `scripts/generate_missing_wavs.py` — Minor Refactor

1. **Read character/voice from manifest** instead of hardcoding `"george_carlin"`

#### `scripts/run_episode.sh` — Minor Change

1. **Accept** `--character` flag, pass to python pipeline
2. **Default** to `george_carlin` if not specified

### Pipeline Flow with Character Selection

```
# CLI invocation
nohup bash scripts/run_episode.sh --character stephen_fry > /tmp/dtfhn.log 2>&1 &

# Or direct Python
python3 -c "
from src.pipeline import run_episode_pipeline
run_episode_pipeline(character='stephen_fry')
"
```

**Pipeline internals:**
1. `run_episode_pipeline(character="stephen_fry")` loads `Character` object
2. All `generate_*` calls receive the Character
3. Manifest stores `"character": "stephen_fry"`
4. `generate_episode_audio.py` reads manifest, gets `character.tts_voice = "stephen_fry"`
5. TTS requests use `voice="stephen_fry"` parameter
6. Segments stored with `voice="stephen_fry"`
7. VTT uses `speaker="Stephen Fry"`

### TTS Voice Provisioning

The TTS server at `192.168.0.134:7849` currently only has `george_carlin`. Adding new characters requires:

1. **Train/prepare voice models** on quato for each new character
2. **Register voice names** in the TTS server config
3. **Verify** via `GET /voices` that new voices appear
4. **Test** voice quality before enabling in production

This is a prerequisite external dependency — the multi-character code can be built before voices are ready, with the TTS server returning errors for unknown voices (which the robust pipeline handles gracefully).

### Cron/Automation

Current cron fires `run_episode.sh` daily. Options for multi-character:

**Option A: Fixed rotation schedule**
```
# Mon/Wed/Fri: Carlin, Tue/Thu: Stephen Fry, Sat: Philip J. Fry
0 5 * * 1,3,5 bash scripts/run_episode.sh --character george_carlin
0 5 * * 2,4   bash scripts/run_episode.sh --character stephen_fry
0 5 * * 6     bash scripts/run_episode.sh --character philip_j_fry
```

**Option B: Random selection**
```bash
CHARS=("george_carlin" "stephen_fry" "philip_j_fry")
CHAR=${CHARS[$((RANDOM % ${#CHARS[@]}))]}
bash scripts/run_episode.sh --character "$CHAR"
```

**Option C: Config file** (recommended)
```json
// config/schedule.json
{
  "default_character": "george_carlin",
  "rotation": ["george_carlin", "stephen_fry", "philip_j_fry"],
  "mode": "round_robin"  // or "random", "fixed_schedule"
}
```

### Migration Plan

1. **Phase 0**: Create `characters/` directory, write `george_carlin.md` (migrate from CARLIN.md), `_shared.md`
2. **Phase 1**: Create `src/character.py`, write `load_character()` 
3. **Phase 2**: Refactor `generator.py` to accept Character — keep backward compatible (default to Carlin)
4. **Phase 3**: Refactor `pipeline.py` to pass character through, store in manifest
5. **Phase 4**: Refactor `tts.py` callers, `transcript.py`, audio scripts to read from manifest
6. **Phase 5**: Write `stephen_fry.md` and `philip_j_fry.md` character files
7. **Phase 6**: Train/provision TTS voices on quato
8. **Phase 7**: Update cron/automation

Each phase can be tested independently. Phase 1-4 can ship with only Carlin and zero behavior change.

### Risks & Open Questions

1. **TTS voice quality**: New voices need training. Stephen Fry's measured cadence is very different from Carlin's rapid-fire delivery. Philip J. Fry is an animated character — can F5-TTS handle that?
2. **Prompt length**: Adding `_shared.md` + character personality to every prompt increases token usage. May need to trim or summarize.
3. **Character consistency across episodes**: Same character should feel consistent day-to-day. The character file is the constraint, but LLMs can drift.
4. **Audience expectations**: Listeners may prefer one character. Sudden rotation could be jarring. Consider announcing character changes in the intro.
5. **Storage schema**: Should episodes table track which character was used? (Recommend: yes, add a `character` string column.)
6. **Open source litmus test**: Currently references "the Carlin character" — needs to be character-agnostic in `_shared.md`.
7. **Intro "A I" prefix**: "A I George Carlin" works because he's dead and the AI angle is the joke. "A I Stephen Fry" is different — Fry is alive. Each character needs their own framing.
