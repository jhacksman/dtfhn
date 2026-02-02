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


def transcode_segment_to_mp3(
    wav_path: Path,
    mp3_path: Path,
    bitrate: str = "192k",
) -> bool:
    """
    Transcode a single WAV segment to MP3 and validate the result.
    
    Args:
        wav_path: Input WAV file
        mp3_path: Output MP3 file
        bitrate: MP3 bitrate (default: 192k CBR for segment archival)
    
    Returns:
        True if transcoding succeeded and output validates
    """
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    
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
    
    if result.returncode != 0:
        print(f"ffmpeg segment transcode error: {result.stderr}")
        return False
    
    return validate_segment_mp3(mp3_path)


def validate_segment_mp3(mp3_path: Path, min_size: int = 1000) -> bool:
    """
    Validate a segment MP3 file.
    
    Checks:
    - File exists
    - File size > min_size bytes
    - ffprobe can read duration (confirms it's valid audio)
    
    Args:
        mp3_path: Path to MP3 file to validate
        min_size: Minimum file size in bytes (default: 1000)
    
    Returns:
        True if MP3 is valid
    """
    if not mp3_path.exists():
        return False
    
    if mp3_path.stat().st_size < min_size:
        return False
    
    # Verify ffprobe can read it
    duration = get_audio_duration(mp3_path)
    if duration <= 0:
        return False
    
    return True


def generate_silence_mp3(
    output_path: Path,
    duration: float = 1.0,
    sample_rate: int = 24000,
    channels: int = 1,
    bitrate: str = "192k",
) -> bool:
    """
    Generate a silent MP3 file using ffmpeg.
    
    Args:
        output_path: Where to save the silence MP3
        duration: Silence duration in seconds
        sample_rate: Audio sample rate (default: 24000 for F5-TTS)
        channels: Number of audio channels (default: 1 mono)
        bitrate: MP3 bitrate (default: 192k to match segments)
    
    Returns:
        True if successful
    """
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl={'mono' if channels == 1 else 'stereo'}",
            "-t", str(duration),
            "-codec:a", "libmp3lame",
            "-b:a", bitrate,
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    
    if result.returncode == 0:
        return True
    else:
        print(f"ffmpeg silence MP3 generation error: {result.stderr}")
        return False


def stitch_mp3s_variable(
    mp3_files: list[Path],
    output_path: Path,
    silence_durations: list[float],
    bitrate: str = "192k",
) -> bool:
    """
    Concatenate segment MP3s with variable silence gaps into final episode MP3.
    
    Uses ffmpeg concat demuxer with re-encoding for clean output.
    Silence MP3s are generated at matching bitrate.
    
    Args:
        mp3_files: List of segment MP3 file paths in order
        output_path: Where to save the final episode MP3
        silence_durations: Silence duration after each MP3 (len = len(mp3_files) - 1)
        bitrate: Output MP3 bitrate (default: 192k)
    
    Returns:
        True if successful
    """
    if not mp3_files:
        print("No MP3 files to stitch")
        return False
    
    if len(silence_durations) != len(mp3_files) - 1:
        print(f"ERROR: silence_durations length ({len(silence_durations)}) must be len(mp3_files)-1 ({len(mp3_files) - 1})")
        return False
    
    # Pre-generate silence MP3s for each unique duration
    unique_durations = set(silence_durations)
    silence_mp3s = {}
    tmp_files = []
    
    try:
        for dur in unique_durations:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                silence_path = Path(f.name)
                tmp_files.append(silence_path)
            if not generate_silence_mp3(silence_path, duration=dur, bitrate=bitrate):
                print(f"Failed to generate {dur}s silence MP3")
                return False
            silence_mp3s[dur] = silence_path
        
        # Build concat file list
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            list_file = Path(f.name)
            tmp_files.append(list_file)
            for i, mp3 in enumerate(mp3_files):
                f.write(f"file '{mp3.absolute()}'\n")
                if i < len(silence_durations):
                    sil = silence_mp3s[silence_durations[i]]
                    f.write(f"file '{sil.absolute()}'\n")
        
        # Use concat demuxer with copy codec (all segments same bitrate)
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
        
        if result.returncode != 0:
            print(f"ffmpeg MP3 stitch error: {result.stderr}")
            return False
        return True
    finally:
        for f in tmp_files:
            f.unlink(missing_ok=True)


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
