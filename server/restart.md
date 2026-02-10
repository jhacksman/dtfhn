# Qwen3-TTS Service Restart Notes

This setup runs the TTS API as a systemd **user** service and uses `restart.sh` to restart it.

**Service**
- Unit file: `~/.config/systemd/user/qwen-tts.service`
- Service name: `qwen-tts.service`
- ExecStart: `/home/quato/Qwen3-TTS/.venv/bin/python /home/quato/Qwen3-TTS/tts_api.py`
- Logs: `journalctl --user -u qwen-tts.service`

**Restart**
- Use: `/home/quato/Qwen3-TTS/restart.sh`
- What it does:
  - `systemctl --user daemon-reload`
  - `systemctl --user restart qwen-tts.service`

**Status / Health**
- Status: `systemctl --user status qwen-tts.service`
- Listen check: `ss -ltnp | rg ':7849'`
- Health check: `curl http://127.0.0.1:7849/health`

**Network**
- Binds to: `0.0.0.0:7849`
- LAN health check: `http://192.168.0.134:7849/health`

**Model Loading**
- Lazy-load: models load only on the first request.
- Idle unload: models unload after 1 hour of inactivity.
- Configure idle unload: `TTS_IDLE_UNLOAD_SECONDS` (default `3600`).

**Env Vars (optional)**
- `TTS_IDLE_UNLOAD_SECONDS`: idle time before unloading models.
- `TTS_CUSTOM_VOICE_MODEL_PATH`: path to CustomVoice checkpoint (if using default voices).
- `TTS_CUSTOM_VOICE_ENABLED`: set to `0` to disable default voices.
- `TTS_TIMEOUT`: per-request timeout (seconds).

**Notes**
- Idle unload logs go to the systemd journal, not `/tmp/tts_api.log`.
- If you want the service to run at boot even when logged out, enable lingering:
  - `loginctl enable-linger quato`
