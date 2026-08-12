"""Embeddings behind one interface, so the model is a deployment choice.

Three backends. Each declares its own dimension -- they are NOT interchangeable.

    bedrock   Amazon Titan Text Embeddings V2. The production path, and what
              makes AWS load-bearing rather than decorative.
    local     sentence-transformers all-MiniLM-L6-v2. No network, no account.
    hash      Deterministic pseudo-embedding. Tests and CI only -- it has no
              semantics, so it must never be the default anywhere.

Why an interface rather than just calling Bedrock: so the engine, the evals and
the demo all run with no AWS account at all. That mattered while the account was
being set up, and it still matters for anyone cloning this repo.

Titan V2 accepts 256, 512 or 1024 -- it REJECTS 384, which is MiniLM's native
size and was this project's original dimension. Measured against the live API,
not assumed. So 512 is canonical and MiniLM is no longer dimension-compatible.

Each backend therefore declares its own `dim`, and the engine refuses to write
into a table built for a different one. Embeddings from different models are not
comparable; padding or truncating one to fit the other would keep the code
running while making every distance in the table meaningless. A loud failure is
the only safe behaviour here.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from functools import lru_cache

import numpy as np

DIM = 512  # Titan V2 accepts 256/512/1024 only -- 384 is REJECTED


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


class Embedder(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed(self, text: str) -> np.ndarray: ...

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        return [self.embed(t) for t in texts]


class HashEmbedder(Embedder):
    """Deterministic, semantics-free. For tests that exercise plumbing only."""

    name = "hash"
    dim = DIM

    def embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        return _unit(np.random.default_rng(seed).normal(size=self.dim))


class LocalEmbedder(Embedder):
    """all-MiniLM-L6-v2, 384-dim natively. Runs offline."""

    name = "local:all-MiniLM-L6-v2"
    dim = 384          # native; NOT interchangeable with Titan's 512

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def embed(self, text: str) -> np.ndarray:
        return _unit(np.asarray(self._model.encode(text), dtype=np.float64))

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        out = self._model.encode(texts)
        return [_unit(np.asarray(v, dtype=np.float64)) for v in out]


class BedrockEmbedder(Embedder):
    """Amazon Titan Text Embeddings V2 at 512 dims."""

    name = "bedrock:amazon.titan-embed-text-v2:0"
    dim = DIM
    MODEL_ID = "amazon.titan-embed-text-v2:0"

    def __init__(self, region: str | None = None) -> None:
        import boto3

        self._client = boto3.client(
            "bedrock-runtime", region_name=region or os.environ.get("AWS_REGION", "us-east-1")
        )

    def embed(self, text: str) -> np.ndarray:
        import json

        resp = self._client.invoke_model(
            modelId=self.MODEL_ID,
            body=json.dumps({"inputText": text, "dimensions": self.dim, "normalize": True}),
        )
        vec = json.loads(resp["body"].read())["embedding"]
        if len(vec) != self.dim:
            raise ValueError(f"Titan returned {len(vec)} dims, expected {self.dim}")
        return _unit(np.asarray(vec, dtype=np.float64))


@lru_cache(maxsize=1)
def get_embedder(backend: str | None = None) -> Embedder:
    """Resolve the backend. Explicit arg > RETRACT_EMBEDDER env > auto-detect.

    Auto-detect prefers bedrock, falls back to local, and NEVER falls back to
    hash: a silent drop to semantics-free vectors would make every distance in
    the table meaningless while everything still appeared to work.
    """
    choice = backend or os.environ.get("RETRACT_EMBEDDER", "auto")

    if choice == "hash":
        return HashEmbedder()
    if choice == "local":
        return LocalEmbedder()
    if choice == "bedrock":
        return BedrockEmbedder()

    if choice != "auto":
        raise ValueError(f"unknown embedder backend: {choice!r}")

    try:
        e = BedrockEmbedder()
        e.embed("warmup")  # prove access now, not on the first real write
        return e
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        print(f"[embed] bedrock unavailable ({type(exc).__name__}), using local model")
        return LocalEmbedder()
