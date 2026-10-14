"""Local embedding providers. Embeddings are always computed on this machine."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from abc import ABC, abstractmethod

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import EMBED_LATENCY

log = get_logger(__name__)


class Embedder(ABC):
    name: str
    model: str
    dim: int = 384

    @abstractmethod
    def _embed(self, texts: list[str], *, query: bool) -> np.ndarray: ...

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        t0 = time.perf_counter()
        vecs = self._embed(texts, query=query)
        EMBED_LATENCY.labels(self.name).observe(time.perf_counter() - t0)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vecs / norms).astype(np.float32)

    def embed_one(self, text: str, *, query: bool = False) -> list[float]:
        return self.embed([text], query=query)[0].tolist()

    @property
    def model_id(self) -> str:
        return f"{self.name}:{self.model}"


class FastEmbedEmbedder(Embedder):
    """ONNX sentence embeddings (default BAAI/bge-small-en-v1.5, 384-d). No PyTorch, runs offline once cached."""

    name = "fastembed"

    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        self.model = model
        self._m = TextEmbedding(model_name=model, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def _embed(self, texts: list[str], *, query: bool) -> np.ndarray:
        with self._lock:
            if query and hasattr(self._m, "query_embed"):
                return np.array(list(self._m.query_embed(texts)), dtype=np.float32)
            return np.array(list(self._m.embed(texts, batch_size=64)), dtype=np.float32)


class HashingEmbedder(Embedder):
    """Deterministic feature-hashing embedder (word uni/bi-grams + char trigrams, signed hashing).

    Real lexical-semantic vectors with no model download: used offline, in CI, and as the
    'no neural model' baseline in retrieval evaluation. Weaker than a neural model on paraphrase.
    """

    name = "hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.model = f"hash-{dim}"

    def _features(self, text: str) -> list[tuple[str, float]]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        feats: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
        feats += [(f"b:{a}_{b}", 0.7) for a, b in zip(words, words[1:], strict=False)]
        for w in words:
            padded = f"#{w}#"
            feats += [(f"c:{padded[i:i + 3]}", 0.25) for i in range(len(padded) - 2)]
        return feats

    def _embed(self, texts: list[str], *, query: bool) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, t in enumerate(texts):
            for feat, weight in self._features(t):
                h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "little")
                idx, sign = h % self.dim, 1.0 if (h >> 32) & 1 else -1.0
                out[row, idx] += sign * weight
            out[row] = np.sign(out[row]) * np.log1p(np.abs(out[row]))
        return out


class OllamaEmbedder(Embedder):
    """Embeddings from a local Ollama model with 384 dimensions (e.g. all-minilm)."""

    name = "ollama"

    def __init__(self, model: str, base_url: str) -> None:
        from app.ai.llm.ollama import OllamaProvider

        self.model = model
        self._p = OllamaProvider(base_url)

    def _embed(self, texts: list[str], *, query: bool) -> np.ndarray:
        return np.array(self._p.embed(texts, model=self.model), dtype=np.float32)


_embedder: Embedder | None = None
_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    with _lock:
        if _embedder is None:
            s = get_settings()
            if s.embedding_provider == "fastembed":
                try:
                    _embedder = FastEmbedEmbedder(s.embedding_model, s.embedding_cache_dir)
                except Exception as exc:  # model not cached and no network, or fastembed missing
                    log.warning("fastembed_unavailable_falling_back_to_hashing", error=type(exc).__name__)
                    _embedder = HashingEmbedder(s.embedding_dim)
            elif s.embedding_provider == "ollama":
                _embedder = OllamaEmbedder(s.embedding_model, s.ollama_base_url)
            else:
                _embedder = HashingEmbedder(s.embedding_dim)
        return _embedder


def set_embedder(e: Embedder | None) -> None:
    global _embedder
    _embedder = e


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    d = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / d) if d else 0.0


_ = math
