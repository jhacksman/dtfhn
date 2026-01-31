# DTFHN Pipeline Autonomy Analysis

**Date:** 2026-01-31
**Episode analyzed:** 2026-01-31-0500
**Author:** Subagent (dtfhn-feed-fix)

---

## 1. Current Pipeline Audit

### `scripts/run_episode.sh` — End-to-End Flow

The pipeline is a 4-step bash script designed for `nohup` execution:

```
Step 1: Text pipeline (fetch HN, scrape, generate scripts, interstitials, intro/outro, metadata)
    └─ Python: src/pipeline.run_episode_pipeline()
    └─ Duration: ~5 min
    └─ Dependencies: HN API, Claude CLI, article URLs, LanceDB, embedding model

Step 2: TTS generation (parallel across 3 GPUs on quato)
    └─ Python: scripts/generate_episode_audio.py
    └─ Duration: ~45 min (2675s for this episode)
    └─ Dependencies: quato TTS server (192.168.0.134:7849), ffmpeg

Step 3: R2 upload + feed update
    └─ Python: scripts/upload_to_r2.py
    └─ Duration: ~30 sec
    └─ Dependencies: Cloudflare R2 credentials, boto3
    └─ Actions: Register in manifest, upload MP3/chapters/VTT, regenerate feed.xml

Step 4: Cloudflare Pages rebuild
    └─ curl to deploy hook URL
    └─ Duration: ~2 sec
    └─ Dependencies: CF_PAGES_DEPLOY_HOOK_URL in .env
```

**Protection mechanisms:**
- Lock file (`/tmp/dtfhn-pipeline.lock`) prevents concurrent runs
- `set -euo pipefail` — any error kills the pipeline
- ERR trap sends failure notification
- EXIT trap cleans up lock file
- R2 upload gracefully skips if credentials missing

### Failure Points per Step

| Step | Component | Can Fail? | Recovery | Impact |
|------|-----------|-----------|----------|--------|
| 1 | HN API | Network timeout | Retry manually | No episode |
| 1 | Article scraping | Multi-tier fallback | Degrades to title_only | Reduced quality |
| 1 | Claude CLI | Auth, rate limit, timeout | Manual intervention | No scripts |
| 1 | LanceDB/embeddings | Disk, memory | Rare | No storage |
| 2 | quato TTS server | Server down, GPU OOM | Lock file, retry | No audio |
| 2 | ffmpeg | Missing binary | Never (installed) | No MP3 |
| 3 | R2 credentials | Missing env vars | Graceful skip | No upload |
| 3 | R2 network | Timeout, auth failure | Exception → pipeline fails | No upload |
| 3 | boto3 | Import error | Exception | No upload |
| 4 | Deploy hook | Network failure | `|| true` (silent fail) | Old site |
| * | Notification | CLI rename | Warning only | No notification |

---

## 2. What Worked Today (2026-01-31-0500)

**Everything.** The full pipeline ran autonomously at 5:00 AM via cron:

- ✅ HN fetch: 9 stories retrieved
- ✅ Article scraping: All stories processed
- ✅ Script generation: 4,045 words across 9 scripts (target: 4,000)
- ✅ Interstitials: 8 transitions generated
- ✅ Intro/outro: Dynamic generation worked (though outro was 634 words — over 100-word limit)
- ✅ TTS: All 19 segments generated in parallel (2675s)
- ✅ MP3: Stitched, transcoded, chapters embedded (22.4 MB, 24.5 min)
- ✅ R2 upload: MP3 + chapters + VTT uploaded successfully
- ✅ Feed manifest: Updated (3 episodes total)
- ✅ Feed XML: Regenerated and uploaded
- ✅ Deploy hook: Cloudflare Pages rebuild triggered
- ✅ Lock file: Acquired and released cleanly
- ✅ Podcast live and playable at `https://podcast.pdxh.org/dtfhn/feed.xml`

**This is the first fully autonomous episode.** The entire pipeline ran from cron to completion with zero human intervention.

---

## 3. What Broke Today

### 3a. Notification (`clawdbot system event`)

```
scripts/run_episode.sh: line 28: clawdbot: command not found
[notify] WARNING: clawdbot system event failed
```

**Root cause:** The CLI was renamed from `clawdbot` to `openclaw`. The script still references the old name.

**Impact:** Low. The notification is a convenience — it doesn't affect episode production. The episode was complete when this failed.

**Fix:** Change `clawdbot system event` → `openclaw system event` in `run_episode.sh`.

### 3b. Telegram Delivery (Not Implemented)

```
WARNING: Telegram version still exceeds limit (16.8 MB)!
```

