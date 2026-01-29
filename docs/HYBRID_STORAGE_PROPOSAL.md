# Hybrid Storage Architecture for Carlin Podcast

## Executive Summary

A two-layer storage system that combines:
1. **Archive Layer**: Raw HTML/content preservation using WARC or simplified gzip files
2. **Vector Layer**: Extracted text + embeddings in LanceDB for semantic search

The key insight: **store raw content for posterity, extracted text for embeddings, and link them with consistent IDs**.

---

## Research Findings

### WARC Format (ISO 28500)

**Pros:**
- Industry standard for web archiving (Internet Archive, national libraries)
- Self-documenting: includes HTTP headers, timestamps, metadata
- `warcio` Python library is excellent - 100 lines to read/write
- Streaming design: can append indefinitely without rewriting
- Built-in support for requests AND responses
- gzip compression is standard

**Cons:**
- Overkill for our use case (we scrape ~10 articles/day, not billions)
- Random access is O(n) without an index (need separate lookup file)
- Tooling expects you to replay whole archives, not retrieve single records
- Format complexity (record types: warcinfo, request, response, metadata, etc.)

**warcio usage example:**
```python
from warcio.capture_http import capture_http
import requests

# Capture HTTP traffic directly to WARC
with capture_http('archive.warc.gz'):
    requests.get('https://example.com/article')
```

### Simpler Alternative: Gzipped File Store

For our scale (~10-50 articles/day), a simpler approach works well:

```
data/
├── archive/
│   ├── 2025-01/
│   │   ├── abc123.html.gz     # Raw HTML
│   │   └── abc123.meta.json   # Metadata (URL, fetch time, headers)
│   └── 2025-02/
└── vectors/                    # LanceDB
```

**Pros:**
- Dead simple: gzip + filesystem
- O(1) lookup by ID
- Easy to inspect/debug
- Can migrate to WARC later if needed

