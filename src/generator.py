"""
Script generation for Carlin Podcast.
Generates Carlin-style scripts from articles with chaining and word count tracking.
Also generates dynamic intro/outro with full episode context.
"""

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from num2words import num2words

logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
CARLIN_MD_PATH = PROJECT_ROOT / "CARLIN.md"

# Config
CLI_TIMEOUT = 180  # 3 min per call
DEFAULT_WORD_TARGET = 4000
WORDS_PER_STORY = 400  # ~400 words per story for 10 stories


def load_carlin_voice() -> str:
    """Load the Carlin character bible from CARLIN.md."""
    if CARLIN_MD_PATH.exists():
        return CARLIN_MD_PATH.read_text()
    # Fallback if file doesn't exist
    return """George Carlin is pro-technology, pro-AI, pro-singularity, accelerationist.
Mock luddites, gatekeepers, closed systems. Support open source, hackers, builders.
Observational tone, bemused disappointment. Punch UP at institutions, never DOWN."""


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def call_claude(prompt: str) -> str:
    """Call Claude via CLI with stdin=DEVNULL to prevent hanging."""
    result = subprocess.run(
        ["claude", "-p", prompt],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr or result.stdout}")

    return result.stdout.strip()


def generate_script(
    article: dict,
    previous_script: Optional[str] = None,
    word_budget: Optional[int] = None,
) -> tuple[str, int]:
    """
    Generate a Carlin-style script for one article.

    Args:
        article: Dict with title, content, comments (list of dicts)
        previous_script: Previous script text for variety/non-repetition
        word_budget: Target word count for this script (None = default ~400)

    Returns:
        Tuple of (script_text, word_count)
    """
    # Load voice guidelines
    carlin_voice = load_carlin_voice()

    # Determine word target
    target_words = word_budget or WORDS_PER_STORY

    # Build length guidance
    if word_budget is not None:
        if word_budget < 300:
            length_guidance = f"Be BRIEF. Target around {target_words} words. Hit the highlights only."
        elif word_budget > 500:
            length_guidance = f"Expand on this one. Target around {target_words} words. Go deep."
        else:
            length_guidance = f"Target around {target_words} words."
    else:
        length_guidance = f"Target around {target_words} words."

    # Build content section
    content = article.get("content", "")
    if content:
        content_section = content[:4000]  # Truncate for token budget
    else:
        content_section = "[Title only - no article text available]"

    # Build comments section
    comments = article.get("comments", [])
    if comments:
        comments_lines = []
        for c in comments[:6]:
            if isinstance(c, dict):
                text = c.get("text", "")[:200]
            else:
                text = str(c)[:200]
            comments_lines.append(f"- {text}")
        comments_section = "\n".join(comments_lines)
    else:
        comments_section = "- [No comments available]"

    # Build variety section if we have a previous script
    variety_section = ""
    if previous_script:
        # Extract key phrases to avoid repeating
        variety_section = f"""
PREVIOUS SCRIPT (for variety - do NOT repeat phrases or structures):
{previous_script[-800:]}

Vary your opening, transitions, and punchlines from the above."""

    # Build the full prompt
    prompt = f"""## CHARACTER VOICE
{carlin_voice}

---

## TASK
Write a 5-paragraph segment about this article for a spoken podcast.

ARTICLE: {article.get('title', 'Untitled')}
URL: {article.get('source_url', '')}

{content_section}

COMMENTS FROM READERS:
{comments_section}
{variety_section}

## STRUCTURE
1. What happened (the news)
2. Key players involved
3. Why this matters (or why it's absurd)
4. Broader context
5. What the comments reveal about people

## LENGTH
{length_guidance}

## OUTPUT
Write ONLY the script text. No preamble, no commentary, no markdown.
Write in spoken voice - this will be read aloud.

Write the script now."""

    script = call_claude(prompt)
    word_count = count_words(script)

    return script, word_count


def generate_episode_scripts(
    articles: list[dict],
    total_word_target: int = DEFAULT_WORD_TARGET,
) -> list[tuple[str, int]]:
    """
    Generate scripts for all articles in an episode with word count management.

    Uses chained generation - each script sees the previous one for variety.
    Adjusts length guidance based on running word count vs target.

    Args:
        articles: List of article dicts
        total_word_target: Total word count target for episode (default 4000)

    Returns:
        List of (script_text, word_count) tuples
    """
    if not articles:
        return []

    # Calculate base word budget per story
    num_stories = len(articles)
    base_budget = total_word_target // num_stories

    scripts = []
    running_total = 0
    previous_script = None

    for i, article in enumerate(articles):
        stories_remaining = num_stories - i
        words_remaining = total_word_target - running_total

        # Calculate word budget for this story
        if stories_remaining > 0:
            ideal_budget = words_remaining // stories_remaining
        else:
            ideal_budget = base_budget

        # Clamp to reasonable bounds
        word_budget = max(250, min(600, ideal_budget))

        print(f"  Story {i + 1}/{num_stories}: {article.get('title', 'Untitled')[:50]}...")
        print(f"    Budget: {word_budget} words (running: {running_total}/{total_word_target})")

        script, word_count = generate_script(
            article=article,
            previous_script=previous_script,
            word_budget=word_budget,
        )

        scripts.append((script, word_count))
        running_total += word_count
        previous_script = script

        print(f"    Generated: {word_count} words (total now: {running_total})")

    print(f"\nEpisode total: {running_total} words (target: {total_word_target})")
    return scripts


