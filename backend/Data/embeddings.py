"""Issue embeddings — Items #27 (similar-incidents) + #28 (post-mortems).

We embed the *resolved* form of each issue (root_cause +
recommendation + description) and store the vector on
``Issue.embedding`` (JSONField list of floats). Similarity search
runs in Python via numpy — fine at MVP scale (few thousand resolved
issues per org). Scaling past ~50K resolved issues per org warrants
a migration to pgvector (tracked in quality backlog Q3.5).

Design decisions:

* **JSONField, not pgvector.** The base Postgres 16 image we ship
  today doesn't have pgvector; the ``pgvector/pgvector:pg16`` image
  does. Rather than force an ops change now, we keep JSONField and
  document the future migration path.
* **OpenAI text-embedding-3-small (1536 dims)** when
  ``OPENAI_API_KEY`` is set. Falls back to a **deterministic hash
  embedding** when the key is missing — tests + zero-cost demos
  don't need real semantic similarity, they need reproducibility.
* **Cosine similarity** in ``find_similar``: canonical for
  text embeddings + cheap in numpy.

Security:

* Text sent to OpenAI is the *resolved* issue text (root_cause +
  recommendation) — user-controlled, so subject to the same PII
  redaction policy as other outbound AI calls (deferred to Q1.5).
  For now, we redact via ``Utils.data_redaction`` before embedding
  when the module is available.
* Embeddings themselves are stored per-org; ``find_similar`` filters
  by ``organisation`` — never cross-org leakage.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


# Dim of both backends — kept aligned so a swap doesn't require a
# re-embed of the whole DB.
EMBEDDING_DIM = 1536


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _redact(text: str) -> str:
    """Scrub PII before sending to a third-party embedding API."""
    try:
        from Utils.data_redaction import DataRedactionService
        redacted, _ = DataRedactionService().redact(text or '')
        return redacted
    except Exception:
        # Redaction is defence-in-depth; embedding must not fail on its absence.
        return text or ''


def _openai_embed(text: str) -> Optional[List[float]]:
    """Real embedding via OpenAI. Returns None on any failure."""
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(
            model='text-embedding-3-small',
            input=_redact(text)[:8000],   # OpenAI cap ~ 8K tokens
        )
        vector = resp.data[0].embedding
        # Sanity — OpenAI text-embedding-3-small is 1536-dim.
        if len(vector) != EMBEDDING_DIM:
            logger.warning(
                'Unexpected embedding dim %d (expected %d); coercing.',
                len(vector), EMBEDDING_DIM,
            )
            vector = list(vector)[:EMBEDDING_DIM] + [0.0] * max(0, EMBEDDING_DIM - len(vector))
        return list(vector)
    except Exception as exc:
        logger.warning('OpenAI embedding failed: %s', exc)
        return None


def _hash_embed(text: str) -> List[float]:
    """Deterministic hash embedding — fallback for tests + no-key demos.

    Produces a reproducible 1536-dim vector from a SHA-256 hash of
    the input. Not semantically meaningful — same text always yields
    the same vector, but similar text does NOT yield similar vectors.
    Useful only for test determinism and "the pipeline runs" demos.
    """
    if not text:
        text = '_empty_'
    seed = hashlib.sha256(text.encode('utf-8')).digest()
    # Expand 32 bytes → 1536 dims by hashing chunks.
    vector: List[float] = []
    for i in range(EMBEDDING_DIM):
        h = hashlib.sha256(seed + i.to_bytes(4, 'little')).digest()
        # Map first 4 bytes to a float in [-1, 1].
        raw = int.from_bytes(h[:4], 'little', signed=True)
        vector.append(raw / (2 ** 31))
    return _l2_normalize(vector)


def _l2_normalize(vector: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_text(text: str) -> Optional[List[float]]:
    """
    Return an embedding vector for ``text`` or ``None`` if embedding
    failed and no fallback ran.

    Tries OpenAI first (real semantic embeddings); falls back to
    the deterministic hash embedding when ``OPENAI_API_KEY`` is
    unset or the API call fails. Always L2-normalised so cosine
    similarity is a dot product.
    """
    if not text or not text.strip():
        return None
    vector = _openai_embed(text)
    if vector is None:
        vector = _hash_embed(text)
    return _l2_normalize(vector)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity of two vectors. Both must be the same
    dimension. Returns 0.0 for zero vectors.

    Uses numpy for speed on any non-trivial vector length.
    """
    try:
        import numpy as np
        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        na = float(np.linalg.norm(va))
        nb = float(np.linalg.norm(vb))
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except Exception:
        # Pure-Python fallback (portable).
        if len(a) != len(b):
            return 0.0
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (na * nb)


def text_for_issue(issue) -> str:
    """
    Assemble the canonical text for embedding an issue.

    Priority: resolved root_cause + recommendation + description +
    component + issue_type. We DELIBERATELY skip raw log content
    (contains request IDs / timestamps / other one-shot noise that
    poisons similarity).
    """
    parts = []
    # The team's confirmed root cause and fix win over the AI's.
    root = ((getattr(issue, 'resolution_root_cause', '') or '').strip()
            or (getattr(issue, 'root_cause', '') or '').strip())
    if root:
        parts.append(f'Root cause: {root}')
    rec = ((getattr(issue, 'resolution_fix', '') or '').strip()
           or (getattr(issue, 'recommendation', '') or '').strip())
    if rec:
        parts.append(f'Recommendation: {rec}')
    desc = (getattr(issue, 'description', '') or '').strip()
    if desc:
        parts.append(f'Description: {desc[:500]}')
    component = (getattr(issue, 'component', '') or '').strip()
    if component:
        parts.append(f'Component: {component}')
    itype = (getattr(issue, 'issue_type', '') or '').strip()
    if itype:
        parts.append(f'Type: {itype}')
    return '\n'.join(parts)
