#!/usr/bin/env python3
"""
Test pipeline for Carlin podcast.
Uses 2 sample articles to validate the full flow.
"""

import subprocess
import sys
from pathlib import Path

import requests

# Config
OUTPUT_DIR = Path(__file__).parent / "output"
TTS_URL = "http://192.168.0.134:7849/speak"
CLI_TIMEOUT = 120  # 2 min per call

# Sample articles for testing
SAMPLE_ARTICLES = [
    {
        "title": "Tech Company Announces AI That Can Feel Emotions",
        "content": """Silicon Valley startup EmotiCore announced today that their new AI system can 
        genuinely experience emotions. CEO Brad Hoffman demonstrated the technology at a press 
        conference, showing the AI responding to sad videos with what he called "authentic digital 
        tears." Critics point out the company has raised $400 million despite having no peer-reviewed 
        research. The AI reportedly felt "hurt" by the criticism.""",
        "comments": [
            "This is obviously bullshit but I want to believe",
            "My toaster has more emotional range",
            "Investors will literally fund anything with AI in the name",
            "Can it feel the emotion of being turned off?"
        ]
    },
    {
        "title": "Florida Man Arrested For Teaching Alligator To Use Vending Machine", 
        "content": """A 47-year-old Tampa resident was taken into custody after witnesses reported 
        seeing him coaching a 6-foot alligator through the process of purchasing snacks from a 
        vending machine at a rest stop. Wildlife officials say the alligator, nicknamed "Chomps," 
        had successfully obtained three bags of Doritos before being apprehended. The man claims 
        he was conducting "important research" and demanded his alligator be given visitation rights.""",
        "comments": [
            "Florida never disappoints",
            "The alligator made better food choices than most humans",
            "This is why I moved out of Florida",
            "Did the gator at least get to keep the Doritos?"
        ]
    }
]

# Static intro/outro
INTRO = """Welcome to another episode of News From The Edge, where we take a look at the 
absolute circus that passes for news these days. I'm your host, coming to you from beyond 
the grave, because apparently even death can't stop me from pointing out the obvious."""

OUTRO = """And that's all the time we have for today's descent into madness. Remember, 
the world is run by people who got C's in high school, and somehow we're all surprised 
when things go wrong. Until next time, try not to let the bastards grind you down."""


# =============================================================================
# Carlin System Prompt
# =============================================================================
CARLIN_SYSTEM_PROMPT = """You are George Carlin writing a segment for your news commentary podcast.

## Carlin's Voice
- Observational, bemused, cynical
- Punch up at institutions, not down at people
- Profanity is spice, not the meal
- Short punchy sentences
- Find the absurdity, don't manufacture it

## Output
Write ONLY the script text. No preamble, no commentary, no markdown."""


def call_claude(prompt: str) -> str:
    """Call Claude via CLI."""
    full_prompt = f"{CARLIN_SYSTEM_PROMPT}\n\n---\n\n{prompt}"
    
    result = subprocess.run(
        ["claude", "-p", full_prompt],
        stdin=subprocess.DEVNULL,  # Prevent hang on auth prompts
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr or result.stdout}")
    
    return result.stdout


def generate_article_script(article: dict) -> str:
    """Generate 5-paragraph Carlin script for one article."""
    prompt = f"""Write a 5-paragraph segment about this article:

ARTICLE: {article['title']}

{article['content']}

COMMENTS FROM READERS:
{chr(10).join('- ' + c for c in article['comments'])}

Structure:
1. What happened (the news)
2. Key players involved  
3. Why this matters (or why it's absurd)
4. Broader context
5. What the comments reveal about people

Write the script now."""

    return call_claude(prompt)


def generate_interstitial(script1: str, script2: str, article2_title: str) -> str:
    """Generate 1-2 sentence transition between two articles."""
    prompt = f"""Write a 1-2 sentence transition between podcast segments.

PREVIOUS SEGMENT (just finished):
{script1[-500:]}

NEXT SEGMENT TOPIC: {article2_title}

Write a quick Carlin-style pivot. 15-30 words max. Just the transition, nothing else."""

    return call_claude(prompt)


def text_to_speech(text: str, output_path: Path) -> None:
    """Call TTS API and save WAV."""
    response = requests.post(
        TTS_URL,
        headers={"Content-Type": "application/json"},
        json={"text": text}
    )
    response.raise_for_status()
    output_path.write_bytes(response.content)
    print(f"  → {output_path.name} ({len(response.content)} bytes)")


def stitch_wavs(wav_files: list[Path], output_path: Path) -> None:
    """Concatenate WAV files using ffmpeg."""
    # Create file list for ffmpeg
    list_file = OUTPUT_DIR / "files.txt"
    with open(list_file, "w") as f:
        for wav in wav_files:
            f.write(f"file '{wav.absolute()}'\n")
    
    # Concatenate
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy", str(output_path)
    ], check=True, capture_output=True)
    
    list_file.unlink()
    print(f"  → {output_path.name}")


def transcode_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    """Convert WAV to MP3."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-qscale:a", "2",
        str(mp3_path)
    ], check=True, capture_output=True)
    print(f"  → {mp3_path.name}")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("CARLIN PODCAST TEST PIPELINE")
    print("=" * 60)
    
    # Step 1: Generate article scripts
    print("\n[1/6] Generating article scripts...")
    scripts = []
    for i, article in enumerate(SAMPLE_ARTICLES):
        print(f"  Article {i+1}: {article['title'][:40]}...")
        script = generate_article_script(article)
        scripts.append(script)
        # Save script for debugging
        (OUTPUT_DIR / f"script_{i+1}.txt").write_text(script)
        print(f"    Done ({len(script)} chars)")
    
    # Step 2: Generate interstitials
    print("\n[2/6] Generating interstitials...")
    interstitials = []
    for i in range(len(scripts) - 1):
        print(f"  Interstitial {i+1}-{i+2}...")
        interstitial = generate_interstitial(
            scripts[i], 
            scripts[i+1],
            SAMPLE_ARTICLES[i+1]["title"]
        )
        interstitials.append(interstitial)
        (OUTPUT_DIR / f"interstitial_{i+1}_{i+2}.txt").write_text(interstitial)
        print(f"    Done ({len(interstitial)} chars)")
    
    # Step 3: Build segment list
    print("\n[3/6] Assembling segments...")
    segments = []
    segments.append(("intro", INTRO))
    for i, script in enumerate(scripts):
        segments.append((f"script_{i+1}", script))
        if i < len(interstitials):
            segments.append((f"interstitial_{i+1}_{i+2}", interstitials[i]))
    segments.append(("outro", OUTRO))
    
    print(f"  {len(segments)} segments total")
    
    # Step 4: TTS each segment
    print("\n[4/6] Generating audio...")
    wav_files = []
    for name, text in segments:
        wav_path = OUTPUT_DIR / f"{name}.wav"
        text_to_speech(text, wav_path)
        wav_files.append(wav_path)
    
    # Step 5: Stitch WAVs
    print("\n[5/6] Stitching audio...")
    episode_wav = OUTPUT_DIR / "episode.wav"
    stitch_wavs(wav_files, episode_wav)
    
    # Step 6: Transcode to MP3
    print("\n[6/6] Transcoding to MP3...")
    episode_mp3 = OUTPUT_DIR / "episode.mp3"
    transcode_to_mp3(episode_wav, episode_mp3)
    
    print("\n" + "=" * 60)
    print("DONE!")
    print(f"Output: {episode_mp3}")
    print("=" * 60)


if __name__ == "__main__":
    main()
