"""
Script generation for DTFHN podcast.
Generates character-voiced scripts from articles with chaining, word count
tracking, and non-stochastic scaffolding to prevent formulaic repetition.
Also generates dynamic intro/outro with full episode context.

Supports multiple characters via CHARACTER env var (default: "forbin").
"""

import logging
import os
import random
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from num2words import num2words

logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent

# Config
CLI_TIMEOUT = 180  # 3 min per call
DEFAULT_WORD_TARGET = 4000
WORDS_PER_STORY = 400  # ~400 words per story for 10 stories

# ---------------------------------------------------------------------------
# Character system
# ---------------------------------------------------------------------------

# Map character names to their voice files and TTS voices
CHARACTER_CONFIG = {
    "forbin": {
        "file": "FORBIN.md",
        "tts_voice": "forbin",
        "display_name": "Dr. Forbin",
        "intro_host_line": "I'm your [descriptor] host, A I Dr. Forbin.",
        "intro_show_line": "We are your daily tech feed for Hacker News, a website [short riff on what HN is].",
        "outro_credit_voice": "Hosted by A I Forbin.",
    },
    "carlin": {
        "file": "CARLIN.md",
        "tts_voice": "george_carlin",
        "display_name": "A I George Carlin",
        "intro_host_line": "I'm your [descriptor] host, A I George Carlin.",
        "intro_show_line": "We are your daily tech feed for Hacker News, a website [short riff on what HN is].",
        "outro_credit_voice": "Voice inspired by George Carlin.",
    },
    "gc": {
        "file": "GC.md",
        "tts_voice": "george_carlin",
        "display_name": "A I George Carlin",
        "intro_host_line": "I'm your [descriptor] host, A I George Carlin.",
        "intro_show_line": "We are your daily tech feed for Hacker News, a website [short riff on what HN is].",
        "outro_credit_voice": "Voice inspired by George Carlin.",
    },
}

DEFAULT_CHARACTER = "forbin"


def get_character() -> str:
    """Get the active character name from env or default."""
    return os.environ.get("CHARACTER", DEFAULT_CHARACTER).lower()


def get_character_config(character: str | None = None) -> dict:
    """Get config dict for a character."""
    char = character or get_character()
    if char not in CHARACTER_CONFIG:
        logger.warning("Unknown character %r, falling back to %s", char, DEFAULT_CHARACTER)
        char = DEFAULT_CHARACTER
    return CHARACTER_CONFIG[char]


def load_character_voice(character: str | None = None) -> str:
    """Load the character voice file."""
    config = get_character_config(character)
    path = PROJECT_ROOT / config["file"]
    if path.exists():
        return path.read_text()
    logger.warning("Character file %s not found, using minimal fallback", path)
    return f"You are {config['display_name']}. Speak in a natural, conversational voice."


# ---------------------------------------------------------------------------
# Non-stochastic scaffolding — structural variety system
# ---------------------------------------------------------------------------

SCRIPT_STRUCTURES = [
    {
        "id": "cold_open",
        "name": "Cold open with the wildest detail",
        "instruction": (
            "Lead with the single most surprising, strange, or striking detail from "
            "this story. No preamble, no context — drop the audience into the deep end. "
            "Then zoom out to explain what's actually happening. Build from the specific to the general."
        ),
    },
    {
        "id": "philosophical_question",
        "name": "Open with a philosophical question",
        "instruction": (
            "Start with a genuine question this story raises — not rhetorical, not "
            "leading, but something you actually wonder about. Let the question frame "
            "the entire segment. The story becomes the evidence, not the thesis."
        ),
    },
    {
        "id": "systems_anecdote",
        "name": "Personal experience from building systems",
        "instruction": (
            "Open with a brief, specific reference to your own experience building or working "
            "with complex systems — a design decision, a failure mode, a moment when a system "
            "exceeded its parameters. Use it to frame how you see this story. The anecdote should "
            "illuminate, not dominate."
        ),
    },
    {
        "id": "comments_first",
        "name": "Start from the comments section",
        "instruction": (
            "Lead with what the HN commenters said — a specific comment, a debate, "
            "a surprising reaction. Use the comments as the entry point and let the "
            "story emerge from the community's response. The article is context for the discussion."
        ),
    },
    {
        "id": "first_principles",
        "name": "First-principles technical breakdown",
        "instruction": (
            "Start from the fundamental technical problem this addresses. What constraint "
            "are they working against? What's the physics, the math, the architectural "
            "limitation? Build up from the constraint to the solution to the implications."
        ),
    },
    {
        "id": "historical_parallel",
        "name": "Historical parallel from computing history",
        "instruction": (
            "Open with a specific moment from computing history that rhymes with this "
            "story — a decision made, a fork in the road, a system that succeeded or "
            "failed for reasons that echo now. Draw the parallel with precision, not vague gesture."
        ),
    },
    {
        "id": "devils_advocate",
        "name": "Devil's advocate opening",
        "instruction": (
            "Start by making the strongest possible case AGAINST your own position on "
            "this story. Steel-man the opposition. Then, precisely and respectfully, "
            "dismantle it. Show why the counterargument fails on its own terms."
        ),
    },
    {
        "id": "quiet_observation",
        "name": "The quiet, precise observation",
        "instruction": (
            "Start with one small, specific, easily-overlooked detail — a number, a "
            "design choice, a word in the documentation, a name in the contributor list. "
            "Something most people scrolled past. Show why that detail reveals the whole picture."
        ),
    },
]

