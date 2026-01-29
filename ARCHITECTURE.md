# Carlin Podcast Pipeline Architecture

**Status:** Analysis/Design Phase  
**Last Updated:** 2025-01-27

---

## Overview

A multi-stage pipeline that transforms raw HN articles + comments into 10-story George Carlin podcast episodes. Each stage has explicit context boundaries to manage token budgets.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE FLOW                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  INGEST  │───▶│ RETRIEVE │───▶│ SUMMARIZE│───▶│ CARLINIZE│          │
│  │          │    │          │    │          │    │          │          │
│  │ Articles │    │ Per-story│    │ 5-para   │    │ Final    │          │
│  │ Comments │    │ chunks   │    │ summaries│    │ scripts  │          │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘          │
│       │                                               │                  │
│       ▼                                               ▼                  │
│  ┌──────────┐                                   ┌──────────┐            │
│  │ VECTOR   │                                   │  ORDER   │            │
│  │ DB       │                                   │ 10 stories│            │
│  │ (SQLite) │                                   └────┬─────┘            │
│  └──────────┘                                        │                  │
│                                                      ▼                  │
│                                          ┌───────────────────┐          │
│                                          │ INTERSTITIALS     │          │
│                                          │ (pairwise gen)    │          │
│                                          └─────────┬─────────┘          │
│                                                    │                    │
│                                                    ▼                    │
│                                          ┌───────────────────┐          │
│                                          │ STITCH + TTS      │          │
│                                          │ Final episode     │          │
│                                          └───────────────────┘          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Ingestion & Vector Storage

### Data Sources
- **Articles:** Title, URL, body text (if available), HN score, timestamp
- **Comments:** Threaded structure, author, text, score, timestamp

### Chunking Strategy

**Recommendation: Semantic paragraph chunking with overlap**

| Content Type | Chunk Size | Overlap | Rationale |
|-------------|-----------|---------|-----------|
| Article body | ~500 tokens | 50 tokens | Preserve paragraph coherence |
| Top-level comments | 1 chunk each | None | Comments are self-contained takes |
| Comment threads | ~800 tokens | 100 tokens | Preserve reply context |

**Why NOT fixed-size chunking:**
- Breaks mid-sentence = garbage embeddings
- Comments are naturally atomic units
- Article paragraphs have semantic boundaries

**Chunking Algorithm:**
```python
def chunk_article(text):
    paragraphs = split_on_double_newline(text)
    chunks = []
    current = ""
    for p in paragraphs:
        if token_count(current + p) > 500:
            chunks.append(current)
            current = last_n_tokens(current, 50) + p  # overlap
        else:
            current += p
    return chunks

def chunk_comments(comments):
    # Top-level comments: one chunk each
    # Replies: group with parent up to 800 tokens
    # Store thread_depth for sentiment weighting
```

### Metadata Schema

```json
{
  "chunk_id": "uuid",
  "article_id": "hn_id",
  "chunk_type": "article_body | comment | comment_thread",
  "position": 0,  // chunk order within article
  
  // Article metadata (denormalized for retrieval)
  "article_title": "string",
  "article_url": "string", 
  "article_score": 150,
  "article_timestamp": "2025-01-27T...",
  "article_domain": "techcrunch.com",
  
  // Comment-specific
  "comment_author": "string | null",
  "comment_score": 42,
  "thread_depth": 0,  // 0 = top-level
  "parent_comment_id": "string | null",
  
  // Derived
  "sentiment": "positive | negative | neutral | mixed",
  "sentiment_intensity": 0.7,  // -1 to 1
  "key_entities": ["Apple", "EU", "Tim Cook"],
  "controversy_score": 0.8,  // high = divided opinions
  
  // Embedding
  "embedding": [...]  // 1536-dim for text-embedding-3-small
}
```

### Comment Sentiment Extraction

**Two-pass approach:**

1. **Embedding-time (lightweight):**
   - Use a small classifier or heuristic on each comment
   - Store `sentiment` and `sentiment_intensity` in metadata
   - Fast, runs during ingestion

2. **Retrieval-time (contextual):**
   - When building summary, LLM interprets sentiment in context
   - "The comments were surprisingly supportive despite..."
   - This is where nuance lives

