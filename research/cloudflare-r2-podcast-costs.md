# Cloudflare R2 Podcast Hosting: Real Cost Analysis

> Researched 2026-01-29. Prices sourced from official Cloudflare, AWS, Backblaze, and Bunny.net pricing pages.

## Assumptions

| Parameter | Value |
|---|---|
| Episode size | 20 MB (MP3) |
| Frequency | Daily (30 episodes/month) |
| New storage/month | ~600 MB |
| New storage/year | ~7.2 GB |
| RSS feed | ~50 KB XML, regenerated daily |
| Archive | Keep everything forever |
| Listener tiers | 100 / 1,000 / 10,000 daily listeners |

---

## 1. Cloudflare R2 Pricing (Current)

**Source:** https://developers.cloudflare.com/r2/pricing/

### Free Tier (per month)
| Resource | Free Allowance |
|---|---|
| Storage | 10 GB-month |
| Class A ops (writes) | 1,000,000 |
| Class B ops (reads) | 10,000,000 |
| Egress | **$0 — always free** |

### Paid Rates (after free tier)
| Resource | Cost |
|---|---|
| Storage | $0.015 / GB-month |
| Class A ops | $4.50 / million |
| Class B ops | $0.36 / million |
| Egress | **$0** |

**The killer feature: R2 has zero egress fees.** This is not a promotional deal — it's the core pricing model. Egress is free whether served via Workers API, S3 API, or r2.dev public domains.

---

## 2. Bandwidth & Operations Math

### Storage Growth

| Timeframe | Cumulative Storage |
|---|---|
| Month 1 | 0.6 GB |
| Month 6 | 3.6 GB |
| Year 1 | 7.2 GB |
| Year 2 | 14.4 GB |
| Year 3 | 21.6 GB |

**Free tier covers storage through ~16 months** (10 GB free). After that, you pay $0.015/GB-month on the overage.

At year 2 (14.4 GB): (14.4 - 10) × $0.015 = **$0.066/month**
At year 3 (21.6 GB): (21.6 - 10) × $0.015 = **$0.174/month**
At year 5 (36 GB): (36 - 10) × $0.015 = **$0.39/month**

Storage costs are negligible for years.

### Bandwidth (Egress)

Each listener downloads 1 episode (20 MB) per day.

| Daily Listeners | Monthly Downloads | Monthly Bandwidth |
|---|---|---|
| 100 | 3,000 | 60 GB |
| 1,000 | 30,000 | 600 GB |
| 10,000 | 300,000 | 6,000 GB (6 TB) |

**R2 egress cost for ALL tiers: $0.** Zero. Nada. This is the entire point.

### Class B Operations (reads = GetObject)

Each download = 1 Class B operation. RSS feed fetches also count.

| Daily Listeners | Monthly MP3 Downloads | Monthly RSS Fetches (est.) | Total Class B Ops |
|---|---|---|---|
| 100 | 3,000 | ~6,000 | ~9,000 |
| 1,000 | 30,000 | ~60,000 | ~90,000 |
| 10,000 | 300,000 | ~600,000 | ~900,000 |

**Free tier: 10 million Class B ops/month.** Even at 10,000 daily listeners, we use under 1 million. All free.

(RSS fetches estimated at 2× downloads — podcast apps poll the feed plus actual episode downloads.)

### Class A Operations (writes = PutObject)

- 1 new episode upload/day = 30/month
- 1 RSS regeneration/day = 30/month
- Total: ~60 Class A ops/month

**Free tier: 1 million.** We use 60. Laughably under the limit.

---

## 3. Workers Pricing (for custom RSS endpoint)

**Source:** https://developers.cloudflare.com/workers/platform/pricing/

You might want a Worker to:
- Serve the RSS XML with proper `Content-Type: application/rss+xml`
- Add caching headers
- Redirect `/feed` to the R2 object
- Analytics/tracking

### Free Plan
- 100,000 requests/day (3M/month)
- 10 ms CPU time per invocation

