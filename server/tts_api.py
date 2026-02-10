#!/usr/bin/env python3
"""
TTS API Server with multi-GPU support.

Runs model instances across GPUs with one worker thread per GPU.
Requests queue in asyncio (no thread consumption while waiting).
"""

import os
import sys
import torch
import pickle
import io
import asyncio
import logging
import time
import itertools
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
import soundfile as sf
import uvicorn
from concurrent.futures import ThreadPoolExecutor, Future
from transformers import StoppingCriteria, StoppingCriteriaList

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tts_api")


class CancellationCriteria(StoppingCriteria):
    def __init__(self):
        self.cancelled = False

    def __call__(self, input_ids, scores, **kwargs):
        return self.cancelled


class TimeoutCriteria(StoppingCriteria):
    def __init__(self, timeout_s):
        self.timeout_s = timeout_s
        self.deadline = None
        self.timed_out = False

    def start(self):
        self.deadline = time.monotonic() + self.timeout_s

    def __call__(self, input_ids, scores, **kwargs):
        if self.deadline and time.monotonic() > self.deadline:
            self.timed_out = True
            return True
        return False

VOICES_DIR = Path(__file__).parent / "voices"
MODEL_PATH = Path(__file__).parent / "Qwen3-TTS-12Hz-1.7B-Base"
CUSTOM_VOICE_MODEL_PATH = Path(
    os.environ.get(
        "TTS_CUSTOM_VOICE_MODEL_PATH",
        str(Path(__file__).parent / "Qwen3-TTS-12Hz-1.7B-CustomVoice"),
    )
)
CUSTOM_VOICE_ENABLED = os.environ.get("TTS_CUSTOM_VOICE_ENABLED", "1").lower() not in ("0", "false", "no")
CUSTOM_VOICE_CONFIG_PATH = CUSTOM_VOICE_MODEL_PATH / "config.json"
NUM_GPUS = 3
DEFAULT_TIMEOUT = int(os.environ.get("TTS_TIMEOUT", "120"))

# One single-thread executor per GPU — guarantees serial access, no locks needed.
_gpu_executors: list[ThreadPoolExecutor] = []
_models: list = [None] * NUM_GPUS
_custom_models: list = [None] * NUM_GPUS
_prompts: dict = {}

# Status tracking — updated from both async and worker threads, so use threading lock.
import threading
_active: list[str | None] = [None] * NUM_GPUS
_queued: list[int] = [0] * NUM_GPUS
_completed: int = 0
_status_lock = threading.Lock()

# Job tracking
_job_counter = itertools.count(1)
_jobs: dict[int, dict] = {}  # job_id -> {future, gpu_id, text_preview, submitted_at, status}
_jobs_lock = threading.Lock()

_start_time: float = 0.0


class SpeakRequest(BaseModel):
    text: str
    voice: str = "george_carlin"
    language: str = "English"
    instruct: str | None = None
    filename: str = "output.wav"
    timeout: int | None = Field(default=None, description="Per-request timeout in seconds (overrides TTS_TIMEOUT env var)")
    non_streaming_mode: bool = True


def load_model(gpu_id):
    from qwen_tts import Qwen3TTSModel
    logger.info(f"Loading model on cuda:{gpu_id}...")
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL_PATH),
        device_map=f"cuda:{gpu_id}",
        dtype=torch.bfloat16,
        attn_implementation="flash_attention_2",
    )
    logger.info(f"Model loaded on cuda:{gpu_id}")
    return model


def load_custom_model(gpu_id):
    from qwen_tts import Qwen3TTSModel
    if not CUSTOM_VOICE_ENABLED:
        raise RuntimeError("Custom voice support disabled (TTS_CUSTOM_VOICE_ENABLED=0)")
    if not CUSTOM_VOICE_MODEL_PATH.exists():
        raise FileNotFoundError(f"Custom voice model not found at {CUSTOM_VOICE_MODEL_PATH}")
    logger.info(f"Loading custom voice model on cuda:{gpu_id}...")
    model = Qwen3TTSModel.from_pretrained(
        str(CUSTOM_VOICE_MODEL_PATH),
        device_map=f"cuda:{gpu_id}",
        dtype=torch.bfloat16,
        attn_implementation="flash_attention_2",
    )
    logger.info(f"Custom voice model loaded on cuda:{gpu_id}")
    return model


