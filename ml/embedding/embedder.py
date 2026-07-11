"""Embedding module for semantic analysis.

Wraps sentence-transformers (bge-small-zh-v1.5) to encode text into vectors.
Supports both single-message and whole-window embeddings.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODEL_CACHE_DIR = Path(__file__).parent.parent / "models" / "bge-small-zh-v1.5"


class Embedder:
    """Sentence embedding wrapper using bge-small-zh-v1.5."""

    def __init__(self, model_name: str = MODEL_NAME, cache_dir: Path = MODEL_CACHE_DIR):
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = None

    def _load_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required. "
                "Install with: pip install sentence-transformers"
            )
        print(f"Loading embedding model: {self.model_name}")
        self._model = SentenceTransformer(
            self.model_name,
            cache_folder=str(self.cache_dir),
        )
        return self._model

    def encode(self, texts: str | List[str], batch_size: int = 32) -> np.ndarray:
        """Encode text(s) into embedding vectors.

        Args:
            texts: single string or list of strings
            batch_size: batch size for encoding

        Returns:
            numpy array of shape (n_texts, embedding_dim)
            For single text input, shape is (embedding_dim,)
        """
        model = self._load_model()
        is_single = isinstance(texts, str)
        if is_single:
            texts = [texts]

        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings[0] if is_single else embeddings

    def encode_window(self, messages: list[dict], pool: str = "mean") -> np.ndarray:
        """Encode a full conversation window into a single vector.

        Args:
            messages: list of message dicts with "role" and "content"
            pool: pooling strategy - "mean" (average all messages)
                  or "her_mean" (average only her messages)

        Returns:
            embedding vector of shape (embedding_dim,)
        """
        if pool == "her_mean":
            texts = [m["content"] for m in messages if m.get("role") == "her"]
        else:
            texts = [m["content"] for m in messages]

        if not texts:
            # Return zero vector if no text
            model = self._load_model()
            dim = model.get_sentence_embedding_dimension()
            return np.zeros(dim)

        embeddings = self.encode(texts)
        return np.mean(embeddings, axis=0)


# Singleton for convenience
_default_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = Embedder()
    return _default_embedder