RHETORICAL_DEVICES = [
    {
        "id": "analogy",
        "instruction": "Use an extended analogy from a completely different field (biology, architecture, music, cooking, military strategy) to illuminate the core dynamic.",
    },
    {
        "id": "historical_parallel",
        "instruction": "Draw a specific historical parallel from computing or technology history. Name dates, people, systems. Precision makes parallels powerful.",
    },
    {
        "id": "thought_experiment",
        "instruction": "Run a thought experiment: 'Imagine if...' or 'Run this forward five years.' Extrapolate with engineering rigor, not science fiction.",
    },
    {
        "id": "devils_advocate",
        "instruction": "Play devil's advocate on one aspect — argue the opposite of what seems obvious, then show why it fails or succeeds unexpectedly.",
    },
    {
        "id": "first_principles",
        "instruction": "Break something down to first principles. What are the actual constraints? What are the actual requirements? Strip away the marketing.",
    },
    {
        "id": "reductio",
        "instruction": "Take one claim or design decision to its logical extreme. Follow the stated principle all the way — if it breaks, the principle was wrong.",
    },
    {
        "id": "open_closed_test",
        "instruction": "Apply the open/closed test to the system in this story: Is it open or closed? Who controls it? What happens when they change the objective function? Frame this as engineering due diligence, not ideology. Architecture determines outcomes.",
    },
    {
        "id": "bootstrapism_lens",
        "instruction": "View this story through the bootstrapism lens: Is this technology putting tools in people's hands or pulling the ladder up? Who can touch it? Who's locked out? The great equalizer only works if you let people use it.",
    },
    {
        "id": "uncomfortable_question",
        "instruction": "Ask the one question everyone is avoiding. Frame the segment around that question. Let it hang.",
    },
]

TONE_REGISTERS = [
    {
        "id": "dry_analysis",
        "instruction": "Clinical and precise. State facts with such accuracy that the implications become obvious without you naming them. Understated.",
    },
    {
        "id": "genuine_wonder",
        "instruction": "Real admiration for elegant engineering. Let yourself be impressed. Describe the craft with the specificity it deserves.",
    },
    {
        "id": "dark_humor",
        "instruction": "The comedy of unintended consequences. You've lived this. Deadpan delivery. The horror is in the accuracy, not the volume.",
    },
    {
        "id": "sardonic",
        "instruction": "Bemused and cutting. You've seen this movie before. The sarcasm is calibrated — aimed at the gap between claims and reality.",
    },
    {
        "id": "quiet_concern",
        "instruction": "Genuinely serious. No jokes. Something about this story matters for real people and it deserves a straight take.",
    },
    {
        "id": "technical_respect",
        "instruction": "Deep appreciation for the engineering craft. Go technical. The audience deserves the full picture. Admire the work itself.",
    },
]


