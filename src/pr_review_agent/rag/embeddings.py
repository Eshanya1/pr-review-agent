from __future__ import annotations

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class LocalEmbedder:
    """Real dense embeddings computed locally -- no API key, no per-call cost.

    Lazily imports sentence-transformers so the base package (and CI's
    editable/regular-install jobs, which don't touch RAG) never pays for the
    torch dependency unless a rag command is actually run. Install with the
    `rag` extra: pip install -e ".[rag]".
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "RAG features need the 'rag' extra: pip install -e \".[rag]\" "
                "(pulls in sentence-transformers for local embeddings)."
            ) from exc
        self.model = SentenceTransformer(model_name)
        self.dimensions = self.model.get_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )
