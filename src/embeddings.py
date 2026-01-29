"""
Vector embeddings infrastructure for Carlin Podcast.
Uses LanceDB for storage and local sentence-transformers for embeddings.
Auto-detects MPS (Apple Silicon), CUDA, or CPU.
"""

from pathlib import Path
from typing import Optional
import lancedb

# Constants
PROJECT_ROOT = Path(__file__).parent.parent
VECTORS_DIR = PROJECT_ROOT / "data" / "vectors"
EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
EMBEDDING_DIM = 1024  # BGE-large dimension

# Singleton for model - loaded once, reused across calls
_model = None
_db_connection = None


def _get_device() -> str:
    """Detect best available device: MPS > CUDA > CPU."""
    import torch
    
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _get_model():
    """
    Get the sentence-transformers model (singleton pattern).
    Auto-detects MPS/CUDA/CPU for acceleration.
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        
        device = _get_device()
        print(f"Loading embedding model on {device}...")
        _model = SentenceTransformer(EMBEDDING_MODEL, device=device)
        print(f"Model loaded: {EMBEDDING_MODEL}")
    
    return _model


def get_db() -> lancedb.DBConnection:
    """Get LanceDB connection (singleton), creating directory if needed."""
    global _db_connection
    if _db_connection is None:
        VECTORS_DIR.mkdir(parents=True, exist_ok=True)
        _db_connection = lancedb.connect(str(VECTORS_DIR))
    return _db_connection


def embed_text(text: str) -> list[float]:
    """
    Generate embedding for a single text.
    
    Args:
        text: Text to embed
        
    Returns:
        List of floats (1024 dimensions)
    """
    model = _get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str], show_progress: bool = False) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in a single batch call.
    Much more efficient than calling embed_text() repeatedly.
    
    Args:
        texts: List of texts to embed
        show_progress: Show progress bar for large batches
        
    Returns:
        List of embeddings, same order as input
    """
    if not texts:
        return []
    
    model = _get_model()
    # Batch encode is highly efficient on GPU/MPS
    show_bar = show_progress or len(texts) > 50
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=show_bar)
    return [e.tolist() for e in embeddings]


def search(table: lancedb.table.Table, query: str, top_k: int = 10) -> list[dict]:
    """
    Vector similarity search on a LanceDB table.
    
    Args:
        table: LanceDB table to search
        query: Text query to search for
        top_k: Number of results to return
        
    Returns:
        List of dicts with record data and _distance score
    """
    vector = embed_text(query)
    results = table.search(vector).limit(top_k).to_list()
    return results


if __name__ == "__main__":
    # Quick sanity check
    print(f"Vectors dir: {VECTORS_DIR}")
    print(f"Embedding model: {EMBEDDING_MODEL}")
    print(f"Device: {_get_device()}")
    
    # Test embedding
    test_vec = embed_text("Hello world, this is a test of the George Carlin podcast system.")
    print(f"Test embedding length: {len(test_vec)}")
    print(f"First 5 values: {test_vec[:5]}")