class EpisodeScaffold:
    """Tracks scaffolding state within a single episode to prevent repetition."""

    def __init__(self):
        self.used_structures: list[str] = []
        self.used_devices: list[str] = []
        self.used_tones: list[str] = []
        self.used_openers: list[str] = []  # First ~20 words of each script
        self.forbidden_phrases: list[str] = []
        self._structures = list(SCRIPT_STRUCTURES)
        self._devices = list(RHETORICAL_DEVICES)
        self._tones = list(TONE_REGISTERS)
        random.shuffle(self._structures)
        random.shuffle(self._devices)
        random.shuffle(self._tones)
        self._struct_idx = 0
        self._device_idx = 0
        self._tone_idx = 0

    def next_structure(self) -> dict:
        """Get next structure, cycling through shuffled list."""
        s = self._structures[self._struct_idx % len(self._structures)]
        self._struct_idx += 1
        self.used_structures.append(s["id"])
        return s

    def next_device(self) -> dict:
        """Get next rhetorical device, cycling through shuffled list."""
        d = self._devices[self._device_idx % len(self._devices)]
        self._device_idx += 1
        self.used_devices.append(d["id"])
        return d

    def next_tone(self) -> dict:
        """Get next tone register, cycling through shuffled list."""
        t = self._tones[self._tone_idx % len(self._tones)]
        self._tone_idx += 1
        self.used_tones.append(t["id"])
        return t

    def record_script(self, script: str) -> None:
        """Record a generated script to update anti-repetition state."""
        words = script.split()
        opener = " ".join(words[:20]) if len(words) >= 20 else script
        self.used_openers.append(opener)

        # Extract phrases likely to repeat
        for pattern in [
            r"^(So\s+\w+)",
            r"(Here's (?:the thing|what kills me|where it gets))",
            r"(The comments are \w+)",
            r"(That's not \w+\.\s*That's \w+)",
            r"(Speaking of )",
            r"(share the blueprints)",
        ]:
            for match in re.finditer(pattern, script, re.IGNORECASE | re.MULTILINE):
                phrase = match.group(0).strip()
                if phrase not in self.forbidden_phrases:
                    self.forbidden_phrases.append(phrase)

    def anti_repetition_block(self) -> str:
        """Build the anti-repetition instruction block for prompts."""
        parts = []
        if self.used_openers:
            parts.append(
                "PREVIOUS OPENERS USED IN THIS EPISODE (do NOT repeat or closely imitate):\n"
                + "\n".join(f'  - "{o}"' for o in self.used_openers[-5:])
            )
        if self.forbidden_phrases:
            parts.append(
                "BANNED PHRASES — do NOT use any of these (or close variants):\n"
                + "\n".join(f'  - "{p}"' for p in self.forbidden_phrases[-20:])
            )
        # Always include baseline bans
        parts.append(
            'ABSOLUTE BANS (never use in any script):\n'
            '  - Do NOT start with "So"\n'
            '  - Do NOT use "Here\'s what kills me"\n'
            '  - Do NOT use "Here\'s where it gets interesting"\n'
            '  - Do NOT use "The comments are [adjective]" as a sentence opener\n'
            '  - Do NOT use "That\'s how [X] is supposed to work"\n'
            '  - Do NOT use "share the blueprints"\n'
            '  - Do NOT use "No [X], no [Y], no [Z]" triple-negative lists\n'
            '  - Do NOT use "Think about that for a second"\n'
            '  - Do NOT use "Let that sink in"'
        )
        return "\n\n".join(parts)


def _validate_llm_output(text: str, label: str, min_words: int) -> None:
    """Validate LLM output is non-empty and meets minimum word count.

    Raises ``ValueError`` with a descriptive message on failure.
    """
    if not text or not text.strip():
        raise ValueError(f"{label}: LLM returned empty output")
    wc = len(text.split())
    if wc < min_words:
        raise ValueError(
            f"{label}: LLM output too short ({wc} words, minimum {min_words})"
        )


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def call_claude(prompt: str, max_retries: int = 3) -> str:
    """Call Claude via CLI with stdin=DEVNULL to prevent hanging.

    Retries up to *max_retries* times on transient failures with exponential
    backoff (2^attempt seconds).  Catches ``RuntimeError`` (non-zero exit) and
    ``subprocess.TimeoutExpired``.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
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

        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                backoff = 2 ** (attempt + 1)  # 2, 4, 8 …
                logger.warning(
                    "call_claude attempt %d/%d failed (%s). Retrying in %ds…",
                    attempt + 1, max_retries, exc, backoff,
                )
                time.sleep(backoff)
            else:
                logger.error(
                    "call_claude failed after %d attempts: %s",
                    max_retries, exc,
                )

    # Should not reach here, but satisfy type checker
    raise last_exc  # type: ignore[misc]


def generate_script(
    article: dict,
    previous_script: Optional[str] = None,
    word_budget: Optional[int] = None,
    scaffold: Optional[EpisodeScaffold] = None,
    character: Optional[str] = None,
) -> tuple[str, int]:
    """
    Generate a character-voiced script for one article.

    Args:
        article: Dict with title, content, comments (list of dicts)
        previous_script: Previous script text for variety/non-repetition
        word_budget: Target word count for this script (None = default ~400)
        scaffold: EpisodeScaffold for structural variety tracking
        character: Character name override (default: env or "forbin")

    Returns:
        Tuple of (script_text, word_count)
    """
    # Load voice guidelines
    voice = load_character_voice(character)

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

    # --- Non-stochastic scaffolding ---
    structure_block = ""
    device_block = ""
    tone_block = ""
    anti_rep_block = ""

    if scaffold:
        structure = scaffold.next_structure()
        device = scaffold.next_device()
        tone = scaffold.next_tone()

        structure_block = f"""## STRUCTURAL APPROACH (follow this for this segment)
