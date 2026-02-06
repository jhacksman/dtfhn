# Cloudflare R2 Podcast Hosting

Zero-egress podcast hosting using Cloudflare R2 + Workers + Pages.

## What This Does

- Serves podcast MP3s and RSS feeds from R2 (free egress)
- Handles range requests for streaming/seeking (required by podcast apps)
- Falls through to Pages for website HTML
- CORS enabled for web players

## Prerequisites

- Cloudflare account (free tier works)
- Domain on Cloudflare DNS

## Setup

### 1. Create R2 Bucket

```bash
# Via Cloudflare dashboard: R2 > Create bucket
# Or via Wrangler CLI:
wrangler r2 bucket create your-podcast-bucket
```

### 2. Create the Worker

```bash
# Install Wrangler if needed
npm install -g wrangler

# Login
wrangler login

# Create worker directory
mkdir -p cloudflare && cd cloudflare

# Initialize (select "Hello World" template)
wrangler init podcast-router
```

Replace the generated `src/index.js` with `worker.js` from this folder.

### 3. Configure wrangler.toml

```toml
name = "podcast-router"
main = "src/index.js"
compatibility_date = "2024-01-01"

[[r2_buckets]]
binding = "R2_BUCKET"
bucket_name = "your-podcast-bucket"
```

### 4. Deploy

```bash
wrangler deploy
```

### 5. Set Up Custom Domain

**Option A: Worker Route (if using Pages for website)**

1. Go to Workers & Pages > your worker > Triggers
2. Add route: `podcast.yourdomain.com/*`
3. Add DNS record pointing to your Pages project

**Option B: Worker Custom Domain**

1. Workers & Pages > your worker > Triggers > Custom Domains
2. Add `podcast.yourdomain.com`
3. Cloudflare handles DNS automatically

## File Structure in R2

```
your-podcast-bucket/
├── dtfhn/
│   ├── feed.xml
│   ├── DTFHN-2026-02-06-0500.mp3
│   └── ...
└── dtfravingfinch/
    ├── feed.xml
    ├── DTFRF-2026-02-06-0530.mp3
    └── ...
```

URLs become:
- `https://podcast.yourdomain.com/dtfhn/feed.xml`
- `https://podcast.yourdomain.com/dtfhn/DTFHN-2026-02-06-0500.mp3`

## Uploading Files

```bash
# Single file
wrangler r2 object put your-podcast-bucket/dtfhn/episode.mp3 --file=episode.mp3

# Or use the R2 S3-compatible API with any S3 client
```

## Customizing

Edit `worker.js` to change:
- Path prefixes (line 6): Add your own podcast paths
- MIME types (lines 47-53): Add file extensions as needed
- Cache duration (line 56): Adjust `max-age` as needed

## Why This Works

1. **Range requests**: Podcast apps request byte ranges for streaming. The worker parses `Range` headers and returns `206 Partial Content` with proper `Content-Range`.

2. **Fallthrough**: If a file isn't in R2, the worker calls `fetch(request)` which hits your Pages origin—so your website still works.

3. **Zero egress**: R2 has no egress fees. Serve terabytes of podcast audio for free.

## Costs

- R2 storage: $0.015/GB/month
- R2 operations: 1M Class A (writes) free, 10M Class B (reads) free
- Workers: 100k requests/day free
- Egress: $0

For a daily podcast (~50MB/episode), expect ~$0.02/month storage.