**Cons:**
- No HTTP headers unless we store them separately
- Not a standard format (can't use WARC tools)

### Recommended: Hybrid WARC + Index

Best of both worlds: use WARC for storage, but maintain a fast lookup index.

---

## Proposed Architecture

### Directory Structure

```
dtfhn/
├── data/
│   ├── vectors/                    # LanceDB (existing)
│   │   └── articles.lance/
│   ├── archive/                    # NEW: Raw content archive
│   │   ├── warc/
│   │   │   ├── 2025-01.warc.gz    # Monthly WARC files
│   │   │   └── 2025-02.warc.gz
│   │   └── index.db               # SQLite index for O(1) lookups
│   └── extracted/                  # NEW: Extracted text cache
│       └── text/
│           ├── abc123.txt         # Plain text (for re-embedding)
│           └── def456.txt
```

### Schema Design

#### 1. LanceDB Articles Table (enhanced)

```python
ARTICLES_SCHEMA = pa.schema([
    pa.field("id", pa.string()),              # Unique article ID (e.g., HN-12345)
    pa.field("title", pa.string()),           # Article title
    pa.field("url", pa.string()),             # Source URL
    pa.field("content", pa.string()),         # Extracted text for embeddings
    pa.field("comments_json", pa.string()),   # JSON-serialized comments
    pa.field("date", pa.string()),            # ISO date when stored
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
    
    # NEW fields for archive linking
    pa.field("archive_file", pa.string()),    # e.g., "2025-01.warc.gz"
    pa.field("archive_offset", pa.int64()),   # Byte offset in WARC file
    pa.field("archive_length", pa.int64()),   # Record length in bytes
    pa.field("content_hash", pa.string()),    # SHA256 of raw HTML (dedup)
    pa.field("fetch_status", pa.string()),    # "full", "full_js", "title_only"
    pa.field("embedding_model", pa.string()), # e.g., "bge-large-en-v1.5"
])
```

#### 2. SQLite Archive Index (fast lookups)

```sql
CREATE TABLE archive_index (
    id TEXT PRIMARY KEY,              -- Same as LanceDB article ID
    url TEXT NOT NULL,
    fetch_time TEXT NOT NULL,         -- ISO timestamp
    warc_file TEXT NOT NULL,          -- Filename
    warc_offset INTEGER NOT NULL,     -- Byte offset for seeking
    warc_length INTEGER NOT NULL,     -- Record length
    content_hash TEXT,                -- SHA256 of response body
    http_status INTEGER,              -- HTTP response code
    content_type TEXT,                -- MIME type
    raw_size INTEGER,                 -- Uncompressed size
    compressed_size INTEGER           -- Size in WARC
);

CREATE INDEX idx_url ON archive_index(url);
CREATE INDEX idx_hash ON archive_index(content_hash);
CREATE INDEX idx_time ON archive_index(fetch_time);
```

#### 3. WARC Record Structure

Each article gets 2-3 WARC records:
1. **response**: Full HTTP response (headers + HTML body)
2. **request**: Original HTTP request (for replay)
3. **metadata** (optional): Our custom metadata JSON

```
WARC/1.1
WARC-Type: response
WARC-Record-ID: <urn:uuid:abc123-...>
WARC-Target-URI: https://example.com/article
WARC-Date: 2025-01-27T19:20:00Z
WARC-Payload-Digest: sha256:abc123...
Content-Type: application/http;msgtype=response
Content-Length: 12345

HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
...

<!DOCTYPE html>...
```

---

## Implementation Plan

### Phase 1: Archive Storage Module

```python
# src/archive.py
"""
Archive storage for raw HTML/content.
Uses WARC format with SQLite index for O(1) lookups.
"""

import gzip
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from warcio import WARCWriter, ArchiveIterator
from warcio.statusandheaders import StatusAndHeaders

PROJECT_ROOT = Path(__file__).parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "data" / "archive"
WARC_DIR = ARCHIVE_DIR / "warc"
INDEX_DB = ARCHIVE_DIR / "index.db"


class ArchiveStore:
    """Write and retrieve raw web content from WARC files."""
    
    def __init__(self):
        self._ensure_dirs()
        self._init_db()
        self._current_warc = None
        self._current_warc_path = None
    
    def _ensure_dirs(self):
        WARC_DIR.mkdir(parents=True, exist_ok=True)
    
    def _init_db(self):
        """Initialize SQLite index database."""
        conn = sqlite3.connect(INDEX_DB)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS archive_index (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                fetch_time TEXT NOT NULL,
                warc_file TEXT NOT NULL,
                warc_offset INTEGER NOT NULL,
                warc_length INTEGER NOT NULL,
                content_hash TEXT,
                http_status INTEGER,
                content_type TEXT,
                raw_size INTEGER,
                compressed_size INTEGER
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_url ON archive_index(url)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_hash ON archive_index(content_hash)')
        conn.commit()
        conn.close()
    
    def _get_warc_writer(self) -> Tuple[WARCWriter, Path]:
        """Get WARC writer for current month's file."""
        month = datetime.now().strftime("%Y-%m")
        warc_path = WARC_DIR / f"{month}.warc.gz"
        
        if self._current_warc_path != warc_path:
            if self._current_warc:
                self._current_warc.close()
            
            # Open in append mode
            fh = gzip.open(warc_path, 'ab')
            self._current_warc = WARCWriter(fh, gzip=False)  # Already gzipped
            self._current_warc_path = warc_path
            self._current_fh = fh
        
        return self._current_warc, self._current_warc_path
    
    def store(
        self,
        id: str,
        url: str,
        html_content: bytes,
        http_status: int = 200,
        content_type: str = "text/html",
        http_headers: Optional[dict] = None,
    ) -> dict:
        """
        Store raw HTML content in WARC archive.
        
        Returns dict with archive metadata (for storing in LanceDB).
        """
        writer, warc_path = self._get_warc_writer()
        
        # Calculate hash for deduplication
        content_hash = hashlib.sha256(html_content).hexdigest()
        
        # Check for duplicate
        conn = sqlite3.connect(INDEX_DB)
        existing = conn.execute(
            'SELECT id FROM archive_index WHERE content_hash = ?',
            (content_hash,)
        ).fetchone()
        
        if existing:
            # Content already archived, just return reference
            conn.close()
            return {
                "archive_file": warc_path.name,
                "archive_offset": -1,  # Use existing
                "archive_length": 0,
                "content_hash": content_hash,
                "deduplicated": True,
                "original_id": existing[0],
            }
        
        # Get current position before writing
        offset = self._current_fh.tell()
        
        # Build HTTP response headers
        headers_list = [
            (k, v) for k, v in (http_headers or {}).items()
        ]
        if not any(h[0].lower() == 'content-type' for h in headers_list):
            headers_list.append(('Content-Type', content_type))
        
        status_headers = StatusAndHeaders(
            f'{http_status} OK',
            headers_list,
            protocol='HTTP/1.1'
        )
        
        # Write WARC record
        record = writer.create_warc_record(
            url,
            'response',
            payload=io.BytesIO(html_content),
            http_headers=status_headers,
            length=len(html_content),
        )
        writer.write_record(record)
        
        # Calculate length
        length = self._current_fh.tell() - offset
        
        # Index the record
        conn.execute('''
            INSERT INTO archive_index 
            (id, url, fetch_time, warc_file, warc_offset, warc_length, 
             content_hash, http_status, content_type, raw_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            id, url, datetime.now().isoformat(), warc_path.name,
            offset, length, content_hash, http_status, content_type,
            len(html_content)
        ))
        conn.commit()
        conn.close()
        
        return {
            "archive_file": warc_path.name,
            "archive_offset": offset,
            "archive_length": length,
            "content_hash": content_hash,
            "deduplicated": False,
        }
    
    def retrieve(self, id: str) -> Optional[bytes]:
        """Retrieve raw HTML content by article ID."""
        conn = sqlite3.connect(INDEX_DB)
        row = conn.execute(
            'SELECT warc_file, warc_offset, warc_length FROM archive_index WHERE id = ?',
            (id,)
        ).fetchone()
        conn.close()
        
        if not row:
            return None
        
        warc_file, offset, length = row
        warc_path = WARC_DIR / warc_file
        
        with gzip.open(warc_path, 'rb') as fh:
            fh.seek(offset)
            chunk = fh.read(length)
        
        # Parse WARC record to extract payload
        for record in ArchiveIterator(io.BytesIO(chunk)):
            if record.rec_type == 'response':
                return record.content_stream().read()
        
        return None
    
    def get_by_url(self, url: str) -> Optional[dict]:
        """Look up archive record by URL."""
        conn = sqlite3.connect(INDEX_DB)
        row = conn.execute(
            'SELECT * FROM archive_index WHERE url = ? ORDER BY fetch_time DESC LIMIT 1',
            (url,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    
    def close(self):
        """Close current WARC file."""
        if self._current_warc:
            self._current_fh.close()
            self._current_warc = None
```

### Phase 2: Integrate with Existing Storage

```python
# Update src/storage.py

def store_article_with_archive(
    id: str,
    title: str,
    url: str,
    content: str,           # Extracted text
    raw_html: bytes,        # Raw HTML for archive
    comments: Optional[list[dict]] = None,
    fetch_status: str = "full",
) -> None:
    """
    Store article in both vector DB and archive.
    """
    from .archive import ArchiveStore
    
    # Store raw HTML in archive
    archive = ArchiveStore()
    archive_meta = archive.store(id, url, raw_html)
    archive.close()
    
    # Store in vector DB with archive link
    table = get_articles_table()
    
    embed_text_content = f"{title}\n\n{content}"
    vector = embed_text(embed_text_content)
    
    table.add([{
        "id": id,
        "title": title,
        "url": url,
        "content": content,
        "comments_json": json.dumps(comments or []),
        "date": datetime.now().isoformat(),
        "vector": vector,
        # Archive linking
        "archive_file": archive_meta["archive_file"],
        "archive_offset": archive_meta["archive_offset"],
        "archive_length": archive_meta["archive_length"],
        "content_hash": archive_meta["content_hash"],
        "fetch_status": fetch_status,
        "embedding_model": EMBEDDING_MODEL,
    }])
```

### Phase 3: Re-embedding Support

```python
# src/reembed.py
"""
Rebuild embeddings when model changes.
Uses archived raw content or extracted text cache.
"""

def rebuild_embeddings(new_model: str = None):
    """
    Rebuild all embeddings with a new model.
    
    Steps:
    1. Load all articles from LanceDB (without vectors)
    2. Re-extract text from archive if needed
    3. Generate new embeddings
    4. Update LanceDB records
    """
    from .embeddings import embed_batch, EMBEDDING_MODEL
    from .storage import get_articles_table
    
    model = new_model or EMBEDDING_MODEL
    table = get_articles_table()
    
    # Get all articles
    articles = table.to_arrow().to_pylist()
    
    print(f"Re-embedding {len(articles)} articles with {model}...")
    
    # Extract texts
    texts = [f"{a['title']}\n\n{a['content']}" for a in articles]
    
    # Batch embed
    vectors = embed_batch(texts, show_progress=True)
    
    # Update records (LanceDB supports upsert)
    for article, vector in zip(articles, vectors):
        article['vector'] = vector
        article['embedding_model'] = model
    
    # Recreate table with new data
    # (LanceDB doesn't have in-place update, so we rebuild)
    db = get_db()
    db.drop_table("articles")
    new_table = db.create_table("articles", articles, schema=ARTICLES_SCHEMA)
    
    print(f"Done. {len(articles)} articles re-embedded.")
```

---

## Storage Considerations

### Compression

| Format | Ratio | Speed | Random Access |
|--------|-------|-------|---------------|
| WARC.gz | ~10:1 | Fast | Need index |
| Zstandard | ~12:1 | Faster | Need index |
| LZ4 | ~5:1 | Fastest | Need index |

**Recommendation**: gzip for WARC (standard), zstd for extracted text cache.

### Storage Estimates (1 year)

Assuming ~20 articles/day, average 50KB raw HTML:
- Raw WARC: 20 × 50KB × 365 ÷ 10 = **36 MB/year** (compressed)
- Extracted text: 20 × 5KB × 365 = **36 MB/year**
- Embeddings: 20 × 4KB × 365 = **29 MB/year** (1024 × float32)
- **Total: ~100 MB/year** (trivial for local storage)

### Where to Store

For this scale: **local filesystem is fine**.

Future options if scaling:
- Object storage (S3/R2) for WARC files
- Keep SQLite index + LanceDB local for fast queries

---

## Retrieval Patterns

### 1. Semantic Search (existing)

```python
results = search_articles("AI safety concerns", top_k=10)
# Returns articles with content, ready for script generation
```

### 2. Retrieve Original HTML

```python
archive = ArchiveStore()
html = archive.retrieve(article_id)
# Returns raw bytes, useful for:
# - Re-extracting with different parser
# - Debugging extraction issues
# - Legal/archival purposes
```

### 3. Re-process from Archive

```python
# If extraction algorithm improves:
archive = ArchiveStore()
for article_id in get_all_article_ids():
    raw_html = archive.retrieve(article_id)
    new_text = improved_extractor(raw_html)
    update_article_content(article_id, new_text)
    # Re-embed
```

### 4. Deduplicate by Content

```python
# Check if we already have this content
archive = ArchiveStore()
if archive.get_by_hash(content_hash):
    print("Already archived, skipping")
```

---

## Integration Summary

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   Scraper    │────▶│  Archive Store  │────▶│  WARC Files  │
│              │     │  (raw HTML)     │     │  + Index DB  │
└──────────────┘     └────────┬────────┘     └──────────────┘
                              │
                              │ archive_file
                              │ archive_offset
                              ▼
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│  Extractor   │────▶│  Vector Store   │────▶│   LanceDB    │
│  (text out)  │     │  (embeddings)   │     │              │
└──────────────┘     └─────────────────┘     └──────────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │ Script Generator│
                     │ (semantic search)│
                     └─────────────────┘
```

---

## Migration Path

1. **Start simple**: Store raw HTML alongside extraction (gzip files)
2. **Add WARC**: When you want HTTP headers/timestamps preserved
3. **Add S3**: When local storage becomes inconvenient
4. **Full archive**: Consider Internet Archive's Heritrix if you need crawling

---

## Alternatives Considered

### 1. Just Store in LanceDB

Store raw HTML as a blob field in LanceDB.

**Rejected because:**
- LanceDB optimized for vector search, not blob storage
- Can't stream/append efficiently
- No compression at row level

### 2. SQLite Only

Store everything in SQLite with FTS5 for search.

**Rejected because:**
- No semantic search (just keyword matching)
- Would need to bolt on vector search anyway

### 3. Pure WARC (no index)

Just write WARC files, scan to find records.

**Rejected because:**
- O(n) lookups are slow
- Need to read entire archive to find one article

---

## Conclusion

The proposed architecture gives you:

1. ✅ **Preservation**: Raw HTML in standard WARC format
2. ✅ **Fast search**: LanceDB for semantic similarity
3. ✅ **Deduplication**: Content hashing prevents duplicates
4. ✅ **Flexibility**: Can re-extract/re-embed anytime
5. ✅ **Simplicity**: ~200 lines of new code
6. ✅ **Scale-appropriate**: Local filesystem for years of content

Start with the simplified gzip approach (Phase 1), add WARC later if you need the HTTP headers/replay capability.