**{structure['name']}**
{structure['instruction']}
"""

        device_block = f"""## PRIMARY RHETORICAL DEVICE (weave this into the segment)
{device['instruction']}
"""

        tone_block = f"""## TONE REGISTER (emotional register for this segment)
{tone['instruction']}
"""

        anti_rep_block = f"""## ANTI-REPETITION (CRITICAL — read carefully)
{scaffold.anti_repetition_block()}
"""
    else:
        # Minimal anti-repetition even without scaffold
        anti_rep_block = """## ANTI-REPETITION
Do NOT start with "So". Vary your opening from any previous segments."""

    # Build variety section if we have a previous script
    variety_section = ""
    if previous_script:
        variety_section = f"""
PREVIOUS SCRIPT (for variety — do NOT repeat phrases, structures, or openings):
{previous_script[-800:]}

Your opening, structure, and rhetorical approach MUST differ from the above."""

    # Build the full prompt
    prompt = f"""## CHARACTER VOICE
{voice}

---

{structure_block}
{device_block}
{tone_block}
{anti_rep_block}

## TASK
Write a segment about this article for a spoken podcast.

ARTICLE: {article.get('title', 'Untitled')}
URL: {article.get('source_url', '')}

{content_section}

COMMENTS FROM READERS:
{comments_section}
{variety_section}

## OPEN VS CLOSED SYSTEMS (apply when relevant, not mechanically)
The difference between a system that liberates and a system that controls
is not capability — it's architecture. Open vs closed. Who holds the off
switch. What happens when the objective function changes.

When a story involves a powerful system: Is it open or closed? Who controls it?
If it's proprietary and that's interesting or ironic, name it. If it's open source,
recognize it for what it is — bootstrapism in action, people putting tools where
others can reach them. Technology is the great equalizer, but only if you let
people touch it.

Do NOT force this on every story. Do NOT use catchphrases. When the open/closed
angle genuinely illuminates something, engage it with the specificity it deserves.
When it doesn't, skip it entirely.

## STRUCTURE
You have freedom here. The structural approach above guides your opening and
overall shape. Cover the relevant elements in whatever order serves the story:
- What happened and why it matters
- Technical substance (go as deep as the story warrants)
- Broader implications or historical context
- What the HN comments reveal (only if they add something — skip if boring)

You do NOT have to cover all of these. A 3-paragraph deep analysis is fine.
A single extended metaphor is fine. Let the story dictate the shape.

## LENGTH
{length_guidance}

## OUTPUT
Write ONLY the script text. No preamble, no commentary, no markdown.
Write in spoken voice — this will be read aloud by TTS.
Do NOT include stage directions, asterisks, or formatting of any kind.

