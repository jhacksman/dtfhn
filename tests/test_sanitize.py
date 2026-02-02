"""Tests for sanitize_llm_output() — LLM preamble/meta stripping.

Covers known failure cases from production episodes and synthetic edge cases.

Note: We import the function by exec'ing just the sanitize function and its
dependencies from generator.py, to avoid pulling in the full package (which
requires requests, lancedb, etc. that may not be in the test venv).
"""

import pytest
import re
import logging
import sys
from pathlib import Path

# We need to extract sanitize_llm_output without importing the full module.
# The function only depends on `re`, `logging`, and the pattern lists defined
# above it. We'll load it by reading the source and extracting the relevant
# parts into an isolated namespace.

_src = Path(__file__).parent.parent / "src" / "generator.py"
_code = _src.read_text()

# Build a minimal module namespace
_ns = {"re": re, "logging": logging, "logger": logging.getLogger("test_sanitize")}
# Execute pattern definitions and the sanitize function
_lines = _code.split("\n")
_in_section = False
_section_code = []
for line in _lines:
    if "# LLM output sanitization" in line:
        _in_section = True
    if _in_section:
        _section_code.append(line)
        # Stop after the function ends (next top-level definition or end of file)
        if _section_code and line.startswith("def ") and "sanitize_llm_output" not in line and "_detect_prompt_leakage" not in line:
            _section_code.pop()  # remove the next function def
            break

exec("\n".join(_section_code), _ns)
sanitize_llm_output = _ns["sanitize_llm_output"]


# ---------------------------------------------------------------------------
# Known production failure: script 5 from 2026-02-01-forbin-test (commit a013a82)
# ---------------------------------------------------------------------------

SCRIPT_5_RAW = """\
Now I have the full context. Let me write the script as Dr. Forbin covering Gul Agha's 1985 Actor model dissertation.

---

Nineteen eighty-five. Gul Agha publishes a doctoral thesis at MIT that formally defines a model of concurrent computation in distributed systems. Not a product. Not a startup. A mathematical framework. And forty years later, we're still arguing about whether anyone should actually use it.

Let me make the case against it. The Actor model is seductive in the way that pure mathematical abstractions always are."""

SCRIPT_5_EXPECTED_START = "Nineteen eighty-five."


def test_known_failure_script_5():
    """The exact failure from commit a013a82 — preamble + --- separator."""
    result = sanitize_llm_output(SCRIPT_5_RAW)
    assert result.startswith(SCRIPT_5_EXPECTED_START), (
        f"Expected to start with {SCRIPT_5_EXPECTED_START!r}, got: {result[:80]!r}"
    )
    assert "Now I have the full context" not in result
    assert "Let me write the script" not in result


# ---------------------------------------------------------------------------
# Preamble stripping
# ---------------------------------------------------------------------------

class TestPreambleStripping:
    def test_heres_the_script(self):
        text = "Here's the script:\n\nThe internet broke again yesterday."
        result = sanitize_llm_output(text)
        assert result.startswith("The internet broke again yesterday.")

    def test_sure_heres(self):
        text = "Sure, here's the podcast script:\n\nFifteen years ago, nobody cared about Rust."
        result = sanitize_llm_output(text)
        assert result.startswith("Fifteen years ago")

    def test_let_me_write(self):
        text = "Let me write this as Dr. Forbin.\n\nThe failure mode was predictable."
        result = sanitize_llm_output(text)
        assert result.startswith("The failure mode was predictable.")

    def test_now_i_have_context(self):
        text = "Now I have all the context needed.\n\nOpen source won again this week."
        result = sanitize_llm_output(text)
        assert result.startswith("Open source won again this week.")

    def test_ill_write(self):
        text = "I'll write this with a cold open approach.\n\nThree point two billion dollars."
        result = sanitize_llm_output(text)
        assert result.startswith("Three point two billion dollars.")

    def test_okay_heres(self):
        text = "Okay, here's the segment:\n\nWhat kills me about this story is the timing."
        result = sanitize_llm_output(text)
        assert result.startswith("What kills me about this story")

    def test_multiple_preamble_lines(self):
        text = (
            "Now I have the full context.\n"
            "Let me write this segment.\n"
            "Here's the script:\n"
            "\n"
            "Real content starts here."
        )
        result = sanitize_llm_output(text)
        assert result.startswith("Real content starts here.")

    def test_separator_with_preamble(self):
        text = (
            "Here's a script about the topic.\n"
            "\n"
            "---\n"
            "\n"
            "The real content begins after the separator."
        )
        result = sanitize_llm_output(text)
        assert result.startswith("The real content begins after the separator.")