def generate_interstitial(script1: str, script2: str, next_title: str) -> str:
    """
    Generate a transition between two scripts.

    Args:
        script1: The script we're leaving
        script2: The script we're entering
        next_title: Title of the next article

    Returns:
        1-2 sentence transition text
    """
    carlin_voice = load_carlin_voice()

    prompt = f"""## CHARACTER VOICE
{carlin_voice}

---

## TASK
Write a 1-2 sentence transition between podcast segments.

PREVIOUS SEGMENT (just finished):
{script1[-500:]}

NEXT SEGMENT TOPIC: {next_title}

Write a quick Carlin-style pivot. 15-30 words max.
Just the transition, nothing else. No quotes or formatting."""

    return call_claude(prompt)


# ---------------------------------------------------------------------------
# Dynamic Intro / Outro
# ---------------------------------------------------------------------------

INTRO_PROMPT = """You are writing the INTRO for today's episode in the voice of George Carlin.

Today's date (TTS-formatted): {tts_date}

Below is the full episode body. Read it to understand today's mood and themes — but you will NOT reference any specific stories, companies, technologies, or people from the episode.

STRUCTURE (follow this order exactly):
1. "You're listening to D T F H N for {tts_date}." — STATIC. This exact line every episode with the date filled in.
2. "I'm your [descriptor] host, A I George Carlin." — DYNAMIC. The descriptor is wide open. NOT limited to synonyms for "dead." Could be absurd, vulgar, pop culture references, Carlin's favorite words, profane, surreal. Examples: "posthumously rendered," "cyberfucked," "seven-words-you-can't-say-on-television," "digitally exhumed," "silicon-based," anything with personality. Different every episode.
3. "We are your daily tech feed for Hacker News, a website [short riff on what HN is]." — DYNAMIC. One clause riff on HN. Funny, irreverent. Different every episode.
4. One sentence mood/tone setter. Informed by today's stories but NEVER explicitly name, tease, or summarize any article. No companies, no technologies, no people from the episode. Setting a vibe, not a preview.
5. A short launch line. "Let's get into it" or something funnier. Different every episode.

RULES:
- 40 to 70 words total. No exceptions.
- The structure above is the ENTIRE intro. Nothing else.
- NEVER mention specific stories, companies, technologies, or people from today's episode
- TTS output ONLY. No markdown, no asterisks, no headers, no formatting, no stage directions.
- Spell out abbreviations as spoken: "A I" not "AI", "D T F H N" not "DTFHN"
- The episode content below is context for YOUR mood, not material to reference.

EPISODE BODY (context for mood only — do NOT reference directly):
{episode_body}"""

OUTRO_PROMPT = """You are writing the OUTRO for today's episode in the voice of George Carlin.

Today's date (TTS-formatted): {tts_date}

Below is the full episode. Read it for context.

STRUCTURE (follow this order):
1. One short parting thought or observation. DYNAMIC. Can implicitly reference the episode's mood but NEVER name specific stories, companies, or technologies.
2. "This has been your daily tech feed for Hacker News for {tts_date}." — STATIC. "This has been" NOT "That's been". This exact line every episode.
3. Credits — STATIC content, DYNAMIC delivery. Rattle these off with Carlin attitude:
   - "This podcast is entirely A I generated."
   - "Voice inspired by George Carlin."
   - "Scripts by Claude Opus four point five."
   - "Voice by Qwen three T T S."
   - "Not affiliated with Hacker News or Y Combinator."
4. "Now go [dynamic uplifting imperative]. We'll see you back here tomorrow." — The "Now go..." part is DYNAMIC — varied, always optimistic and uplifting. Could be "Now go build something useful and beautiful" or "Now go make something the world doesn't deserve yet" or "Now go create something that scares you a little." Always forward-looking, always encouraging. The "We'll see you back here tomorrow." is STATIC, verbatim, every episode.

RULES:
- 60 to 100 words total. No exceptions.
- NEVER mention specific stories, companies, technologies, or people from today's episode
- TTS output ONLY. No markdown, no asterisks, no headers, no formatting, no stage directions.
- Spell out abbreviations as spoken: "A I" not "AI"
- The episode content is context for your mood, not material to reference.
- MUST end with "We'll see you back here tomorrow." — this is the last thing the audience hears, every episode, no exceptions.

EPISODE (context only):
{episode_body}"""