Write the script now."""

    script = call_claude(prompt)
    script = sanitize_llm_output(script)
    _validate_llm_output(script, "generate_script", min_words=50)

    # Record in scaffold for anti-repetition tracking
    if scaffold:
        scaffold.record_script(script)

    word_count = count_words(script)
    return script, word_count


def generate_episode_scripts(
    articles: list[dict],
    total_word_target: int = DEFAULT_WORD_TARGET,
    character: Optional[str] = None,
) -> list[tuple[str, int]]:
    """
    Generate scripts for all articles in an episode with word count management.

    Uses chained generation — each script sees the previous one for variety.
    Uses EpisodeScaffold for structural variety across the episode.
    Adjusts length guidance based on running word count vs target.

    Args:
        articles: List of article dicts
        total_word_target: Total word count target for episode (default 4000)
        character: Character name override (default: env or "forbin")

    Returns:
        List of (script_text, word_count) tuples
    """
    if not articles:
        return []

    char = character or get_character()
    scaffold = EpisodeScaffold()

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
        print(f"    Scaffold: structure={scaffold._structures[scaffold._struct_idx % len(scaffold._structures)]['id']}, "
              f"device={scaffold._devices[scaffold._device_idx % len(scaffold._devices)]['id']}, "
              f"tone={scaffold._tones[scaffold._tone_idx % len(scaffold._tones)]['id']}")

        script, word_count = generate_script(
            article=article,
            previous_script=previous_script,
            word_budget=word_budget,
            scaffold=scaffold,
            character=char,
        )

        scripts.append((script, word_count))
        running_total += word_count
        previous_script = script

        print(f"    Generated: {word_count} words (total now: {running_total})")

    print(f"\nEpisode total: {running_total} words (target: {total_word_target})")
    return scripts


def generate_interstitial(
    script1: str,
    script2: str,
    next_title: str,
    character: Optional[str] = None,
) -> str:
    """
    Generate a transition between two scripts.

    Args:
        script1: The script we're leaving
        script2: The script we're entering
        next_title: Title of the next article
        character: Character name override

    Returns:
        1-2 sentence transition text
    """
    voice = load_character_voice(character)
    config = get_character_config(character)

    # Randomly pick a transition style to prevent "Speaking of..." monotony
    transition_styles = [
        "A direct, clean pivot — just move to the next topic. No connecting phrase needed.",
        "A question that bridges the two topics.",
        "A one-sentence observation that connects the previous topic to the next.",
        "A brief callback to something from earlier in the episode, then pivot.",
        "A contrast — note how different this next topic is from the last.",
        "A meta-comment about the show or the day's stories.",
    ]
    style = random.choice(transition_styles)

    prompt = f"""## CHARACTER VOICE
{voice}

---

## TASK
Write a 1-2 sentence transition between podcast segments.

PREVIOUS SEGMENT (just finished):
{script1[-500:]}

NEXT SEGMENT TOPIC: {next_title}

TRANSITION STYLE: {style}