def get_model(gpu_id):
    if _models[gpu_id] is None:
        _models[gpu_id] = load_model(gpu_id)
    return _models[gpu_id]


def get_custom_model(gpu_id):
    if _custom_models[gpu_id] is None:
        _custom_models[gpu_id] = load_custom_model(gpu_id)
    return _custom_models[gpu_id]


def _load_custom_speakers_from_config() -> set[str]:
    if not CUSTOM_VOICE_CONFIG_PATH.exists():
        return set()
    try:
        with open(CUSTOM_VOICE_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        spk_id = data.get("talker_config", {}).get("spk_id", {}) or {}
        return {str(k).strip().lower() for k in spk_id.keys()}
    except Exception:
        logger.exception("Failed to load custom speakers from CustomVoice config")
        return set()


CUSTOM_SPEAKERS = _load_custom_speakers_from_config()


def _normalize_voice_name(name: str) -> str:
    return str(name).strip().lower()


def _is_custom_voice(name: str) -> bool:
    if not CUSTOM_VOICE_ENABLED:
        return False
    return _normalize_voice_name(name) in CUSTOM_SPEAKERS


def list_clone_voices() -> list[str]:
    voices = []
    for d in VOICES_DIR.iterdir():
        if d.is_dir() and (d / "prompt.pkl").exists():
            voices.append(d.name)
    return voices


def list_custom_voices() -> list[str]:
    if not CUSTOM_VOICE_ENABLED:
        return []
    return sorted(CUSTOM_SPEAKERS)


def get_prompt(voice_name):
    if voice_name in _prompts:
        return _prompts[voice_name]

    voice_dir = VOICES_DIR / voice_name
    prompt_cache = voice_dir / "prompt.pkl"

    if not prompt_cache.exists():
        raise FileNotFoundError(f"Voice '{voice_name}' not found or not built")

    with open(prompt_cache, "rb") as f:
        _prompts[voice_name] = pickle.load(f)

    return _prompts[voice_name]


def generate_on_gpu(gpu_id, text, voice, language, cancel_criteria=None, timeout_criteria=None, instruct=None, non_streaming_mode=True):
    """Run TTS on a specific GPU. Called from that GPU's single-thread executor."""
    criteria_list = []
    if cancel_criteria is not None:
        criteria_list.append(cancel_criteria)
    if timeout_criteria is not None:
        criteria_list.append(timeout_criteria)

    extra_kwargs = {}
    if criteria_list:
        extra_kwargs["stopping_criteria"] = StoppingCriteriaList(criteria_list)

    if timeout_criteria is not None:
        timeout_criteria.start()

    if _is_custom_voice(voice):
        model = get_custom_model(gpu_id)
        wavs, sr = model.generate_custom_voice(
            text=text,
            language=language,
            speaker=voice,
            instruct=instruct,
            non_streaming_mode=non_streaming_mode,
            **extra_kwargs,
        )
    else:
        model = get_model(gpu_id)
        prompt = get_prompt(voice)
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=language,
            voice_clone_prompt=prompt,
            **extra_kwargs,
        )

    if timeout_criteria is not None and timeout_criteria.timed_out:
        raise TimeoutError(f"Generation timed out after {timeout_criteria.timeout_s}s")

    if cancel_criteria is not None and cancel_criteria.cancelled:
        raise InterruptedError("Generation was cancelled")

    buf = io.BytesIO()
    sf.write(buf, wavs[0], sr, format="WAV")
    buf.seek(0)
    return buf.read()


def _get_least_queued_gpu() -> int:
    """Pick the GPU with the fewest queued + active jobs."""
    with _status_lock:
        best_gpu = 0
        best_load = _queued[0] + (1 if _active[0] is not None else 0)
        for i in range(1, NUM_GPUS):
            load = _queued[i] + (1 if _active[i] is not None else 0)
            if load < best_load:
                best_load = load
                best_gpu = i
        return best_gpu


def _finish_job(job_id: int, final_status: str):
    """Mark a job as done/failed/timed_out in the tracking dict."""
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = final_status
            _jobs[job_id]["future"] = None  # release reference