### Paid Plan ($5/month base)
- 10 million requests/month included
- $0.30 per additional million
- 30 million CPU ms/month included

**For our podcast:** Even at 10,000 daily listeners, RSS + episode requests are under 1 million/month. The **free Worker plan is sufficient.**

However: if you want the Worker, you don't even need one. R2 supports **public buckets** via `r2.dev` subdomains or custom domains, serving objects directly without a Worker.

### Verdict: Workers cost = $0

---

## 4. Cloudflare Pages (Alternative for RSS)

**Source:** https://developers.cloudflare.com/pages/functions/pricing/

- Static asset requests: **free and unlimited** on all plans
- Functions (dynamic): count as Worker requests

You could host a static site on Pages that includes the RSS XML as a static asset, rebuilt daily via CI/CD. Requests to static assets are free and unlimited.

**Pages cost = $0**

But this is overengineering. Just put the RSS XML in R2 alongside the MP3s.

---

## 5. Hidden Costs & Gotchas

### Custom Domain
- **Free** if you use Cloudflare as DNS (which you'd want anyway for R2 custom domains)
- R2 custom domains require the domain to be on Cloudflare DNS
- No additional charge

### SSL/TLS
- **Free.** Cloudflare provides free SSL on all plans, including R2 custom domains.

### R2 "Subscription"
- R2 requires a Cloudflare account (free) and you need to "subscribe" to R2 (also free — it's just enabling the service)
- No credit card required for free tier usage

### Gotchas
1. **r2.dev rate limits:** The default `r2.dev` public URL has rate limiting. For production podcast hosting, use a custom domain.
2. **No CDN caching by default:** R2 serves from a single location. To get global CDN caching, you need to put the custom domain through Cloudflare's CDN (free with Cloudflare DNS). This is automatic when using a custom domain on Cloudflare.
3. **Cache invalidation:** When you update the RSS feed, Cloudflare's cache will serve stale content until TTL expires. Set appropriate `Cache-Control` headers (e.g., `max-age=3600` for the RSS, longer for MP3s which are immutable).
4. **Large file warning:** R2 has a 5 GB max object size via single PUT (300 MB via Workers API). 20 MB MP3s are no problem.
5. **10 GB free tier is per-account**, not per-bucket.

---

## 6. Cost Comparison with Alternatives

### Scenario: Year 1, 1,000 daily listeners
- Storage: 7.2 GB (growing monthly)
- Monthly bandwidth: 600 GB
- Monthly requests: ~90,000

#### Cloudflare R2

| Item | Cost/month |
|---|---|
| Storage (under 10 GB free) | $0.00 |
| Class A ops | $0.00 |
| Class B ops | $0.00 |
| Egress (always free) | $0.00 |
| Custom domain + SSL | $0.00 |
| **Total** | **$0.00** |

#### AWS S3 + CloudFront

| Item | Cost/month |
|---|---|
| S3 storage (~7 GB, $0.023/GB) | $0.16 |
| S3 GET requests (90K × $0.0004/1000) | $0.04 |
| S3 PUT requests (60 × $0.005/1000) | $0.00 |
| CloudFront egress (600 GB × $0.085/GB first 10TB) | $51.00 |
| CloudFront requests (90K × $0.0075/10K) | $0.07 |
| **Total** | **~$51.27** |

Note: AWS has a 1 TB/month free CloudFront tier for the first year. With that: ~$0.20/month year 1. After year 1 free tier expires: ~$51/month.

#### Backblaze B2 + Cloudflare CDN

| Item | Cost/month |
|---|---|
| B2 storage (~7 GB, $0.006/GB) | $0.04 |
| B2 Class B ops (90K, $0.004/10K after 2500 free/day) | ~$0.01 |
| B2 egress to Cloudflare CDN | $0.00 (free via Bandwidth Alliance) |
| Cloudflare CDN (free plan) | $0.00 |
| **Total** | **~$0.05** |

This is the budget runner-up. B2 + Cloudflare's free CDN = nearly free thanks to the Bandwidth Alliance (zero egress from B2 to Cloudflare). You do need to set up Cloudflare as a CDN in front of B2.

#### Bunny.net (CDN + Storage)

| Item | Cost/month |
|---|---|
| Storage (7 GB, single region, $0.01/GB) | $0.07 |
| CDN bandwidth (600 GB × $0.01/GB NA/EU) | $6.00 |
| Minimum monthly charge | $1.00 |
| **Total** | **~$6.07** |

Bunny is cheap, fast, and simple. No egress tricks needed. But not free.

#### VPS with nginx (e.g., Hetzner)

| Item | Cost/month |
|---|---|
| Hetzner CX22 (2 vCPU, 4GB RAM, 40GB disk, 20TB traffic) | €4.35 (~$4.75) |
| Domain + SSL (Let's Encrypt) | $0.00 |
| **Total** | **~$4.75** |

Simple, full control, 20 TB/month included traffic. But you manage the server, updates, security, backups. At 10,000 daily listeners (6 TB/month), still within Hetzner's 20 TB cap.

### Comparison Summary Table

| Provider | 100/day | 1,000/day | 10,000/day |
|---|---|---|---|
| **Cloudflare R2** | $0.00 | $0.00 | $0.00 |
| **B2 + Cloudflare** | ~$0.05 | ~$0.05 | ~$0.05 |
| **Bunny.net** | ~$1.60 | ~$6.07 | ~$60.07 |
| **AWS S3+CF (post yr1)** | ~$5.27 | ~$51.27 | ~$510+ |
| **VPS (Hetzner)** | ~$4.75 | ~$4.75 | ~$4.75 |

Note: R2 stays $0 across all three tiers because egress is free and operations stay under the 10M free tier. The only growing cost is storage over time.

---

## 7. Bottom Line

### Is it actually $0/month for a small podcast?

**Yes.** For a daily podcast with up to ~10,000 listeners/day:
- **Year 1:** $0.00/month (storage under 10 GB free tier, operations well under limits, egress always free)
- **Year 2:** $0.07/month (14.4 GB storage, only 4.4 GB billed)
- **Year 5:** $0.39/month (36 GB storage, 26 GB billed)

### At what scale does it stop being free?

**Storage** is the only cost that grows:
- Free until ~16 months of daily episodes (10 GB)
- Even then, it's pennies — $0.015/GB-month

**Operations** (reads) are the theoretical limit:
- Free tier: 10 million Class B ops/month
- At 20 MB/episode, that's 10 million downloads/month = ~333,000 daily listeners
- Beyond that: $0.36 per million operations = $0.36 per ~33,000 additional downloads
- At 100,000 daily listeners (3M downloads/month): still $0 in operations

**Egress** never costs anything on R2. Period.

### The real breakpoint:

| Scale | Monthly Cost |
|---|---|
| < 333K daily listeners, < 10 GB stored | **$0.00** |
| 333K daily listeners, 50 GB stored | ~$0.60 storage + ~$0 ops = **~$0.60** |
| 1M daily listeners, 100 GB stored | ~$1.35 storage + ~$3.24 ops = **~$4.59** |

You would need a **massively popular podcast** (hundreds of thousands of daily listeners) AND years of archive before R2 costs you more than a few dollars per month.

### Recommendation

**Use Cloudflare R2. It's not even close.**

Setup:
1. Create R2 bucket
2. Attach custom domain (requires Cloudflare DNS — free)
3. Upload MP3s and RSS XML directly to R2
4. Enable public access via custom domain (gets Cloudflare CDN automatically)
5. No Workers needed for basic hosting
6. Optional: Worker for RSS generation, analytics, or redirects (free tier sufficient)

The only scenario where an alternative wins:
- **VPS** if you want full control and run other services on it too
- **B2 + Cloudflare** if you're already invested in Backblaze ecosystem

For pure podcast file hosting, R2's zero-egress model makes it the objectively cheapest option at any scale.