# ---------------------------------------------------------------------------
# Trailing meta-commentary
# ---------------------------------------------------------------------------

class TestTrailingStripping:
    def test_let_me_know(self):
        text = "Great content here.\n\nLet me know if you'd like any changes."
        result = sanitize_llm_output(text)
        assert result == "Great content here."

    def test_hope_this_helps(self):
        text = "The script ends here.\n\nHope this works for the episode!"
        result = sanitize_llm_output(text)
        assert result == "The script ends here."

    def test_want_me_to(self):
        text = "That's the core of it.\n\nWant me to revise anything?"
        result = sanitize_llm_output(text)
        assert result == "That's the core of it."

    def test_word_count_trailing(self):
        text = "Last line of script.\n\n427 words"
        result = sanitize_llm_output(text)
        assert result == "Last line of script."

    def test_word_count_with_dash(self):
        text = "End of content.\n\nWord count: 384"
        result = sanitize_llm_output(text)
        assert result == "End of content."

    def test_trailing_separator(self):
        text = "Content here.\n\n---"
        result = sanitize_llm_output(text)
        assert result == "Content here."

    def test_note_trailing(self):
        text = "Script ends.\n\nNote: I kept it under the word limit."
        result = sanitize_llm_output(text)
        assert result == "Script ends."


# ---------------------------------------------------------------------------
# Markdown artifact stripping
# ---------------------------------------------------------------------------

class TestMarkdownStripping:
    def test_header_stripped(self):
        text = "# Script\n\nActual content starts here."
        result = sanitize_llm_output(text)
        assert result == "Actual content starts here."

    def test_bold_markers_stripped(self):
        text = "This is **important** and *emphasized* content."
        result = sanitize_llm_output(text)
        assert result == "This is important and emphasized content."

    def test_code_backticks_stripped(self):
        text = "They called it `kubernetes` and the world changed."
        result = sanitize_llm_output(text)
        assert result == "They called it kubernetes and the world changed."

    def test_code_fence_stripped(self):
        text = "Before.\n```\ncode block\n```\nAfter."
        result = sanitize_llm_output(text)
        # Code fences removed, content between them kept
        assert "```" not in result
        assert "Before." in result
        assert "After." in result

    def test_horizontal_rule_stripped(self):
        text = "First paragraph.\n\n---\n\nSecond paragraph."
        # With short first paragraph, this might be treated as separator
        # but both are legitimate content. Let's test a mid-content separator.
        text = ("A" * 200 + "\n\n---\n\n" + "B" * 200)
        result = sanitize_llm_output(text)
        # The --- in the middle should be stripped as markdown artifact
        assert "---" not in result


# ---------------------------------------------------------------------------
# Conservative: must NOT strip legitimate content
# ---------------------------------------------------------------------------

class TestConservative:
    def test_script_starting_with_year(self):
        text = "Nineteen eighty-five. Something happened."
        result = sanitize_llm_output(text)
        assert result == text

    def test_script_starting_with_quote(self):
        text = '"Move fast and break things." That was the mantra.'
        result = sanitize_llm_output(text)
        assert result == text

    def test_script_starting_with_number(self):
        text = "Three point two billion dollars. That's what they raised."
        result = sanitize_llm_output(text)
        assert result == text

    def test_script_with_question_opener(self):
        text = "What happens when the machine exceeds its parameters?"
        result = sanitize_llm_output(text)
        assert result == text

    def test_let_me_in_script_body(self):
        """'Let me' in the middle of a script should NOT be stripped."""
        text = (
            "The architecture is elegant.\n"
            "Let me make the case against it.\n"
            "The Actor model is seductive."
        )
        result = sanitize_llm_output(text)
        assert "Let me make the case against it." in result

    def test_here_in_script_body(self):
        """'Here's' in middle of script should NOT be stripped."""
        text = (
            "First paragraph of real content.\n"
            "Here's where it gets interesting.\n"
            "The data shows something unexpected."
        )
        result = sanitize_llm_output(text)
        assert "Here's where it gets interesting." in result

    def test_empty_input(self):
        assert sanitize_llm_output("") == ""
        assert sanitize_llm_output("   ") == ""

    def test_clean_script_unchanged(self):
        """A clean script with no artifacts should pass through unchanged."""
        text = (
            "The first thing you notice about this paper is the date. "
            "Nineteen eighty-five. Reagan is in the White House. "
            "The internet is a DARPA project. And Gul Agha is writing "
            "a doctoral thesis that will quietly shape how we think about "
            "concurrent computation for the next four decades."
        )
        result = sanitize_llm_output(text)
        assert result == text

    def test_short_content_not_stripped_by_separator(self):
        """If content after --- is very short, don't treat --- as separator."""
        text = "Long preamble that is actually content.\n\n---\n\nShort."
        result = sanitize_llm_output(text)
        # "Short." is only 6 chars, well under 100 threshold
        # So the --- should NOT be treated as a separator
        assert "Long preamble" in result