@asynccontextmanager
async def lifespan(app):
    logger.info(f"Loading models on {NUM_GPUS} GPUs...")
    # Load models sequentially on the main thread (from_pretrained isn't thread-safe
    # during dispatch — parallel loads hit meta tensor conflicts).
    for gpu_id in range(NUM_GPUS):
        get_model(gpu_id)
    for gpu_id in range(NUM_GPUS):
        _gpu_executors.append(ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"gpu-{gpu_id}"))
    logger.info("All models loaded.")
    global _start_time
    _start_time = time.time()
    yield
    for executor in _gpu_executors:
        executor.shutdown(wait=False)


app = FastAPI(title="TTS API", version="2.0", lifespan=lifespan)


@app.get("/")
def root():
    return {
        "status": "ok",
        "gpus": NUM_GPUS,
        "voices": list_voices(),
        "clone_voices": list_clone_voices(),
        "custom_voices": list_custom_voices(),
    }


@app.get("/voices")
def list_voices():
    voices = list_clone_voices()
    for v in list_custom_voices():
        if v not in voices:
            voices.append(v)
    return voices


@app.get("/voices/clones")
def list_clone_voices_endpoint():
    return list_clone_voices()


@app.get("/voices/custom")
def list_custom_voices_endpoint():
    return list_custom_voices()


@app.get("/status")
def status():
    with _status_lock:
        gpus = []
        for i in range(NUM_GPUS):
            gpus.append({
                "gpu": i,
                "active": _active[i],
                "queued": _queued[i],
            })
        total_queued = sum(_queued)
        total_active = sum(1 for a in _active if a is not None)
        return {
            "gpus": gpus,
            "total_active": total_active,
            "total_queued": total_queued,
            "completed": _completed,
        }


@app.get("/jobs")
def list_jobs():
    """List all tracked jobs with their status."""
    with _jobs_lock:
        jobs = []
        for job_id, info in _jobs.items():
            jobs.append({
                "job_id": job_id,
                "gpu_id": info["gpu_id"],
                "text_preview": info["text_preview"],
                "status": info["status"],
                "submitted_at": info["submitted_at"],
            })
    return {"jobs": jobs}


@app.delete("/jobs/{job_id}")
def cancel_job(job_id: int):
    """Cancel a job. Only succeeds for queued (not yet running) jobs."""
    with _jobs_lock:
        info = _jobs.get(job_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if info["status"] == "cancelled":
            return {"job_id": job_id, "result": "already_cancelled"}

        if info["status"] in ("done", "failed", "timed_out"):
            return {"job_id": job_id, "result": info["status"]}

        future: Future | None = info["future"]
        was_queued = info["status"] == "queued"
        if future is not None and future.cancel():
            info["status"] = "cancelled"
            info["future"] = None
            # Only decrement _queued if the executor hadn't already picked it up
            if was_queued:
                gpu_id = info["gpu_id"]
                with _status_lock:
                    _queued[gpu_id] -= 1
            return {"job_id": job_id, "result": "cancelled"}

        # Active job — signal cancellation via stopping criteria
        if info["status"] == "active":
            criteria = info.get("cancel_criteria")
            if criteria is not None:
                criteria.cancelled = True
                return {"job_id": job_id, "result": "cancelling"}
            return {"job_id": job_id, "result": "already_running"}

        return {"job_id": job_id, "result": "cancel_failed"}


@app.delete("/gpu/{gpu_id}/queue")
def flush_gpu_queue(gpu_id: int):
    """Cancel all queued (not yet running) jobs for a specific GPU."""
    if gpu_id < 0 or gpu_id >= NUM_GPUS:
        raise HTTPException(status_code=404, detail=f"GPU {gpu_id} not found (have 0-{NUM_GPUS - 1})")

    cancelled_ids = []
    with _jobs_lock:
        for job_id, info in _jobs.items():
            if info["gpu_id"] != gpu_id:
                continue
            if info["status"] != "queued":
                continue
            future: Future | None = info["future"]
            if future is not None and future.cancel():
                info["status"] = "cancelled"
                info["future"] = None
                cancelled_ids.append(job_id)

    if cancelled_ids:
        with _status_lock:
            _queued[gpu_id] -= len(cancelled_ids)

    return {"gpu_id": gpu_id, "cancelled": len(cancelled_ids), "cancelled_job_ids": cancelled_ids}



@app.get("/health")
def health():
    uptime = time.time() - _start_time if _start_time > 0 else 0
    return {"status": "ok", "uptime_s": round(uptime, 1)}


@app.post("/restart")
async def restart():
    # Cancel all queued jobs
    cancelled = 0
    with _jobs_lock:
        for job_id, info in _jobs.items():
            if info["status"] == "queued":
                future = info.get("future")
                if future is not None and future.cancel():
                    info["status"] = "cancelled"
                    info["future"] = None
                    cancelled += 1
                    with _status_lock:
                        _queued[info["gpu_id"]] -= 1

    # Signal cancellation on all active jobs
    with _jobs_lock:
        for job_id, info in _jobs.items():
            if info["status"] == "active":
                criteria = info.get("cancel_criteria")
                if criteria is not None:
                    criteria.cancelled = True

    # Wait up to 10s for active jobs to finish
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with _status_lock:
            active_count = sum(1 for a in _active if a is not None)
        if active_count == 0:
            break
        await asyncio.sleep(0.5)

    # Re-exec after delay so response gets sent
    def _do_restart():
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_do_restart, daemon=True).start()

    return {"status": "restarting", "cancelled_jobs": cancelled}


