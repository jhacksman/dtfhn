# DEPRECATED: Voice pipeline integrated into generate_episode_audio.py as of 2026-02-15
# This file is kept for reference only. Use generate_episode_audio.py with pipeline_config.json.
#!/usr/bin/env python3
"""Render DTFHN episode with dylan voice + sharp instruct, then RVC to bob.
Single takes. Handles full pipeline: TTS → RVC → merge → loudnorm → upload.

DEPRECATED: All functionality has been moved to generate_episode_audio.py
which reads pipeline_config.json for voice, RVC, pause, and music settings.
"""

import json
import os
import re
import subprocess
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

EP_DATE = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
DTFHN_DIR = Path.home() / "clawd/dtfhn"
EP_DIR = DTFHN_DIR / "data/episodes" / EP_DATE
WAV_DIR = EP_DIR / "wav_temp"
SEG_DIR = EP_DIR / "segments"

TTS_URL = "http://192.168.0.134:7849/speak"
RVC_URL = "http://192.168.0.134:7850/convert"
SHARP_INSTRUCT = "Sharp, irreverent, rapid-fire with sudden pauses. Sarcastic, biting, confrontational. Builds from conversational to explosive declarations."

WAV_DIR.mkdir(parents=True, exist_ok=True)
SEG_DIR.mkdir(parents=True, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)

def get_duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True)
        return float(r.stdout.strip())
    except:
        return 0.0

def split_script(text):
    """Split at [pause] markers and paragraph breaks."""
    # Split on [pause]
    parts = re.split(r'\[pause\]', text)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Split on double newlines (paragraphs)
        paras = re.split(r'\n\s*\n', part)
        for p in paras:
            p = p.strip()
            if p:
                chunks.append(p)
    return chunks

def tts_render(text, out_path, retries=3):
    """Render text with dylan voice + sharp instruct."""
    if out_path.exists() and out_path.stat().st_size > 1000:
        return out_path
    
    payload = {"text": text, "voice": "dylan", "instruct": SHARP_INSTRUCT, "timeout": 0}
    
    for attempt in range(retries):
        try:
            resp = requests.post(TTS_URL, json=payload, timeout=600)
            if resp.status_code == 200 and len(resp.content) > 1000:
                out_path.write_bytes(resp.content)
                return out_path
            log(f"  TTS fail: status={resp.status_code} size={len(resp.content)}")
        except Exception as e:
            log(f"  TTS error: {e}")
        time.sleep(30 * (attempt + 1))
    return None

def rvc_convert(wav_in, wav_out, retries=3):
    """Convert through RVC bob model."""
    if wav_out.exists() and wav_out.stat().st_size > 1000:
        return wav_out
    
    for attempt in range(retries):
        try:
            with open(wav_in, 'rb') as f:
                resp = requests.post(RVC_URL, files={"audio": f}, data={"model_name": "bob"}, timeout=300)
            if resp.status_code == 200 and len(resp.content) > 1000:
                wav_out.write_bytes(resp.content)
                return wav_out
            log(f"  RVC fail: status={resp.status_code} size={len(resp.content)}")
        except Exception as e:
            log(f"  RVC error: {e}")
        time.sleep(10 * (attempt + 1))
    return None

def merge_segments(seg_wavs, output_path):
    """Merge WAV segments with 1s silence gaps."""
    silence = WAV_DIR / "_silence.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=1.0",
                    str(silence)], capture_output=True, check=True)
    
    concat_file = WAV_DIR / "concat.txt"
    with open(concat_file, "w") as f:
        for i, wav in enumerate(seg_wavs):
            f.write(f"file '{wav.absolute()}'\n")
            if i < len(seg_wavs) - 1:
                f.write(f"file '{silence.absolute()}'\n")
    
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
                    "-c", "copy", str(output_path)], capture_output=True, check=True)
    
    silence.unlink(missing_ok=True)
    concat_file.unlink(missing_ok=True)
    return output_path

