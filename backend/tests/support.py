"""Offline fake models shared by tests."""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence

import numpy as np

from app.config import EMBEDDING_DIM


class FakeEmbedder:
    """Hashed bag of words. Texts that share words get similar vectors, so tests are semantic
    enough without downloading a model."""

    def _vec(self, value: str) -> np.ndarray:
        vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        for token in re.findall(r"[a-z][a-z0-9]{2,}", value.lower()):
            digest = zlib.crc32(token.encode())
            vector[digest % EMBEDDING_DIM] += 1.0 if (digest >> 16) & 1 else -1.0
            vector[(digest >> 8) % EMBEDDING_DIM] += 0.5
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray:
        return np.vstack([self._vec(t) for t in texts])

    encode_queries = encode_documents


class FakeReranker:
    """Fraction of query words found in the document."""

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        words = set(re.findall(r"[a-z]{4,}", query.lower()))
        return [
            len(words & set(re.findall(r"[a-z]{4,}", doc.lower()))) / max(len(words), 1)
            for doc in documents
        ]
