# Qwen3-TTS API Server

A multi-GPU FastAPI server for Qwen3-TTS voice cloning with job tracking, cancellation, timeouts, and intelligent load balancing.

## Features

- **Multi-GPU support** - Distributes requests across GPUs with least-queued dispatch
- **Job tracking** - Monitor, list, and cancel jobs
- **Timeouts** - Per-request and global timeout configuration
- **Voice cloning** - Use custom voice profiles with reference audio
- **Queue management** - Flush GPU queues, cancel individual jobs

## Prerequisites

1. **Qwen3-TTS** - Install the qwen_tts package:
   ```bash
   pip install qwen-tts
   # or clone and install from: https://github.com/QwenLM/Qwen3-TTS
   ```

2. **Model weights** - Download from HuggingFace:
   ```bash
   # Using huggingface-cli
   huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base --local-dir Qwen3-TTS-12Hz-1.7B-Base
   ```

3. **Dependencies**:
   ```bash
   pip install fastapi uvicorn soundfile torch transformers
   ```

4. **Flash Attention 2** (recommended for performance):
   ```bash
   pip install flash-attn --no-build-isolation
   ```

## Setup

1. Place the server files in your project:
   ```
   your-project/
   ├── tts_api.py
   ├── tts_pipeline.py
   ├── restart.sh
   ├── Qwen3-TTS-12Hz-1.7B-Base/  # model weights
   └── voices/
       └── <voice_name>/
           ├── reference.mp3      # or reference.wav
           └── transcript.txt     # exact transcript of reference audio
   ```

2. Configure `tts_api.py` (edit these constants at the top):
   ```python
   VOICES_DIR = Path(__file__).parent / "voices"
   MODEL_PATH = Path(__file__).parent / "Qwen3-TTS-12Hz-1.7B-Base"
   NUM_GPUS = 3  # adjust to your GPU count
   ```

3. Build voice prompts (required before first use):
   ```bash
   python tts_pipeline.py --voice <voice_name> --rebuild
   ```

## Running the Server

```bash
# Direct
python tts_api.py

# With restart script
./restart.sh

# With custom timeout (default: 120s)
TTS_TIMEOUT=180 python tts_api.py
```

Server runs on `http://localhost:7849` by default.

## API Endpoints

### Generate Speech

```bash
POST /speak
Content-Type: application/json

{
  "text": "Hello, world!",
  "voice": "my_voice",
  "language": "English",
  "filename": "output.wav",
  "timeout": 120
}
```

Returns: WAV audio file with `X-Job-Id` header.

### List Voices

```bash
GET /voices
```

### Server Status

```bash
GET /status
```

Returns GPU status, active jobs, queue depth, and completion count.

### Health Check

```bash
GET /health
```

### Job Management

```bash
# List all jobs
GET /jobs

# Cancel a job
DELETE /jobs/{job_id}

# Flush all queued jobs for a GPU
DELETE /gpu/{gpu_id}/queue
```

### Restart Server

```bash
POST /restart
```

Cancels all queued jobs, signals active jobs to stop, and restarts the process.

## Voice Setup

Each voice needs a folder in `voices/` with:

| File | Description |
|------|-------------|
| `reference.mp3` or `reference.wav` | 5-30 seconds of clear speech |
| `transcript.txt` | Exact transcript of the reference audio |

After adding a voice, build its prompt cache:

```bash
python tts_pipeline.py --voice <voice_name> --rebuild
```

This creates `prompt.pkl` which the API server uses for fast inference.

## GPU Configuration

The server is configured via constants at the top of `tts_api.py`:

```python
NUM_GPUS = 3  # Number of GPUs to use
```

### Single GPU Setup

For a single GPU, edit `tts_api.py`:

```python
NUM_GPUS = 1
```

The server will load one model instance and process requests sequentially.

### Multi-GPU Setup

With multiple GPUs, the server:
- Loads a separate model instance on each GPU at startup
- Routes requests to the GPU with the shortest queue (least-queued dispatch)
- Processes requests in parallel across GPUs

**Memory requirements:** ~4GB VRAM per GPU for the 1.7B model with bfloat16.

### Local Development (No Flash Attention)

If you don't have Flash Attention 2, edit `tts_api.py` line ~94:

```python
# Change this:
attn_implementation="flash_attention_2",

# To this:
attn_implementation="sdpa",  # or remove the line entirely
```

Also update `tts_pipeline.py` line ~35 similarly.

### CPU-Only (Not Recommended)

CPU inference is technically possible but extremely slow (~10x slower). Change `device_map` in both files:

```python
device_map="cpu",
dtype=torch.float32,  # bfloat16 may not work on CPU
```

Remove the `attn_implementation` line entirely.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_TIMEOUT` | `120` | Default generation timeout in seconds |

## Example Client

```python
import requests

response = requests.post(
    "http://localhost:7849/speak",
    json={
        "text": "This is a test of the voice cloning system.",
        "voice": "my_voice",
        "language": "English",
    }
)

if response.status_code == 200:
    with open("output.wav", "wb") as f:
        f.write(response.content)
    print(f"Job ID: {response.headers.get('X-Job-Id')}")
```

## License

Server code is provided as-is. Qwen3-TTS model and library are subject to their own license terms.
