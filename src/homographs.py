"""
Homograph disambiguation for TTS.

Uses an LLM to identify homographs in script text and replace them with
phonetic respellings that guide the TTS engine to the correct pronunciation.

This runs BEFORE prepare_text_for_tts() — it produces a TTS-ready variant
of the script while leaving the published script untouched.
"""

import json
import logging
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
HOMOGRAPHS_FILE = DATA_DIR / "homographs.json"


@lru_cache(maxsize=1)
def load_homographs() -> dict:
    """Load the homograph dictionary from data/homographs.json."""
    if not HOMOGRAPHS_FILE.exists():
        logger.warning("Homographs file not found: %s", HOMOGRAPHS_FILE)
        return {}
    with open(HOMOGRAPHS_FILE) as f:
        return json.load(f)


def _find_homographs_in_text(text: str) -> list[str]:
    """Find which homographs from our dictionary appear in the text."""
    homographs = load_homographs()
    found = []
    text_lower = text.lower()
    for word in homographs:
        # Word boundary check
        if re.search(rf'\b{re.escape(word)}\b', text_lower):
            found.append(word)
    return found


def _call_llm(prompt: str) -> str:
    """Call the OpenClaw gateway for LLM disambiguation."""
    gateway_port = os.environ.get("OPENCLAW_GATEWAY_PORT", "18789")
    gateway_token = os.environ.get("OPENCLAW_GATEWAY_PASSWORD") or os.environ.get(
        "DTFHN_GATEWAY_TOKEN", "ctrlhctrlh"
    )
    gateway_url = f"http://localhost:{gateway_port}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {gateway_token}",
        "Content-Type": "application/json",
    }
    body = json.dumps({
        "model": "anthropic/claude-haiku-3-5",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(gateway_url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("LLM call failed for homograph disambiguation: %s", e)
        return ""


def disambiguate_homographs(text: str) -> str:
    """Disambiguate homographs in text using LLM context analysis.

    Takes script text, identifies homographs from the dictionary,
    asks an LLM to determine the correct pronunciation for each instance,
    and returns text with phonetic respellings substituted.

    If no homographs are found, or the LLM call fails, returns the
    original text unchanged (fail-safe).

    Args:
        text: Script segment text (clean, published version)

    Returns:
        Text with homographs replaced by phonetic respellings for TTS
    """
    found = _find_homographs_in_text(text)
    if not found:
        return text

    homographs = load_homographs()

    # Build a compact reference for just the found homographs
    ref_lines = []
    for word in found:
        variants = homographs[word]
        variant_str = ", ".join(f"{k}: \"{v}\"" for k, v in variants.items())
        ref_lines.append(f"  {word}: {{{variant_str}}}")
    reference = "\n".join(ref_lines)

    prompt = f"""You are a pronunciation disambiguator for a TTS system. Given text and a homograph dictionary, replace each homograph with the correct phonetic respelling based on context.

HOMOGRAPH DICTIONARY:
{reference}

TEXT:
{text}

RULES:
- Replace EVERY instance of the listed homographs with the correct respelling from the dictionary
- Choose the respelling that matches how the word is used in context
- Keep ALL other text EXACTLY the same — same punctuation, same spacing, same line breaks
- Output ONLY the modified text, nothing else
- If unsure about a word's usage, pick the more common pronunciation in context

OUTPUT:"""

    result = _call_llm(prompt)
    if not result:
        logger.warning("Homograph disambiguation failed, using original text")
        return text

    # Sanity check: result should be roughly same length (±30%)
    len_ratio = len(result) / len(text) if text else 1.0
    if len_ratio < 0.7 or len_ratio > 1.3:
        logger.warning(
            "Homograph disambiguation result length ratio %.2f is suspicious "
            "(original %d, result %d chars). Using original.",
            len_ratio, len(text), len(result),
        )
        return text

    logger.info(
        "Disambiguated %d homograph(s) in text: %s",
        len(found), ", ".join(found),
    )
    return result