**Heuristic signals for controversy_score:**
- High variance in comment sentiment
- Many replies to top-level comments
- Presence of "[flagged]" or "[dead]" comments
- Ratio of negative:positive top comments

---

## Stage 2: Vector Retrieval → Summaries

### Retrieval Strategy

For each article, retrieve:
1. **All article body chunks** (ordered by position)
2. **Top 10-15 comments by score** (diverse sentiment if possible)
3. **1-2 controversial threads** (high engagement, mixed sentiment)

**Query:** Article title + first paragraph embedding  
**Filter:** `article_id = X`  
**Rerank:** Hybrid of vector similarity + metadata (score, sentiment diversity)

### Summary Generation

**Input context per article:** ~4,000 tokens max
- Article chunks: ~2,000 tokens
- Comment selection: ~1,500 tokens  
- Prompt/instructions: ~500 tokens

**Output:** 5-paragraph structured summary (~800-1000 tokens)

```
Paragraph 1: What happened (factual core)
Paragraph 2: Why it matters (implications, context)
Paragraph 3: The HN reaction (overall sentiment, key takes)
Paragraph 4: The best/funniest/most insightful comments
Paragraph 5: The controversy/debate (if any)
```

**Token Budget:**
- Input: 4,000 tokens × 10 articles = 40,000 tokens
- Output: 1,000 tokens × 10 = 10,000 tokens
- **Total Stage 2:** ~50,000 tokens

---

## Stage 3: Summaries → Carlin Scripts

### Input
- 10 summaries (~10,000 tokens total)
- Carlin voice/style guide (~500 tokens)
- Format instructions (~300 tokens)

### Processing
**Option A: Batch all 10**
- Single call with all summaries
- Pro: Cross-story coherence, can reference earlier bits
- Con: 15K+ input, complex prompt

**Option B: Sequential with memory**
- Process one at a time
- Pass "stories so far" context (titles only)
- Pro: Better individual quality
- Con: More calls, potential drift

**Recommendation: Batch with structure**
- Send all 10 summaries in one call
- Request structured output with clear story boundaries
- Use "Act 1 / Act 2 / Act 3" framing (opening energy, middle, strong closer)

### Output
- 10 Carlin scripts, ~600-800 words each (~700 tokens)
- **Total output:** ~7,000 tokens
- **Total Stage 3:** ~20,000 tokens

---

## Stage 4: Episode Ordering

### The Core Question
How do we arrange 10 stories for maximum engagement?

### Ordering Criteria (weighted)

| Factor | Weight | Rationale |
|--------|--------|-----------|
| **Energy curve** | 30% | Start strong, dip mid, end strongest |
| **Topic variety** | 25% | Don't cluster similar stories |
| **Controversy placement** | 20% | Save spiciest takes for later |
| **Thematic bridges** | 15% | Enable natural transitions |
| **Length balance** | 10% | Alternate long/short |

### Proposed Algorithm

```python
def order_stories(stories):
    # 1. Score each story on dimensions
    for s in stories:
        s.energy = rate_energy(s)        # 1-10, how punchy
        s.controversy = rate_controversy(s)
        s.category = classify_topic(s)   # tech, politics, culture, etc.
        s.length = token_count(s)
        
    # 2. Place anchors
    opener = max(stories, key=lambda s: s.energy * 0.8 + s.accessibility * 0.2)
    closer = max(remaining, key=lambda s: s.controversy * 0.6 + s.energy * 0.4)
    
    # 3. Fill middle with variety constraint
    # No adjacent stories in same category
    # Alternate long/short
    # Build energy toward position 7-8, then dip slightly before closer
    
    # 4. Identify natural transition pairs
    # Stories that share entities, themes, or contrasting angles
```

### Manual Override
Store ordering rationale in metadata so human can review/adjust:
```json
{
  "episode_id": "2025-01-27",
  "ordering": [
    {"story_id": 3, "position": 1, "reason": "High energy opener, accessible topic"},
    {"story_id": 7, "position": 2, "reason": "Contrasts with opener, shared 'regulation' theme"},
    ...
  ]
}
```

---

## Stage 5: Interstitial Generation

