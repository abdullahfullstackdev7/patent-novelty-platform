"""Local embedding and reranking models (CPU) behind small protocols so tests can fake them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np

from app.config import Settings, get_settings

# Recommended by the BGE authors for short queries against passages.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def encode_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray: ...


class Reranker(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


class SentenceTransformerEmbedder:
    """bge-small-en-v1.5 by default. Vectors are L2-normalized so cosine equals dot product."""

    def __init__(
        self,
        settings: Settings | None = None,
        batch_size: int = 64,
        max_seq_length: int = 512,
    ) -> None:
        self._settings = settings or get_settings()
        self._batch_size = batch_size
        self._max_seq_length = max_seq_length
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._settings.embedding_model, device="cpu")
            self._model.max_seq_length = self._max_seq_length
        return self._model

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self.model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.astype(np.float32)

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode([QUERY_INSTRUCTION + t for t in texts])


class CrossEncoderReranker:
    """cross-encoder/ms-marco-MiniLM-L-6-v2. Scores are raw logits, higher is better."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._settings.reranker_model, max_length=512, device="cpu")
        return self._model

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        scores = self.model.predict(
            [(query, doc) for doc in documents], batch_size=16, show_progress_bar=False
        )
        return [float(s) for s in scores]
