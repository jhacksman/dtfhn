"""
DTF:HN — Archive ingestion to shared LanceDB on JackPack.
Writes episode metadata, scripts, audio clips, sources to shared tables.
Non-blocking: warns but doesn't fail if JackPack is unmounted.
"""

from __future__ import annotations

import hashlib
import json
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pyarrow as pa

# Shared LanceDB path (same as FTL and RF)
DB_PATH = Path("/Volumes/JackPack/dtf/lancedb")
EMBEDDING_DIM = 1024

_db = None


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _null_vector() -> list[float]:
    """Null embedding vector — flagged for later backfill."""
    return [0.0] * EMBEDDING_DIM


def is_available() -> bool:
    """Check if JackPack archive is accessible."""
    return DB_PATH.exists()


def get_db():
    """Get shared LanceDB connection."""
    global _db
    if _db is None:
        import lancedb
        _db = lancedb.connect(str(DB_PATH))
    return _db


def _get_or_create_table(name: str, schema: pa.Schema):
    db = get_db()
    try:
        return db.open_table(name)
    except Exception:
        return db.create_table(name, schema=schema)


# Import shared schemas from dtfftl
# We define them inline to avoid cross-repo imports
_episodes_schema = pa.schema([
    pa.field("episode_id", pa.utf8()),
    pa.field("show", pa.utf8()),
    pa.field("episode_number", pa.utf8()),
    pa.field("title", pa.utf8()),
    pa.field("subtitle", pa.utf8()),
    pa.field("publish_date", pa.utf8()),
    pa.field("season", pa.int32()),
    pa.field("episode_of_year", pa.int32()),
    pa.field("duration_seconds", pa.float32()),
    pa.field("mp3_path", pa.utf8()),
    pa.field("description", pa.utf8()),
    pa.field("show_notes", pa.utf8()),
    pa.field("chapters_json", pa.utf8()),
    pa.field("rss_enclosure_url", pa.utf8()),
    pa.field("warc_path", pa.utf8()),
    pa.field("ai_model_script", pa.utf8()),
    pa.field("ai_model_tts", pa.utf8()),
    pa.field("human_approvals", pa.utf8()),
    pa.field("character", pa.utf8()),
    pa.field("segment_count", pa.int32()),
    pa.field("source_count", pa.int32()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
])

_sources_schema = pa.schema([
    pa.field("source_id", pa.utf8()),
    pa.field("episode_id", pa.utf8()),
    pa.field("show", pa.utf8()),
    pa.field("source_type", pa.utf8()),
    pa.field("title", pa.utf8()),
    pa.field("url", pa.utf8()),
    pa.field("captured_at", pa.utf8()),
    pa.field("warc_path", pa.utf8()),
    pa.field("html_path", pa.utf8()),
    pa.field("raw_text", pa.utf8()),
    pa.field("metadata_json", pa.utf8()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
])

_script_chunks_schema = pa.schema([
    pa.field("chunk_id", pa.utf8()),
    pa.field("episode_id", pa.utf8()),
    pa.field("show", pa.utf8()),
    pa.field("segment", pa.int32()),
    pa.field("speaker", pa.utf8()),
    pa.field("line_index", pa.int32()),
    pa.field("text", pa.utf8()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
])

_audio_clips_schema = pa.schema([
    pa.field("clip_id", pa.utf8()),
    pa.field("episode_id", pa.utf8()),
    pa.field("show", pa.utf8()),
    pa.field("script_chunk_id", pa.utf8()),
    pa.field("type", pa.utf8()),
    pa.field("speaker", pa.utf8()),
    pa.field("voice", pa.utf8()),
    pa.field("instruct", pa.utf8()),
    pa.field("text", pa.utf8()),
    pa.field("wav_path", pa.utf8()),
    pa.field("wav_size_bytes", pa.int64()),
    pa.field("wav_sha256", pa.utf8()),
    pa.field("duration_seconds", pa.float32()),
    pa.field("word_count", pa.int32()),
    pa.field("sample_rate", pa.int32()),
    pa.field("segment_index", pa.int32()),
    pa.field("render_timestamp", pa.utf8()),
    pa.field("tts_server", pa.utf8()),
])

_pipeline_runs_schema = pa.schema([
    pa.field("run_id", pa.utf8()),
    pa.field("episode_id", pa.utf8()),
    pa.field("show", pa.utf8()),
    pa.field("phase", pa.utf8()),
    pa.field("status", pa.utf8()),
    pa.field("started_at", pa.utf8()),
    pa.field("completed_at", pa.utf8()),
    pa.field("metadata_json", pa.utf8()),
    pa.field("error", pa.utf8()),
])

_scripts_schema = pa.schema([
    pa.field("script_id", pa.utf8()),
    pa.field("episode_id", pa.utf8()),
    pa.field("show", pa.utf8()),
    pa.field("version", pa.int32()),
    pa.field("full_text", pa.utf8()),
    pa.field("approved_by", pa.utf8()),
    pa.field("approved_at", pa.utf8()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
])


def archive_episode(
    episode_date: str,
    episode_dir: Path,
    stories: list[dict] = None,
    duration_seconds: float = 0.0,
    story_count: int = 10,
) -> dict:
    """
    Archive a DTFHN episode to shared LanceDB.
    Call after assembly phase completes.
    Returns summary dict.
    """
    if not is_available():
        print("WARNING: JackPack not mounted, skipping archive")
        return {"archived": False, "reason": "jackpack_unmounted"}

    try:
        episode_id = f"dtfhn-{episode_date}"
        show = "dtfhn"
        results = {}

        # 1. Episode record
        ep_table = _get_or_create_table("episodes", _episodes_schema)
        mp3_path = episode_dir / f"DTFHN-{episode_date}.mp3"
        ep_table.add([{
            "episode_id": episode_id,
            "show": show,
            "episode_number": episode_date,
            "title": f"DTF:HN {episode_date}",
            "subtitle": "",
            "publish_date": episode_date,
            "season": int(episode_date[:4]),
            "episode_of_year": 0,
            "duration_seconds": duration_seconds,
            "mp3_path": str(mp3_path) if mp3_path.exists() else "",
            "description": "",
            "show_notes": "",
            "chapters_json": "",
            "rss_enclosure_url": f"https://pod.c457.org/dtfhn/episodes/DTFHN-{episode_date}.mp3",
            "warc_path": "",
            "ai_model_script": "claude-opus-4-6",
            "ai_model_tts": "qwen3-tts/forbin",
            "human_approvals": "{}",
            "character": "forbin",
            "segment_count": story_count * 2 + 2,  # scripts + interstitials + intro/outro
            "source_count": story_count,
            "vector": _null_vector(),
        }])
        results["episode"] = True
        print(f"  ✓ Archived episode record: {episode_id}")

        # 2. Script chunks from segment text files
        chunks_table = _get_or_create_table("script_chunks", _script_chunks_schema)
        scripts_table = _get_or_create_table("scripts", _scripts_schema)
        chunk_rows = []
        full_text_parts = []

        for txt_file in sorted(episode_dir.glob("*.txt")):
            if txt_file.name == "stories.json":
                continue
            text = txt_file.read_text().strip()
            if not text:
                continue
            full_text_parts.append(text)

            # Parse segment index from filename like "01_-_script_01.txt"
            name = txt_file.stem
            seg_idx = 0
            try:
                seg_idx = int(name.split("_")[0])
            except (ValueError, IndexError):
                pass

            seg_type = "script" if "script" in name else "interstitial" if "interstitial" in name else "other"
            if "intro" in name:
                seg_type = "intro"
            elif "outro" in name:
                seg_type = "outro"

            chunk_rows.append({
                "chunk_id": _uuid(),
                "episode_id": episode_id,
                "show": show,
                "segment": seg_idx,
                "speaker": "forbin",
                "line_index": 0,
                "text": text[:10000],  # Truncate very long scripts
                "vector": _null_vector(),
            })

        if chunk_rows:
            chunks_table.add(chunk_rows)
            print(f"  ✓ Archived {len(chunk_rows)} script chunks")

        # Store full script
        if full_text_parts:
            full_text = "\n\n---\n\n".join(full_text_parts)
            scripts_table.add([{
                "script_id": _uuid(),
                "episode_id": episode_id,
                "show": show,
                "version": 1,
                "full_text": full_text[:100000],
                "approved_by": "auto",
                "approved_at": _now(),
                "vector": _null_vector(),
            }])
        results["script_chunks"] = len(chunk_rows)

        # 3. Audio clips
        clips_table = _get_or_create_table("audio_clips", _audio_clips_schema)
        clip_rows = []
        for wav_file in sorted(episode_dir.glob("*.wav")):
            duration = 0.0
            sample_rate = 0
            try:
                with wave.open(str(wav_file), "rb") as wf:
                    frames = wf.getnframes()
                    sample_rate = wf.getframerate()
                    duration = frames / float(sample_rate) if sample_rate else 0.0
            except Exception:
                pass

            # Parse segment index from filename
            seg_idx = 0
            name = wav_file.stem
            try:
                seg_idx = int(name.split("_")[0])
            except (ValueError, IndexError):
                pass

            clip_rows.append({
                "clip_id": _uuid(),
                "episode_id": episode_id,
                "show": show,
                "script_chunk_id": "",
                "type": "dialogue",
                "speaker": "forbin",
                "voice": "forbin",
                "instruct": "",
                "text": "",
                "wav_path": str(wav_file),
                "wav_size_bytes": wav_file.stat().st_size,
                "wav_sha256": "",
                "duration_seconds": round(duration, 2),
                "word_count": 0,
                "sample_rate": sample_rate,
                "segment_index": seg_idx,
                "render_timestamp": _now(),
                "tts_server": "quato",
            })

        if clip_rows:
            clips_table.add(clip_rows)
            print(f"  ✓ Archived {len(clip_rows)} audio clips")
        results["audio_clips"] = len(clip_rows)

        # 4. Story sources
        stories_path = episode_dir / "stories.json"
        if stories_path.exists():
            sources_table = _get_or_create_table("sources", _sources_schema)
            try:
                story_list = json.loads(stories_path.read_text())
                src_rows = []
                for s in story_list:
                    src_rows.append({
                        "source_id": f"{episode_id}-hn-{s.get('id', _uuid())}",
                        "episode_id": episode_id,
                        "show": show,
                        "source_type": "hackernews",
                        "title": s.get("title", ""),
                        "url": s.get("url", ""),
                        "captured_at": _now(),
                        "warc_path": "",
                        "html_path": "",
                        "raw_text": json.dumps(s)[:5000],
                        "metadata_json": json.dumps(s),
                        "vector": _null_vector(),
                    })
                if src_rows:
                    sources_table.add(src_rows)
                    print(f"  ✓ Archived {len(src_rows)} HN story sources")
                results["sources"] = len(src_rows)
            except Exception as e:
                print(f"WARNING: Story source ingest failed: {e}")

        # 5. Pipeline run
        runs_table = _get_or_create_table("pipeline_runs", _pipeline_runs_schema)
        runs_table.add([{
            "run_id": _uuid(),
            "episode_id": episode_id,
            "show": show,
            "phase": "full_pipeline",
            "status": "completed",
            "started_at": _now(),
            "completed_at": _now(),
            "metadata_json": json.dumps({
                "episode_date": episode_date,
                "story_count": story_count,
                "duration_seconds": duration_seconds,
            }),
            "error": "",
        }])
        results["pipeline_run"] = True

        print(f"  ✓ DTFHN archive complete for {episode_id}")
        return {"archived": True, **results}

    except Exception as e:
        print(f"WARNING: Archive failed (non-blocking): {e}")
        import traceback
        traceback.print_exc()
        return {"archived": False, "error": str(e)}
