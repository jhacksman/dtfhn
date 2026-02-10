#!/usr/bin/env python3
"""Test script generation fixes: no double headers, correct interstitial numbers."""

import json
import sys
import os

sys.path.insert(0, '/Volumes/JackPack/clawd/dtfhn')
os.chdir('/Volumes/JackPack/clawd/dtfhn')
os.environ.setdefault('CHARACTER', 'jack')

from src.generator import (
    generate_episode_scripts,
    generate_interstitial,
    generate_intro,
    generate_outro,
    generate_story_header,
    format_date_for_tts,
)

DATE = "2026-02-10"
STORIES_PATH = f"data/episodes/{DATE}/stories.json"
OUTPUT_PATH = "/tmp/dtfhn-test-episode.txt"

print(f"Loading stories from {STORIES_PATH}...")
with open(STORIES_PATH) as f:
    stories = json.load(f)

articles = stories if isinstance(stories, list) else stories.get("stories", stories.get("articles", []))

# Normalize to pipeline format
for a in articles:
    if not isinstance(a.get("comments"), list):
        a["comments"] = []
    if "content" not in a:
        a["content"] = a.get("article_text", "")
print(f"Found {len(articles)} stories")

# Generate scripts
print("\n=== Generating scripts ===")
scripts_with_counts = generate_episode_scripts(articles, total_word_target=4000, character="jack")
scripts = [s for s, _ in scripts_with_counts]

# Generate interstitials
print("\n=== Generating interstitials ===")
interstitials = []
for i in range(len(scripts) - 1):
    title = articles[i + 1].get("title", "Untitled")
    print(f"  Interstitial {i+1} -> {i+2}: {title[:50]}...")
    trans = generate_interstitial(
        scripts[i], scripts[i + 1], title,
        current_story_num=i + 1, next_story_num=i + 2,
        character="jack",
    )
    interstitials.append(trans)

# Generate intro/outro
tts_date = format_date_for_tts(DATE)
print("\n=== Generating intro ===")
intro = generate_intro(scripts, interstitials, tts_date, character="jack")
print("\n=== Generating outro ===")
outro = generate_outro(scripts, interstitials, intro, tts_date, character="jack")

# Assemble episode.txt
print("\n=== Assembling episode ===")
parts = [intro, ""]
for i, script in enumerate(scripts):
    title = articles[i].get("title", "Untitled")
    header = generate_story_header(i + 1, title)
    parts.append(header)
    parts.append("")
    parts.append(script)
    parts.append("")
    if i < len(interstitials):
        parts.append(interstitials[i])
        parts.append("")
parts.append(outro)

episode_text = "\n".join(parts)

with open(OUTPUT_PATH, "w") as f:
    f.write(episode_text)

print(f"\n✅ Episode written to {OUTPUT_PATH}")
print(f"   Total length: {len(episode_text)} chars, {len(episode_text.split())} words")

# Quick validation
print("\n=== Validation ===")
import re
double_headers = re.findall(r"Story \w+\.\s*[^\n]*\n\s*Story \w+\.", episode_text, re.IGNORECASE)
if double_headers:
    print(f"❌ DOUBLE HEADERS FOUND: {len(double_headers)}")
    for dh in double_headers:
        print(f"   {dh[:100]}")
else:
    print("✅ No double headers")

# Check interstitials for wrong numbers
for i, inter in enumerate(interstitials):
    expected_from = i + 1
    expected_to = i + 2
    nums_found = re.findall(r"story\s+(\w+)", inter, re.IGNORECASE)
    if nums_found:
        print(f"  Interstitial {expected_from}->{expected_to} mentions stories: {nums_found}")