def format_date_for_tts(date_str: str) -> str:
    """
    Convert YYYY-MM-DD to TTS-friendly fully spoken format.

    Example: '2026-01-28' -> 'January twenty-eighth, two thousand twenty-six'
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    month = dt.strftime("%B")
    day = num2words(dt.day, to="ordinal")
    year = num2words(dt.year)
    return f"{month} {day}, {year}"


def _strip_markdown(text: str) -> str:
    """Strip markdown artifacts the LLM might sneak into TTS output."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip markdown headers, horizontal rules, code fences
        if stripped.startswith("#") or stripped.startswith("---") or stripped.startswith("```"):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)
    # Remove asterisks (bold/italic markers)
    text = re.sub(r"\*+", "", text)
    return text.strip()


def _strip_preamble(text: str) -> str:
    """Strip LLM preamble lines like 'Here's the intro:' before actual content."""
    # Common preamble patterns the LLM might prepend
    preamble_re = re.compile(
        r"^(here'?s?\s+(the|your|an?)\s+\w+[:\.]?\s*\n?)",
        re.IGNORECASE,
    )
    text = preamble_re.sub("", text).strip()
    return text


def _check_word_count(text: str, label: str, max_words: int) -> None:
    """Log a warning if word count exceeds limit by more than 20%."""
    wc = count_words(text)
    threshold = int(max_words * 1.2)
    if wc > threshold:
        logger.warning(
            "%s word count %d exceeds %d-word limit (threshold %d)",
            label, wc, max_words, threshold,
        )


# Static safety-net fragments
_INTRO_STATIC_PREFIX = "You're listening to D T F H N"
_OUTRO_STATIC_SUFFIX = "We'll see you back here tomorrow."


def generate_intro(
    scripts: list[str],
    interstitials: list[str],
    tts_date: str,
) -> str:
    """
    Generate a dynamic Carlin cold-open intro for the episode.

    Args:
        scripts: List of 10 script texts
        interstitials: List of 9 interstitial texts
        tts_date: Date spelled out for speech (e.g. "January twenty-eighth, …")

    Returns:
        Intro text (40-70 words, TTS-ready)
    """
    # Interleave scripts and interstitials to show episode flow
    body_parts = []
    for i, script in enumerate(scripts):
        body_parts.append(f"--- SCRIPT {i + 1} ---\n{script}")
        if i < len(interstitials):
            body_parts.append(f"--- INTERSTITIAL {i + 1}→{i + 2} ---\n{interstitials[i]}")
    episode_body = "\n\n".join(body_parts)

    prompt = INTRO_PROMPT.format(tts_date=tts_date, episode_body=episode_body)
    text = call_claude(prompt)

    # Harden output
    text = _strip_preamble(text)
    text = _strip_markdown(text)
    if not text.startswith(_INTRO_STATIC_PREFIX):
        logger.warning("Intro missing static prefix — prepending")
        text = f"You're listening to D T F H N for {tts_date}. {text}"
    _check_word_count(text, "Intro", 70)

    return text


def generate_outro(
    scripts: list[str],
    interstitials: list[str],
    intro_text: str,
    tts_date: str,
) -> str:
    """
    Generate a dynamic Carlin closing outro for the episode.

    Args:
        scripts: List of 10 script texts
        interstitials: List of 9 interstitial texts
        intro_text: The generated intro (for coherent bookending)
        tts_date: Date spelled out for speech

    Returns:
        Outro text (60-100 words, TTS-ready)
    """
    # Build full episode body: intro + interleaved scripts/interstitials
    body_parts = [f"--- INTRO ---\n{intro_text}"]
    for i, script in enumerate(scripts):
        body_parts.append(f"--- SCRIPT {i + 1} ---\n{script}")
        if i < len(interstitials):
            body_parts.append(f"--- INTERSTITIAL {i + 1}→{i + 2} ---\n{interstitials[i]}")
    episode_body = "\n\n".join(body_parts)

    prompt = OUTRO_PROMPT.format(tts_date=tts_date, episode_body=episode_body)
    text = call_claude(prompt)

    # Harden output
    text = _strip_preamble(text)
    text = _strip_markdown(text)
    if not text.rstrip().endswith(_OUTRO_STATIC_SUFFIX):
        logger.warning("Outro missing static suffix — appending")
        # Strip trailing punctuation before appending
        text = text.rstrip()
        if not text.endswith("."):
            text += "."
        text += f" {_OUTRO_STATIC_SUFFIX}"
    _check_word_count(text, "Outro", 100)

    return text


if __name__ == "__main__":
    # Quick test
    print("Testing generator...")

    test_article = {
        "title": "OpenAI Releases New Model That's Actually Just GPT-4 Again",
        "source_url": "https://example.com/test",
        "content": """OpenAI announced today what they're calling a 'revolutionary' 
        new AI model. Upon closer inspection, researchers found it performs 
        identically to GPT-4 but costs twice as much. The company defended 
        the pricing, stating that 'innovation has a price.'""",
        "comments": [
            {"author": "skeptic123", "text": "This is literally the same model lol"},
            {"author": "ai_believer", "text": "Trust the process, they know what they're doing"},
        ],
    }

    script, word_count = generate_script(test_article)
    print(f"\nGenerated script ({word_count} words):\n")
    print(script)