@app.post("/speak")
async def speak(req: SpeakRequest):
    global _completed
    gpu_id = _get_least_queued_gpu()
    text_preview = req.text[:50] + "..." if len(req.text) > 50 else req.text
    timeout = req.timeout if req.timeout is not None else DEFAULT_TIMEOUT

    job_id = next(_job_counter)

    # Mark queued immediately from async context
    with _status_lock:
        _queued[gpu_id] += 1

    loop = asyncio.get_running_loop()

    cancel_criteria = CancellationCriteria()
    timeout_criteria = TimeoutCriteria(timeout) if timeout > 0 else None

    # Register job BEFORE submitting so the executor thread can always find it.
    with _jobs_lock:
        _jobs[job_id] = {
            "future": None,  # patched in after submit
            "gpu_id": gpu_id,
            "text_preview": text_preview,
            "submitted_at": time.time(),
            "status": "queued",
            "cancel_criteria": cancel_criteria,
        }

    def do_generate():
        """Runs on the GPU's single-thread executor.
        Status transitions happen here so they reflect actual state:
        queued -> active (when executor picks up the job) -> done."""
        global _completed
        with _status_lock:
            _queued[gpu_id] -= 1
            _active[gpu_id] = text_preview
        with _jobs_lock:
            if _jobs[job_id]["status"] == "cancelled":
                with _status_lock:
                    _active[gpu_id] = None
                return None
            _jobs[job_id]["status"] = "active"
        try:
            result = generate_on_gpu(
                gpu_id, req.text, req.voice, req.language,
                cancel_criteria=cancel_criteria,
                timeout_criteria=timeout_criteria,
                instruct=req.instruct,
                non_streaming_mode=req.non_streaming_mode,
            )
            with _status_lock:
                _active[gpu_id] = None
                _completed += 1
            _finish_job(job_id, "done")
            return result
        except TimeoutError:
            with _status_lock:
                _active[gpu_id] = None
            _finish_job(job_id, "timed_out")
            raise
        except InterruptedError:
            with _status_lock:
                _active[gpu_id] = None
            _finish_job(job_id, "cancelled")
            raise
        except Exception:
            with _status_lock:
                _active[gpu_id] = None
            _finish_job(job_id, "failed")
            raise

    future = loop.run_in_executor(_gpu_executors[gpu_id], do_generate)

    with _jobs_lock:
        _jobs[job_id]["future"] = future

    try:
        audio_bytes = await future
    except TimeoutError:
        logger.warning(f"Job {job_id} timed out after {timeout}s on gpu:{gpu_id}")
        raise HTTPException(status_code=504, detail=f"Generation timed out after {timeout}s (job {job_id})")
    except InterruptedError:
        raise HTTPException(status_code=409, detail=f"Job {job_id} was cancelled")
    except asyncio.CancelledError:
        raise HTTPException(status_code=409, detail=f"Job {job_id} was cancelled")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception(f"Generation failed on gpu:{gpu_id}")
        raise HTTPException(status_code=500, detail="TTS generation failed")

    if audio_bytes is None:
        # Job was cancelled between queue and execution
        raise HTTPException(status_code=409, detail=f"Job {job_id} was cancelled")

    headers = {
        "Content-Disposition": f'attachment; filename="{req.filename}"',
        "X-Job-Id": str(job_id),
    }
    return Response(content=audio_bytes, media_type="audio/wav", headers=headers)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7849, workers=1)
