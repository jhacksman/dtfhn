# Plan: Dr. Forbin Character Implementation

## Overview
Replace George Carlin as default character with Dr. Charles Forbin from "Colossus: The Forbin Project" (1970). Implement non-stochastic scaffolding to prevent the formulaic repetition that plagued Carlin.

## Phase 1: Character File (FORBIN.md)
- Create FORBIN.md following GC.md structure (voice/personality only, values in ETHOS.md)
- Key traits: systems thinker, built Colossus, dry/precise/sardonic, genuine wonder at engineering, dark humor about unintended consequences
- References building Colossus as personal experience
- NOT doom-and-gloom — respects tech, knows the cost

## Phase 2: Non-Stochastic Scaffolding (generator.py)
This is the core architectural change. Add to generator.py:

### 2a. SCRIPT_STRUCTURES (8 templates)
Randomly assigned per story. Each defines a different structural approach:
1. "Cold open with the wildest detail" — lead with the most surprising fact
2. "Philosophical question" — open with a question this story raises
3. "Personal anecdote from building Colossus" — connect to Forbin's experience
4. "Start from the comments" — lead with what HN said, then reveal the story
5. "First-principles breakdown" — deconstruct the technology methodically
6. "Historical parallel" — start with a similar moment in computing history
7. "Devil's advocate" — argue the opposite of what you believe, then reveal why
8. "The quiet observation" — start with a small, precise detail that reveals everything

### 2b. RHETORICAL_DEVICES pool
Track usage within episode, avoid repeats:
- Analogy (from another field)
- Historical parallel (computing history)
- Thought experiment ("imagine if...")
- Devil's advocate
- First-principles breakdown
- Reductio ad absurdum
- Personal experience callback (Colossus)
- The uncomfortable question

### 2c. TONE_REGISTER options
Assigned per story based on content keywords/signals:
- DRY_ANALYSIS — clinical, precise
- GENUINE_WONDER — real admiration for elegant engineering
- DARK_HUMOR — unintended consequences, irony
- SARDONIC_OBSERVATION — bemused, cutting
- QUIET_CONCERN — serious, measured
- TECHNICAL_RESPECT — deep appreciation for the craft

### 2d. Anti-repetition guard
- Track used openers, phrases, rhetorical devices across the episode
- Pass forbidden list to each subsequent prompt
- Explicit "DO NOT USE" list in prompt

### 2e. Character loading
- CHARACTER env var, defaults to "forbin"
- `load_character_voice(character)` replaces `load_carlin_voice()`
- Loads FORBIN.md, GC.md, or CARLIN.md based on character name
- Update INTRO_PROMPT and OUTRO_PROMPT to be character-aware

## Phase 3: TTS Configuration (tts.py)
- Make TTS_VOICE configurable: look up voice by character name
- CHARACTER_VOICES dict mapping character → TTS voice
- Default: forbin → "forbin", carlin/gc → "george_carlin"

## Phase 4: Shell Script (run_episode.sh)
- Add CHARACTER env var support, default "forbin"
- Pass through to Python pipeline

## Phase 5: Pipeline Integration (pipeline.py)
- Pass CHARACTER through to generator calls
- Update banner/print statements

## Phase 6: Test Episode
- Run full text pipeline with current top 10 HN stories
- Save to episodes/ with today's date
- Review scripts for variety and character voice
- Do NOT run TTS

## Phase 7: Git & Documentation
- Commit after each phase
- Update RULES.md with lessons learned
- Push to origin

## Key Design Decisions
- Backward compatible: CHARACTER=carlin still works
- CARLIN.md and GC.md preserved, just not default
- Scaffolding lives in generator.py (not separate module) — it's tightly coupled to prompt construction
- Random selection uses Python's random module with no seed (different every run)