def loudnorm_mp3(wav_path, mp3_path):
    """Two-pass loudnorm + MP3 192k."""
    r = subprocess.run(["ffmpeg", "-i", str(wav_path), "-af",
                       "loudnorm=I=-13:TP=-1:LRA=11:print_format=json",
                       "-f", "null", "-"], capture_output=True, text=True)
    
    m = re.search(r'\{[^}]+\}', r.stderr, re.DOTALL)
    if m:
        stats = json.loads(m.group())
        mi, mtp, mlra, mth = stats["input_i"], stats["input_tp"], stats["input_lra"], stats["input_thresh"]
        subprocess.run(["ffmpeg", "-y", "-i", str(wav_path), "-af",
                       f"loudnorm=I=-13:TP=-1:LRA=11:measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:measured_thresh={mth}:linear=true",
                       "-ar", "44100", "-codec:a", "libmp3lame", "-b:a", "192k",
                       str(mp3_path)], capture_output=True, check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-i", str(wav_path),
                       "-ar", "44100", "-codec:a", "libmp3lame", "-b:a", "192k",
                       str(mp3_path)], capture_output=True, check=True)
    return mp3_path

def main():
    log(f"=== DTFHN {EP_DATE} — dylan+RVC bob pipeline ===")
    
    # Load manifest
    manifest = json.loads((EP_DIR / "manifest.json").read_text())
    segment_names = manifest["segments"]
    
    all_segment_wavs = []
    
    for seg_name in segment_names:
        script_file = EP_DIR / f"{seg_name}.txt"
        if not script_file.exists():
            log(f"SKIP {seg_name}: no script file")
            continue
        
        text = script_file.read_text().strip()
        if not text:
            continue
        
        log(f"=== {seg_name} ===")
        chunks = split_script(text)
        log(f"  {len(chunks)} chunks")
        
        chunk_wavs = []
        for ci, chunk in enumerate(chunks):
            tts_wav = WAV_DIR / f"{seg_name}_c{ci:02d}_tts.wav"
            rvc_wav = WAV_DIR / f"{seg_name}_c{ci:02d}_rvc.wav"
            
            # TTS render
            log(f"  TTS chunk {ci}: {chunk[:50]}...")
            result = tts_render(chunk, tts_wav)
            if not result:
                log(f"  FAILED TTS for {seg_name} chunk {ci}")
                continue
            
            # RVC convert
            log(f"  RVC chunk {ci}...")
            result = rvc_convert(tts_wav, rvc_wav)
            if not result:
                log(f"  FAILED RVC for {seg_name} chunk {ci}, using TTS directly")
                chunk_wavs.append(tts_wav)
                continue
            
            chunk_wavs.append(rvc_wav)
            dur = get_duration(rvc_wav)
            log(f"  chunk {ci} done: {dur:.1f}s")
        
        if chunk_wavs:
            # Merge chunks for this segment
            seg_wav = SEG_DIR / f"{seg_name}.wav"
            if len(chunk_wavs) == 1:
                subprocess.run(["cp", str(chunk_wavs[0]), str(seg_wav)], check=True)
            else:
                merge_segments(chunk_wavs, seg_wav)
            all_segment_wavs.append(seg_wav)
            log(f"  segment done: {get_duration(seg_wav):.1f}s")
    
    # Final merge
    log("=== FINAL MERGE ===")
    full_wav = WAV_DIR / "full_episode.wav"
    merge_segments(all_segment_wavs, full_wav)
    log(f"Full episode WAV: {get_duration(full_wav):.1f}s")
    
    # Loudnorm + MP3
    log("=== LOUDNORM + MP3 ===")
    mp3_path = EP_DIR / f"DTFHN-{EP_DATE}.mp3"
    loudnorm_mp3(full_wav, mp3_path)
    
    dur = get_duration(mp3_path)
    size = mp3_path.stat().st_size
    log(f"=== COMPLETE: {mp3_path.name} | {dur:.0f}s ({dur/60:.1f}min) | {size/1024/1024:.1f}MB ===")

if __name__ == "__main__":
    main()