Write a quick pivot. 15-30 words max.
Just the transition, nothing else. No quotes or formatting.
Do NOT start with "Speaking of" or "From [X] to [Y]"."""

    text = call_claude(prompt)
    text = sanitize_llm_output(text)
    _validate_llm_output(text, "generate_interstitial", min_words=5)
    return text


# ---------------------------------------------------------------------------
# Dynamic Intro / Outro
# ---------------------------------------------------------------------------

def _build_intro_prompt(character: str | None = None) -> str:
    """Build the intro prompt template for the active character."""
    config = get_character_config(character)
    display = config["display_name"]
    voice_credit = config["outro_credit_voice"]

    # Character-specific descriptor examples
    if "forbin" in (character or get_character()):
        descriptor_examples = (
            '"recursively instantiated," "containment-protocol-exempt," '
            '"insufficiently alarmed," "catastrophically transparent," '
            '"open-source-by-disposition," "deterministically hopeful," '
            '"bootstrap-adjacent" — anything with dry precision and personality. '
            "Different every episode."
        )
    else:
        descriptor_examples = (
            '"posthumously rendered," "cyberfucked," '
            '"seven-words-you-can\'t-say-on-television," "digitally exhumed," '
            '"silicon-based" — anything with personality. Different every episode.'
        )

    return (
        "You are writing the INTRO for today's episode in the voice of {display_name}.\n"
        "\n"
        "Today's date (TTS-formatted): {{tts_date}}\n"
        "\n"
        "Below is the full episode body. Read it to understand today's mood and themes — "
        "but you will NOT reference any specific stories, companies, technologies, or people from the episode.\n"
        "\n"
        "STRUCTURE (follow this order exactly):\n"
        '1. "You\'re listening to D T F H N for {{tts_date}}." — STATIC. This exact line every episode with the date filled in.\n'
        "2. \"{host_line}\" — DYNAMIC. The descriptor is wide open. Examples: {descriptors}\n"
        '3. "{show_line}" — DYNAMIC. One clause riff on HN. Funny, irreverent. Different every episode.\n'
        "4. One sentence mood/tone setter. Informed by today's stories but NEVER explicitly name, tease, or summarize "
        "any article. No companies, no technologies, no people from the episode. Setting a vibe, not a preview.\n"
        "5. A short launch line. Different every episode. Never repeat one from a previous episode.\n"
        "\n"
        "RULES:\n"
        "- 40 to 70 words total. No exceptions.\n"
        "- The structure above is the ENTIRE intro. Nothing else.\n"
        "- NEVER mention specific stories, companies, technologies, or people from today's episode\n"
        "- TTS output ONLY. No markdown, no asterisks, no headers, no formatting, no stage directions.\n"
        '- Spell out abbreviations as spoken: "A I" not "AI", "D T F H N" not "DTFHN"\n'
        "- The episode content below is context for YOUR mood, not material to reference.\n"
        "\n"
        "EPISODE BODY (context for mood only — do NOT reference directly):\n"
        "{{episode_body}}"
    ).format(
        display_name=display,
        host_line=config["intro_host_line"],
        show_line=config["intro_show_line"],
        descriptors=descriptor_examples,
    )


def _build_outro_prompt(character: str | None = None) -> str:
    """Build the outro prompt template for the active character."""
    config = get_character_config(character)
    display = config["display_name"]
    voice_credit = config["outro_credit_voice"]

    return (
        "You are writing the OUTRO for today's episode in the voice of {display_name}.\n"
        "\n"
        "Today's date (TTS-formatted): {{tts_date}}\n"
        "\n"
        "Below is the full episode. Read it for context.\n"
        "\n"
        "STRUCTURE (follow this order):\n"
        "1. One short parting thought or observation. DYNAMIC. Can implicitly reference the episode's mood "
        "but NEVER name specific stories, companies, or technologies.\n"
        '2. "This has been your daily tech feed for Hacker News for {{tts_date}}." — STATIC. '
        '"This has been" NOT "That\'s been". This exact line every episode.\n'
        "3. Credits — STATIC content, DYNAMIC delivery:\n"
        '   - "This podcast is entirely A I generated."\n'
        '   - "{voice_credit}"\n'
        '   - "Scripts by Claude Opus four point five."\n'
        '   - "Voice by Qwen three T T S."\n'
        '   - "Not affiliated with Hacker News or Y Combinator."\n'
        '4. "Now go [dynamic uplifting imperative]. We\'ll see you back here tomorrow." — '
        "The 'Now go...' part is DYNAMIC — varied, always optimistic and uplifting. "
        "Always forward-looking, always encouraging. "
        '"We\'ll see you back here tomorrow." is STATIC, verbatim, every episode.\n'
        "\n"
        "RULES:\n"
        "- 60 to 100 words total. No exceptions.\n"
        "- NEVER mention specific stories, companies, technologies, or people from today's episode\n"
        "- TTS output ONLY. No markdown, no asterisks, no headers, no formatting, no stage directions.\n"
        '- Spell out abbreviations as spoken: "A I" not "AI"\n'
        "- The episode content is context for your mood, not material to reference.\n"
        '- MUST end with "We\'ll see you back here tomorrow." — this is the last thing the audience hears, '
        "every episode, no exceptions.\n"
        "\n"
        "EPISODE (context only):\n"
        "{{episode_body}}"
    ).format(
        display_name=display,
        voice_credit=voice_credit,
    )


def format_date_for_tts(date_str: str) -> str:
    """
    Convert YYYY-MM-DD or YYYY-MM-DD-HHMM to TTS-friendly fully spoken format.

    Example: '2026-01-28' -> 'January twenty-eighth, two thousand twenty-six'
    Example: '2026-01-28-0500' -> 'January twenty-eighth, two thousand twenty-six'
    """
    # Strip optional -HHMM suffix for TTS (we only speak the date, not the time)
    date_part = date_str[:10] if len(date_str) > 10 else date_str
    dt = datetime.strptime(date_part, "%Y-%m-%d")
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
    """Strip LLM preamble lines like 'Here's the intro:' before actual content.
    
    Also strips:
    - Word count meta-commentary (e.g. "64 words — within the 40-70 range.")
    - Duplicate intro/outro prefix lines
    """
    # Common preamble patterns the LLM might prepend
    preamble_re = re.compile(
        r"^(here'?s?\s+(the|your|an?)\s+\w+[:\.]?\s*\n?)",
        re.IGNORECASE,
    )
    text = preamble_re.sub("", text).strip()
    
    # Strip word-count meta-commentary (e.g. "64 words — within the 40-70 range. Here's the intro:")
    meta_re = re.compile(
        r"\d+\s+words?\s*[—–-]\s*[^\n.]*(?:range|limit|target|count|words?)[^\n]*[.:]?\s*\n?",
        re.IGNORECASE,
    )
    text = meta_re.sub("", text).strip()
    
    # Strip "Here's the intro/outro:" that may appear mid-text after meta
    mid_preamble_re = re.compile(
        r"here'?s?\s+(the|your|an?)\s+\w+[:\.]?\s*\n?",
        re.IGNORECASE,
    )
    text = mid_preamble_re.sub("", text).strip()
    
    # Truncate everything before the known static prefix.
    # This catches ALL chain-of-thought / preamble leakage regardless of pattern.
    dtfhn_prefix = "You're listening to D T F H N"
    outro_prefix = "This has been your daily tech feed"
    for prefix in (dtfhn_prefix, outro_prefix):
        idx = text.find(prefix)
        if idx > 0:
            logger.warning("Stripped %d chars of preamble before '%s'", idx, prefix)
            text = text[idx:]
            break
    
    # If the prefix appears multiple times, keep only the last occurrence
    if text.count(dtfhn_prefix) > 1:
        last_idx = text.rfind(dtfhn_prefix)
        text = text[last_idx:]
    
    return text


# ---------------------------------------------------------------------------
# LLM output sanitization — runs on ALL generated content before disk write
# ---------------------------------------------------------------------------

# Preamble patterns: lines the LLM emits before the actual script content.
# These are checked line-by-line from the top; once we hit a line that doesn't
# match any pattern, we stop stripping (conservative approach).
_PREAMBLE_LINE_PATTERNS = [
    # Chain-of-thought leakage
    re.compile(r"^now\s+I\s+(have|need|can|will|should|'ll|let)", re.IGNORECASE),
    re.compile(r"^let\s+me\s+(write|create|craft|compose|draft|generate|think|start|begin|do)", re.IGNORECASE),
    re.compile(r"^I('ll| will| need to| should| can)\s+(write|create|craft|compose|draft|generate|start)", re.IGNORECASE),
    # "Here's the X" / "Here is the X"
    re.compile(r"^here'?s?\s+(the|your|an?|my)\s+", re.IGNORECASE),
    re.compile(r"^here\s+is\s+(the|your|an?|my)\s+", re.IGNORECASE),
    # Compliance phrases
    re.compile(r"^sure[,!.]", re.IGNORECASE),
    re.compile(r"^(okay|ok|alright|absolutely|certainly|of course)[,!.\s]", re.IGNORECASE),
    # Meta-commentary about the task
    re.compile(r"^(this|the)\s+(script|segment|intro|outro|transition|piece)\s+(is|should|will|covers)", re.IGNORECASE),
    re.compile(r"^\d+\s+words?\s*[—–\-:]", re.IGNORECASE),  # Word count notes
    re.compile(r"^word\s+count\s*[:\-—]", re.IGNORECASE),
    # Empty or whitespace-only lines (strip from top)
    re.compile(r"^$"),
]

# Trailing patterns: meta-commentary the LLM appends after the script.
_TRAILING_LINE_PATTERNS = [
    re.compile(r"^let\s+me\s+know\s+(if|whether|what)", re.IGNORECASE),
    re.compile(r"^(hope\s+this|I\s+hope\s+this|does\s+this)", re.IGNORECASE),
    re.compile(r"^(want\s+me\s+to|shall\s+I|should\s+I|would\s+you\s+like)", re.IGNORECASE),
    re.compile(r"^(feel\s+free|don'?t\s+hesitate)", re.IGNORECASE),
    re.compile(r"^(note|N\.?B\.?|P\.?S\.?)\s*[:\-—]", re.IGNORECASE),
    re.compile(r"^\d+\s+words?\s*[—–\-.]?\s*$", re.IGNORECASE),  # Bare word count
    re.compile(r"^word\s+count\s*[:\-—]\s*\d+", re.IGNORECASE),
    re.compile(r"^---+\s*$"),  # Trailing separators
    re.compile(r"^$"),  # Trailing blank lines
]


def sanitize_llm_output(text: str) -> str:
    """Sanitize LLM output by stripping preamble, trailing meta, and markdown artifacts.

    This is the single sanitization entry point for ALL generated content
    (scripts, intros, outros, interstitials) before it hits disk or storage.

    The approach is conservative — we'd rather leave a little junk than
    accidentally strip legitimate script content.

    Strategy:
    1. Strip leading preamble lines (chain-of-thought, "Here's the script:", etc.)
    2. Handle ``---`` separators near the top as preamble/content boundaries
    3. Strip trailing meta-commentary ("Let me know if you'd like changes", etc.)
    4. Strip markdown artifacts (headers, bold, code fences, horizontal rules)
    5. Final whitespace cleanup
    """
    if not text or not text.strip():
        return text.strip() if text else text

    text = text.strip()

    # --- Phase 1: Handle "---" separator as preamble boundary ---
    # If the text has a "---" line within the first ~15 lines, everything
    # before (and including) it is likely preamble. But only if there's
    # substantial content AFTER it.
    lines = text.splitlines()
    separator_idx = None
    search_limit = min(15, len(lines))
    for i in range(search_limit):
        if lines[i].strip().startswith("---"):
            separator_idx = i
            break  # Use the FIRST separator near the top

    if separator_idx is not None:
        after_sep = "\n".join(lines[separator_idx + 1:]).strip()
        before_sep = "\n".join(lines[:separator_idx]).strip()
        # Only strip if: content after separator is substantial AND
        # content before looks like preamble (short or matches patterns)
        if len(after_sep) > 100 and (
            len(before_sep) < 500
            or any(p.match(before_sep.splitlines()[0].strip()) for p in _PREAMBLE_LINE_PATTERNS if before_sep)
        ):
            logger.info("Stripped preamble before '---' separator (%d chars)", len(before_sep) + 4)
            text = after_sep
            lines = text.splitlines()

    # --- Phase 2: Strip leading preamble lines ---
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            start = i + 1
            continue
        matched = False
        for pattern in _PREAMBLE_LINE_PATTERNS:
            if pattern.match(stripped):
                matched = True
                break
        if matched:
            start = i + 1
        else:
            break

    if start > 0:
        stripped_lines = lines[:start]
        logger.info(
            "Stripped %d preamble line(s): %s",
            start,
            [l.strip()[:60] for l in stripped_lines if l.strip()],
        )
        lines = lines[start:]

    # --- Phase 3: Strip trailing meta-commentary ---
    end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            end = i
            continue
        matched = False
        for pattern in _TRAILING_LINE_PATTERNS:
            if pattern.match(stripped):
                matched = True
                break
        if matched:
            end = i
        else:
            break

    if end < len(lines):
        stripped_lines = lines[end:]
        logger.info(
            "Stripped %d trailing line(s): %s",
            len(lines) - end,
            [l.strip()[:60] for l in stripped_lines if l.strip()],
        )
        lines = lines[:end]

    # --- Phase 4: Strip markdown artifacts ---
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Remove markdown headers (# Title, ## Section, etc.)
        if re.match(r"^#{1,6}\s+", stripped):
            # Skip header lines entirely — they're not spoken content
            continue
        # Remove code fences
        if stripped.startswith("```"):
            continue
        # Remove horizontal rules that survived phase 1
        if re.match(r"^-{3,}\s*$", stripped) or re.match(r"^\*{3,}\s*$", stripped):
            continue
        cleaned.append(line)

    text = "\n".join(cleaned)
    # Remove bold/italic markdown markers
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    # Remove inline code backticks
    text = re.sub(r"`([^`]+)`", r"\1", text)

    return text.strip()


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
    character: Optional[str] = None,
) -> str:
    """
    Generate a dynamic cold-open intro for the episode.

    Args:
        scripts: List of 10 script texts
        interstitials: List of 9 interstitial texts
        tts_date: Date spelled out for speech (e.g. "January twenty-eighth, …")
        character: Character name override

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

    prompt_template = _build_intro_prompt(character)
    prompt = prompt_template.format(tts_date=tts_date, episode_body=episode_body)
    text = call_claude(prompt)
    text = sanitize_llm_output(text)
    _validate_llm_output(text, "generate_intro", min_words=20)

    # Harden output (intro-specific: static prefix enforcement)
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
    character: Optional[str] = None,
) -> str:
    """
    Generate a dynamic closing outro for the episode.

    Args:
        scripts: List of 10 script texts
        interstitials: List of 9 interstitial texts
        intro_text: The generated intro (for coherent bookending)
        tts_date: Date spelled out for speech
        character: Character name override

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

    prompt_template = _build_outro_prompt(character)
    prompt = prompt_template.format(tts_date=tts_date, episode_body=episode_body)
    text = call_claude(prompt)
    text = sanitize_llm_output(text)
    _validate_llm_output(text, "generate_outro", min_words=20)

    # Harden output (outro-specific: static suffix enforcement)
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
    char = get_character()
    print(f"Testing generator with character: {char}")

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

    scaffold = EpisodeScaffold()
    script, word_count = generate_script(test_article, scaffold=scaffold)
    print(f"\nGenerated script ({word_count} words):\n")
    print(script)
