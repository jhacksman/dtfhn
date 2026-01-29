"""Audio assembly for Carlin podcast.

Handles WAV concatenation and MP3 transcoding using ffmpeg.
"""
import json
import subprocess
import tempfile
from pathlib import Path

# Default silence between segments (in seconds)
DEFAULT_SILENCE_DURATION = 1.0


def generate_silence_wav(
    output_path: Path,
    duration: float = 1.0,
    sample_rate: int = 24000,
    channels: int = 1,
) -> bool:
    """
    Generate a silent WAV file using ffmpeg.
    
    Args:
        output_path: Where to save the silence WAV
        duration: Silence duration in seconds
        sample_rate: Audio sample rate (default: 24000 for F5-TTS)
        channels: Number of audio channels (default: 1 mono)
    
    Returns:
        True if successful, False otherwise
    """
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl={'mono' if channels == 1 else 'stereo'}",
            "-t", str(duration),
            "-c:a", "pcm_s16le",  # Match TTS output format
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    
    if result.returncode == 0:
        return True
    else:
        print(f"ffmpeg silence generation error: {result.stderr}")
        return False


def stitch_wavs(
    wav_files: list[Path],
    output_path: Path,
    silence_duration: float | None = DEFAULT_SILENCE_DURATION,
) -> bool:
    """
    Concatenate WAV files using ffmpeg with optional silence gaps.
    
    Args:
        wav_files: List of WAV file paths in order
        output_path: Where to save the concatenated WAV
        silence_duration: Seconds of silence between segments.
                         Set to None or 0 to disable silence gaps.
    
    Returns:
        True if successful, False otherwise
    """
    if not wav_files:
        print("No WAV files to stitch")
        return False
    
    silence_path: Path | None = None
    
    try:
        # Generate silence WAV if needed
        if silence_duration and silence_duration > 0:
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False
            ) as silence_file:
                silence_path = Path(silence_file.name)
            
            if not generate_silence_wav(silence_path, duration=silence_duration):
                print("Failed to generate silence WAV, continuing without gaps")
                silence_path.unlink(missing_ok=True)
                silence_path = None
        
        # Build file list with interleaved silence
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            list_file = Path(f.name)
            for i, wav in enumerate(wav_files):
                f.write(f"file '{wav.absolute()}'\n")
                # Add silence after each segment except the last
                if silence_path and i < len(wav_files) - 1:
                    f.write(f"file '{silence_path.absolute()}'\n")
        
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            return True
        else:
            print(f"ffmpeg stitch error: {result.stderr}")
            return False
    finally:
        # Clean up temp files
        if "list_file" in locals():
            list_file.unlink(missing_ok=True)
        if silence_path:
            silence_path.unlink(missing_ok=True)


def transcode_to_mp3(
    wav_path: Path,
    mp3_path: Path,
    bitrate: str = "128k",
) -> bool:
    """
    Transcode WAV to MP3 using ffmpeg.
    
    Args:
        wav_path: Input WAV file
        mp3_path: Output MP3 file
        bitrate: MP3 bitrate (default: 128k)
    
    Returns:
        True if successful, False otherwise
    """
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(wav_path),
            "-codec:a", "libmp3lame",
            "-b:a", bitrate,
            str(mp3_path),
        ],
        capture_output=True,
        text=True,
    )
    
    if result.returncode == 0:
        return True
    else:
        print(f"ffmpeg transcode error: {result.stderr}")
        return False


def get_audio_duration(file_path: Path) -> float:
    """
    Get duration of audio file in seconds.
    
    Uses ffprobe to extract duration metadata.
    
    Args:
        file_path: Path to audio file (WAV, MP3, etc.)
    
    Returns:
        Duration in seconds, or 0.0 on error
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(file_path),
        ],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        print(f"ffprobe error: {result.stderr}")
        return 0.0
    
    try:
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Duration parse error: {e}")
        return 0.0


def cleanup_wav_files(wav_files: list[Path]) -> int:
    """
    Delete WAV files after successful MP3 creation.
    
    WAV files are build artifacts - delete to save ~400MB per episode.
    
    Args:
        wav_files: List of WAV paths to delete
    
    Returns:
        Number of files deleted
    """
    deleted = 0
    for wav in wav_files:
        try:
            wav.unlink(missing_ok=True)
            deleted += 1
        except Exception as e:
            print(f"Failed to delete {wav}: {e}")
    return deleted
