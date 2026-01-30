"""Carlin Podcast - George Carlin-style tech news podcast generator."""

from .hn import fetch_stories, Story, Comment
from .tts import (
    text_to_speech,
    text_to_speech_parallel,
    check_tts_status,
    TTS_URL,
    TTS_VOICE,
)
from .audio import (
    stitch_wavs,
    transcode_to_mp3,
    get_audio_duration,
    cleanup_wav_files,
)
from .storage import (
    # New v2 API
    store_episode,
    get_episode,
    get_episode_mp3,
    episode_exists,
    search_episodes,
    list_episodes,
    store_story,
    store_stories_batch,
    update_story_script,
    get_story,
    get_stories_by_date,
    story_exists,
    search_stories,
    get_existing_hn_ids,
    migrate_from_v1,
    # Utilities
    compress_html,
    decompress_html,
    make_story_id,
    # Backward compatibility (deprecated)
    get_existing_source_ids,
)
from .generator import (
    generate_script,
    generate_episode_scripts,
    generate_interstitial,
)
from .pipeline import (
    run_episode_pipeline,
    run_test_pipeline,
    finalize_episode_audio,
    build_segment_dicts,
    generate_episode_metadata,
)
from .metadata import embed_id3_metadata, PODCAST_METADATA
from .chapters import embed_chapters, generate_chapters_json, segments_to_chapters, load_stories_for_episode
from .transcript import generate_vtt, generate_plain_transcript

__all__ = [
    # HN
    "fetch_stories",
    "Story",
    "Comment",
    # TTS
    "text_to_speech",
    "text_to_speech_parallel",
    "check_tts_status",
    "TTS_URL",
    "TTS_VOICE",
    # Audio
    "stitch_wavs",
    "transcode_to_mp3",
    "get_audio_duration",
    "cleanup_wav_files",
    # Storage - Episodes
    "store_episode",
    "get_episode",
    "get_episode_mp3",
    "episode_exists",
    "search_episodes",
    "list_episodes",
    # Storage - Stories
    "store_story",
    "store_stories_batch",
    "update_story_script",
    "get_story",
    "get_stories_by_date",
    "story_exists",
    "search_stories",
    "get_existing_hn_ids",
    # Storage - Migration
    "migrate_from_v1",
    # Storage - Utils
    "compress_html",
    "decompress_html",
    "make_story_id",
    # Deprecated
    "get_existing_source_ids",
    # Generator
    "generate_script",
    "generate_episode_scripts",
    "generate_interstitial",
    # Pipeline
    "run_episode_pipeline",
    "run_test_pipeline",
    "finalize_episode_audio",
    "build_segment_dicts",
    "generate_episode_metadata",
    # Metadata
    "embed_id3_metadata",
    "PODCAST_METADATA",
    # Chapters
    "embed_chapters",
    "generate_chapters_json",
    "segments_to_chapters",
    # Transcripts
    "generate_vtt",
    "generate_plain_transcript",
]