# ---------------------------------------------------------------------------
# Combined scenarios
# ---------------------------------------------------------------------------

class TestCombined:
    def test_preamble_and_trailing(self):
        text = (
            "Here's the script:\n"
            "\n"
            "Real content in the middle.\n"
            "\n"
            "Let me know if you'd like changes."
        )
        result = sanitize_llm_output(text)
        assert result == "Real content in the middle."

    def test_preamble_separator_trailing_markdown(self):
        text = (
            "Now I have the context. Let me write this.\n"
            "\n"
            "---\n"
            "\n"
            "# Script 5\n"
            "\n"
            "The **actual** content starts here.\n"
            "\n"
            "---\n"
            "\n"
            "Word count: 52"
        )
        result = sanitize_llm_output(text)
        assert result.startswith("The actual content starts here.")
        assert "Word count" not in result
        assert "**" not in result
        assert "# Script" not in result

    def test_full_production_scenario(self):
        """Simulate a full production failure with all artifact types."""
        text = (
            "Sure, here's the script as Dr. Forbin:\n"
            "\n"
            "---\n"
            "\n"
            "Twenty twenty-six. Another year, another framework. "
            "But this one is different, and I don't say that lightly. "
            "The architecture tells you everything you need to know.\n"
            "\n"
            "The comments section, predictably, missed the point entirely. "
            "They're arguing about syntax while the real story is in the "
            "dependency graph.\n"
            "\n"
            "Let me know if you want me to adjust the tone."
        )
        result = sanitize_llm_output(text)
        assert result.startswith("Twenty twenty-six.")
        assert "Sure, here" not in result
        assert "Let me know" not in result
        assert result.endswith("dependency graph.")


# ---------------------------------------------------------------------------
# Extended leakage detection patterns (added 2026-02-03)
# ---------------------------------------------------------------------------

class TestExtendedLeakagePatterns:
    def test_i_think(self):
        text = "I think I should approach this analytically.\n\nThe kernel patch landed quietly."
        result = sanitize_llm_output(text)
        assert result.startswith("The kernel patch landed quietly.")

    def test_i_need_to(self):
        text = "I need to focus on the technical details here.\n\nFour years of development."
        result = sanitize_llm_output(text)
        assert result.startswith("Four years of development.")

    def test_step_marker(self):
        text = "Step 1: Set the scene.\n\nThe server room was silent."
        result = sanitize_llm_output(text)
        assert result.startswith("The server room was silent.")

    def test_my_approach(self):
        text = "My approach: dry systems analysis with a pivot to open source.\n\nThe architecture tells a story."
        result = sanitize_llm_output(text)
        assert result.startswith("The architecture tells a story.")

    def test_for_this_episode(self):
        text = "For this episode I'll take a measured tone.\n\nThere's a reason nobody talks about routing tables."
        result = sanitize_llm_output(text)
        assert result.startswith("There's a reason nobody talks about routing tables.")

    def test_the_script_should(self):
        text = "The script should feel analytical.\n\nDistributed consensus is a solved problem."
        result = sanitize_llm_output(text)
        assert result.startswith("Distributed consensus is a solved problem.")

    def test_i_want_to_make_sure(self):
        text = "I want to make sure this hits the right tone.\n\nThe commit log tells you everything."
        result = sanitize_llm_output(text)
        assert result.startswith("The commit log tells you everything.")

    def test_trailing_meta_about_script(self):
        text = "The architecture diagram is the product.\n\nThis script is 347 words."
        result = sanitize_llm_output(text)
        assert "347 words" not in result
        assert result.rstrip().endswith("The architecture diagram is the product.")

    def test_trailing_ive_kept(self):
        text = "The open protocol won. That's the story.\n\nI've kept this under the word limit."
        result = sanitize_llm_output(text)
        assert "word limit" not in result

    def test_first_i_planning(self):
        text = "First, I need to establish context.\n\nTwo thousand twenty-three."
        result = sanitize_llm_output(text)
        assert result.startswith("Two thousand twenty-three.")