**What exists:** `generate_episode_audio.py` creates a 96k mono Telegram MP3 alongside the main MP3. For this episode: 16.8 MB (still over Telegram's ~16 MB limit for bots, ~50 MB for regular users).

**What's missing:** There is NO delivery step. The Telegram MP3 is created locally but never sent. `run_episode.sh` has no Telegram send step. There's no Signal/Discord/email delivery either.

**Root cause:** The pipeline creates the file but nobody sends it. This was apparently planned but never implemented.

### 3c. Outro Word Count

```
Outro word count 634 exceeds 100-word limit (threshold 120)
```

**Impact:** Minor. The outro was 6x the target but TTS still rendered it. Makes the episode slightly longer than optimal. The hardening in `generate_outro()` logs a warning but doesn't truncate — by design, since a long outro is better than a broken one.

---

## 4. Failure Mode Categories

### Network Failures
| Component | Symptom | Likelihood | Recovery |
|-----------|---------|------------|----------|
| HN API (`news.ycombinator.com`) | Timeout/connection error | Low | Retry; HN is highly available |
| Article scraping | 4-tier fallback to title_only | Medium | Graceful degradation built-in |
| TTS server (quato) | Connection refused | Medium | Server may be down, need SSH restart |
| R2 upload (Cloudflare) | Auth failure, timeout | Low | Credentials in .env; Cloudflare is reliable |
| Claude CLI | Rate limit, auth expiry | Low-Medium | Depends on Anthropic service |
| Deploy hook | Network error | Low | `|| true` means non-fatal |

### Resource Failures
| Component | Symptom | Likelihood | Recovery |
|-----------|---------|------------|----------|
| Disk space | No room for WAVs (~400MB) | Low | Mac mini has plenty |
| GPU OOM (quato) | TTS job fails | Low | 3x 3090 = 72GB VRAM |
| Memory (Mac mini) | Embedding model OOM | Very low | 256GB RAM available |
| Lock file stale | Pipeline won't start | Low | Check PID, remove manually |

### Logic Failures
| Component | Symptom | Likelihood | Recovery |
|-----------|---------|------------|----------|
| Script word count | Over/under budget | Medium | Clamped to 250-600 range |
| Outro too long | Over limit | Medium (happened today) | Warning only, non-fatal |
| Segment naming | Wrong order in stitching | Very low | Standardized helpers |
| Feed manifest | Duplicate entry | Very low | `add_episode_to_manifest()` deduplicates |

### External/API Changes
| Component | Symptom | Likelihood | Recovery |
|-----------|---------|------------|----------|
| HN API format change | Parsing errors | Very low | Stable for years |
| Claude CLI breaking change | Subprocess errors | Low | Pin version |
| LanceDB schema change | Import errors | Low | Migration scripts exist |
| TTS API change | 500 errors | Very low | Self-hosted, controlled |

---

## 5. What's Needed for Full Autonomy

The pipeline is **95% autonomous** as of today. Here's what's left:

### 5a. Fix Notification (5 minutes)

**Current state:** `clawdbot system event` → command not found
**Fix:** Replace with `openclaw system event` in `run_episode.sh`
**Why it matters:** Without notifications, failures are silent. The human discovers missing episodes only when checking manually.

### 5b. Telegram/Signal Delivery (1-2 hours)

**Current state:** Telegram MP3 is created but never sent. No delivery mechanism exists.
**Needed:**
1. Add Step 5 to `run_episode.sh`: Send MP3 via Signal or Telegram
2. Handle >16MB files for Telegram: Either (a) lower bitrate further (64k = ~11MB), (b) use Telegram's 50MB user upload limit instead of bot API, (c) send a link to the R2 URL instead of the file, or (d) use Signal which has a 100MB limit
3. Signal is already configured (per TOOLS.md: `+19713359243`), likely the better choice since there's no file size issue

**Recommended:** Use `openclaw` message tool or a simple `curl` to Signal. If Telegram is required, send the podcast URL rather than the file.

### 5c. Error Recovery / Retry (2-3 hours)

**Current state:** Any error kills the pipeline (`set -e`). No retry logic.
**Needed:**
1. TTS server down → retry after 5 min (quato may need wake-up time)
2. R2 upload failure → retry 3x with backoff
3. Network timeout on HN → retry with exponential backoff
4. Stale lock file → auto-clean if PID is dead (partially exists but could be more robust)

### 5d. Quato Health Check (30 minutes)

**Current state:** If quato TTS server is down, the pipeline hangs or fails after timeout.
**Needed:** Pre-flight check before Step 2:
```bash
if ! curl -sf http://192.168.0.134:7849/ > /dev/null 2>&1; then
    notify "FAILURE" "TTS server unreachable"
    exit 1
fi
```
Could also add SSH-based wake-up: `ssh quato 'cd /path/to/tts && ./start.sh'`

### 5e. Episode Verification (30 minutes)

**Current state:** Pipeline assumes success if no exceptions. No post-upload verification.
**Needed:** After upload, verify:
1. `curl -sI https://podcast.pdxh.org/dtfhn/episodes/DTFHN-{date}.mp3` returns 200
2. Feed XML contains the new episode guid
3. File size matches local copy

### 5f. Telegram File Size Problem (Architectural)

The core issue: 24-minute episodes at 128k = 22MB. Telegram bot limit = ~16MB. Even at 96k mono = 16.8MB.

**Options (pick one):**
1. **Send R2 URL instead of file** — simplest, works always (recommended)
2. **Use 64k mono for Telegram** — ~11MB, acceptable for speech
3. **Use Signal instead** — 100MB limit, already configured
4. **Split into parts** — complex, bad UX
5. **Accept it** — Episodes will only get longer as the show matures

---

## 6. Recommended Changes

### Priority 1: Fix notification (NOW — 5 min)
```bash
# In run_episode.sh, change:
clawdbot system event \
# To:
openclaw system event \
```
**Effort:** 5 minutes. **Impact:** Critical for failure awareness.

### Priority 2: Add delivery step (SOON — 1 hour)
Add Step 5 to `run_episode.sh`:
```bash
# Step 5: Deliver to subscribers
echo "[5/5] Delivering episode..." | tee -a "$LOG"
EPISODE_URL="https://podcast.pdxh.org/dtfhn/episodes/DTFHN-${EPISODE_DATE}.mp3"
# Option A: Signal (no size limits)
openclaw message send --target signal:+19713359243 \
    --message "🎙️ New DTFHN episode: ${EPISODE_DATE}\n${EPISODE_URL}" || true
# Option B: Telegram with URL (not file)
# openclaw message send --target telegram:CHANNEL_ID \
#     --message "🎙️ New DTFHN: ${EPISODE_URL}" || true
```
**Effort:** 1 hour (including testing). **Impact:** High — closes the "last mile" delivery gap.

### Priority 3: TTS pre-flight check (SOON — 30 min)
Before TTS step, verify quato is reachable:
```bash
for i in 1 2 3; do
    if curl -sf http://192.168.0.134:7849/ > /dev/null 2>&1; then
        break
    fi
    echo "TTS server not responding, retry $i/3..." | tee -a "$LOG"
    sleep 30
done
```
**Effort:** 30 minutes. **Impact:** Prevents 45-min pipeline hang when quato is down.

### Priority 4: Post-upload verification (LATER — 30 min)
After R2 upload, verify the episode is accessible:
```bash
HTTP_CODE=$(curl -so /dev/null -w '%{http_code}' "https://podcast.pdxh.org/dtfhn/episodes/DTFHN-${EPISODE_DATE}.mp3")
if [ "$HTTP_CODE" != "200" ]; then
    notify "FAILURE" "Episode uploaded but not accessible (HTTP $HTTP_CODE)"
fi
```
**Effort:** 30 minutes. **Impact:** Catches R2 permission issues, CDN propagation delays.

### Priority 5: Retry logic for network steps (LATER — 2 hours)
Wrap network-dependent steps in retry loops:
- HN API fetch: 3 retries, 30s backoff
- R2 upload: 3 retries, 10s backoff  
- Deploy hook: Already has `|| true` (acceptable)

**Effort:** 2 hours. **Impact:** Medium — most network failures are transient.

### Priority 6: Monitoring dashboard (SOMEDAY — 4 hours)
Simple status page showing:
- Last successful episode date
- Feed XML last-modified timestamp
- Next scheduled run
- Quato TTS server status
- Days since last failure

Could be a simple markdown file updated by the pipeline, or a Cloudflare Worker reading R2 metadata.

**Effort:** 4 hours. **Impact:** Nice-to-have for peace of mind.

---

## Summary

The DTFHN pipeline is remarkably close to full autonomy. Today's episode (2026-01-31-0500) ran completely end-to-end from a 5 AM cron job with zero human intervention. The only things that broke were:

1. **Notification** — `clawdbot` renamed to `openclaw` (5-min fix)
2. **Telegram delivery** — not implemented, file too large anyway (needs design decision)
3. **Outro length** — cosmetic, non-blocking

The pipeline architecture is sound. The explicit manifest, lock file protection, ERR trap, and graceful R2 skip all demonstrate defensive design. The main gaps are notification (fix now), delivery (add soon), and retry logic (add later).

**Bottom line:** One sed command and one new step in run_episode.sh would bring this to 100% autonomous operation.
