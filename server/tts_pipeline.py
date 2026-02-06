#!/usr/bin/env python3
"""
TTS Pipeline for voice cloning.

Voice profiles live in voices/<name>/ with:
  - reference.mp3 (or .wav)
  - transcript.txt

Usage:
  python tts_pipeline.py --voice george_carlin --text "Hello world"
  python tts_pipeline.py --voice george_carlin --file input.txt -o output.wav
"""

import torch
import soundfile as sf
import pickle
import argparse
from pathlib import Path

VOICES_DIR = Path(__file__).parent / "voices"
MODEL_PATH = Path(__file__).parent / "Qwen3-TTS-12Hz-1.7B-Base"

_model = None


def get_model():
    global _model
    if _model is None:
        from qwen_tts import Qwen3TTSModel
        print("Loading model...")
        _model = Qwen3TTSModel.from_pretrained(
            str(MODEL_PATH),
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="flash_attention_2",
        )
    return _model


def list_voices():
    voices = []
    for d in VOICES_DIR.iterdir():
        if d.is_dir():
            audio = d / "reference.mp3"
            if not audio.exists():
                audio = d / "reference.wav"
            transcript = d / "transcript.txt"
            if audio.exists() and transcript.exists():
                voices.append(d.name)
    return voices


def load_voice_profile(voice_name):
    voice_dir = VOICES_DIR / voice_name
    if not voice_dir.exists():
        raise ValueError(f"Voice '{voice_name}' not found. Available: {list_voices()}")

    audio = voice_dir / "reference.mp3"
    if not audio.exists():
        audio = voice_dir / "reference.wav"

    transcript = (voice_dir / "transcript.txt").read_text().strip()
    prompt_cache = voice_dir / "prompt.pkl"

    return audio, transcript, prompt_cache


def get_voice_prompt(voice_name, force_rebuild=False):
    audio, transcript, prompt_cache = load_voice_profile(voice_name)

    if prompt_cache.exists() and not force_rebuild:
        print(f"Loading cached prompt for '{voice_name}'...")
        with open(prompt_cache, "rb") as f:
            return pickle.load(f)

    print(f"Building voice prompt for '{voice_name}'...")
    model = get_model()
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(audio),
        ref_text=transcript,
        x_vector_only_mode=False,
    )

    with open(prompt_cache, "wb") as f:
        pickle.dump(prompt, f)
    print(f"Cached prompt to {prompt_cache}")

    return prompt


def speak(text, voice_name, output_path=None, language="English"):
    model = get_model()
    prompt = get_voice_prompt(voice_name)

    print(f"Generating speech ({len(text)} chars)...")
    wavs, sr = model.generate_voice_clone(
        text=text,
        language=language,
        voice_clone_prompt=prompt,
    )

    if output_path:
        sf.write(output_path, wavs[0], sr)
        print(f"Saved: {output_path}")

    return wavs[0], sr


def main():
    parser = argparse.ArgumentParser(description="TTS Pipeline")
    parser.add_argument("--voice", "-v", default="george_carlin", help="Voice profile name")
    parser.add_argument("--text", "-t", help="Text to speak")
    parser.add_argument("--file", "-f", help="Read text from file")
    parser.add_argument("--output", "-o", default="output.wav", help="Output wav file")
    parser.add_argument("--language", "-l", default="English", help="Language")
    parser.add_argument("--list", action="store_true", help="List available voices")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild voice prompt")

    args = parser.parse_args()

    if args.list:
        print("Available voices:", list_voices())
        return

    if args.rebuild:
        get_voice_prompt(args.voice, force_rebuild=True)
        return

    if args.file:
        text = Path(args.file).read_text().strip()
    elif args.text:
        text = args.text
    else:
        text = "Hello world, this is a test of the voice cloning pipeline."

    speak(text, args.voice, args.output, args.language)


if __name__ == "__main__":
    main()