### Key Insight
Interstitials need ONLY:
1. Final script of story N (the one we're leaving)
2. Final script of story N+1 (the one we're entering)

**NOT** the summaries. NOT the raw articles. Just the Carlin scripts.

### Context per interstitial
- Story N script: ~700 tokens
- Story N+1 script: ~700 tokens  
- Instructions + style: ~300 tokens
- **Total input:** ~1,700 tokens

### Generation Strategy

```
For each pair (N, N+1):
  Input: last 2 paragraphs of story N, first 2 paragraphs of story N+1
  
  Prompt: "Write a 2-3 sentence Carlin-style transition that:
    - Acknowledges what we just covered (brief callback)
    - Pivots naturally to the next topic
    - Maintains the irreverent tone
    - Feels like a comedian's segue, not a news anchor"
    
  Output: ~50-100 tokens
```

### Interstitial Types
1. **Thematic bridge:** "Speaking of corporate greed..."
2. **Contrast pivot:** "But hey, at least SOMEONE's having a good week..."
3. **Callback setup:** "Remember that AI thing? Well buckle up..."
4. **Palette cleanser:** "Okay, I need to talk about something stupid for a minute..."

### Token Budget
- 9 interstitials × 1,700 input = 15,300 tokens
- 9 × 100 output = 900 tokens
- **Total Stage 5:** ~16,000 tokens

---

## Stage 6: Final Stitching

### Assembly Order
```
1. Cold open (pre-generated, ~30 seconds)
2. Story 1
3. Interstitial 1→2
4. Story 2
...
9. Story 9
10. Interstitial 9→10
11. Story 10
12. Outro (pre-generated, ~30 seconds)
```

### TTS Considerations
- **Pause markers:** Insert [PAUSE:1.5] between segments
- **Emphasis markers:** Store in scripts as *emphasized* or CAPS
- **Music cues:** [MUSIC:intro], [MUSIC:transition], [MUSIC:outro]

### Output Artifacts
```
episode/
├── 2025-01-27/
│   ├── manifest.json       # Full episode metadata
│   ├── scripts/
│   │   ├── story_01.txt
│   │   ├── story_02.txt
│   │   └── ...
│   ├── interstitials/
│   │   ├── trans_01_02.txt
│   │   └── ...
│   ├── audio/
│   │   ├── story_01.wav
│   │   ├── trans_01_02.wav
│   │   └── full_episode.mp3
│   └── metadata/
│       ├── ordering_rationale.json
│       └── source_articles.json
```

---

## Token Budget Summary

| Stage | Input Tokens | Output Tokens | Total | Notes |
|-------|-------------|---------------|-------|-------|
| 1. Ingest | N/A | N/A | — | Embedding costs only |
| 2. Summaries | 40,000 | 10,000 | 50,000 | 10 articles × 4K |
| 3. Carlinize | 15,000 | 7,000 | 22,000 | Batch processing |
| 4. Ordering | 8,000 | 500 | 8,500 | LLM-assisted ordering |
| 5. Interstitials | 15,000 | 900 | 16,000 | 9 transitions |
| 6. Stitch | — | — | — | Assembly only |
| **TOTAL** | **78,000** | **18,400** | **~97,000** | Per episode |

**Cost estimate (Claude 3.5 Sonnet):**
- Input: 78K × $3/1M = $0.23
- Output: 18K × $15/1M = $0.28
- **Total per episode: ~$0.50**

Plus embedding costs (~$0.01 per episode)
Plus TTS costs (ElevenLabs/local)

---

## Open Questions

1. **Vector DB choice:** sqlite-vec vs chromadb vs pgvector?
   - Recommendation: sqlite-vec for simplicity, local-first

2. **Embedding model:** text-embedding-3-small vs local?
   - Recommendation: OpenAI for quality, ~$0.01/episode

3. **Carlin voice fidelity:** How much style guide is enough?
   - Need iterative testing with real samples

4. **Episode length target:** 20 min? 30 min? 45 min?
   - Affects stories per episode and script length

5. **Source diversity:** HN only? Multiple sources?
   - Start with HN, expand later

6. **Update frequency:** Daily? Weekly?
   - Affects freshness vs. production quality tradeoff

---

## Next Steps

1. [ ] Create CLAUDE.md with project conventions
2. [ ] Set up sqlite-vec with schema
3. [ ] Build HN scraper with rate limiting
4. [ ] Test embedding + chunking on sample articles
5. [ ] Iterate on Carlin voice prompt
6. [ ] Build ordering heuristics
7. [ ] Test full pipeline on single episode
