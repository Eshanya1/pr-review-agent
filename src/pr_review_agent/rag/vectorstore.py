from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .chunking import Chunk


@dataclass
class SearchResult:
    chunk: Chunk
    score: float


class VectorStore:
    """Brute-force cosine similarity over embeddings held in memory.

    A real, embedded vector store (not pgvector -- see README for why: no
    hosted DB to provision, no native SQLite extension to load, works
    identically on a laptop or in a fresh Binder container). At the scale of
    one repo's chunks (hundreds, not millions) brute-force search is fast
    enough that an ANN index would be premature; swapping in pgvector for
    production scale means implementing this same three-method interface
    against a real server, nothing else in the pipeline would change.
    """

    def __init__(self):
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None

    def build(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        self.chunks = chunks
        self.vectors = np.asarray(vectors, dtype=np.float32)

    def search(self, query_vector: np.ndarray, k: int = 5) -> list[SearchResult]:
        if self.vectors is None or len(self.chunks) == 0:
            return []
        sims = self.vectors @ np.asarray(query_vector, dtype=np.float32)
        top = np.argsort(-sims)[:k]
        return [SearchResult(chunk=self.chunks[i], score=float(sims[i])) for i in top]

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        (path / "chunks.json").write_text(json.dumps([c.to_dict() for c in self.chunks]))

    @classmethod
    def load(cls, path: Path) -> "VectorStore":
        store = cls()
        store.vectors = np.load(path / "vectors.npy")
        store.chunks = [Chunk.from_dict(d) for d in json.loads((path / "chunks.json").read_text())]
        return store

    @staticmethod
    def exists(path: Path) -> bool:
        return (path / "vectors.npy").exists() and (path / "chunks.json").exists()
