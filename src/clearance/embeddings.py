"""Embedders: a local ONNX model via fastembed (default), and a deterministic hashing embedder for tests and CI.

Both run on the machine that runs Clearance; no text is sent anywhere to be embedded.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from clearance.config import Settings


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


_TOKEN = re.compile(r"[a-z0-9€$]+(?:[.,'][a-z0-9]+)*")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "the",
        "their",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)


class HashEmbedder:
    """Feature-hashed bag of words and bigrams, L2-normalized. Deterministic, no downloads, good enough for tests:
    texts that share words are close, unrelated texts are near-orthogonal."""

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def name(self) -> str:
        return f"hash-{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def _vector(self, text: str) -> list[float]:
        tokens = [token for token in _TOKEN.findall(text.lower()) if token not in _STOP]
        features = tokens + [f"{a} {b}" for a, b in itertools.pairwise(tokens)]
        vector = np.zeros(self._dim, dtype=np.float64)
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (0.5 if " " in feature else 1.0)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            vector[0] = 1.0
            norm = 1.0
        return [float(x) for x in vector / norm]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FastEmbedEmbedder:
    """BAAI/bge-small-en-v1.5 (384 dimensions, ~67 MB ONNX) on CPU. Downloaded once into the model cache."""

    # bge models are trained with this instruction prefix for queries (not for passages).
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str, cache_dir: Path, threads: int = 4) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._threads = threads
        self._model: object | None = None
        self._lock = threading.Lock()
        self._dim: int | None = None

    @property
    def name(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self.embed_query("dimension probe"))
        return self._dim

    def _load(self) -> object:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(
                    model_name=self._model_name, cache_dir=str(self._cache_dir), threads=self._threads
                )
            return self._model

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.embed(list(texts), batch_size=32)  # type: ignore[attr-defined]
        return [[float(x) for x in vector] for vector in vectors]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        prefix = self.QUERY_PREFIX if "bge-" in self._model_name.lower() else ""
        return self._embed([prefix + text])[0]


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hash":
        return HashEmbedder(384)
    return FastEmbedEmbedder(settings.embedding_model, settings.model_cache_dir, settings.embedding_threads)
