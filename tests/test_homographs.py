"""Tests for homograph disambiguation module."""

import json
from unittest.mock import patch
from src.homographs import (
    load_homographs,
    _find_homographs_in_text,
    disambiguate_homographs,
)


def test_load_homographs():
    """Homographs dictionary loads and has expected structure."""
    h = load_homographs()
    assert isinstance(h, dict)
    assert "read" in h
    assert "past_tense" in h["read"]
    assert "present_tense" in h["read"]


def test_find_homographs_in_text():
    """Finds homographs that appear in text."""
    load_homographs.cache_clear()
    found = _find_homographs_in_text("I read the live broadcast")
    assert "read" in found
    assert "live" in found


def test_find_no_homographs():
    """Returns empty list when no homographs present."""
    load_homographs.cache_clear()
    found = _find_homographs_in_text("The quick brown fox")
    assert found == []


def test_disambiguate_no_homographs():
    """Returns original text unchanged when no homographs found."""
    load_homographs.cache_clear()
    text = "The quick brown fox jumps."
    assert disambiguate_homographs(text) == text


def test_disambiguate_fails_gracefully():
    """Returns original text when LLM call fails."""
    load_homographs.cache_clear()
    text = "I read the book."
    with patch("src.homographs._call_llm", return_value=""):
        result = disambiguate_homographs(text)
    assert result == text


def test_disambiguate_rejects_bad_length():
    """Rejects LLM output that's wildly different in length."""
    load_homographs.cache_clear()
    text = "I read the book."
    with patch("src.homographs._call_llm", return_value="way too long " * 100):
        result = disambiguate_homographs(text)
    assert result == text


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
