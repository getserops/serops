"""Issue embeddings — Items #27 (similar-incidents) + #28 (post-mortems).

We embed the *resolved* form of each issue (root_cause +
recommendation + description) and store the vector on
``Issue.embedding`` (JSONField list of floats) together with the
model that produced it on ``Issue.embedding_model``. Similarity search
runs in Python — fine at MVP scale (few thousand resolved issues per
org). Scaling past ~50K resolved issues per org warrants a migration
to pgvector (tracked in quality backlog Q3.5).

Two modes, and the stored ``embedding_model`` always says which one
produced a vector:

* **Provider mode** (``"<provider>:<model>"``, e.g.
  ``"openai:text-embedding-3-small"``). Uses the *organisation's own*
  AI provider from Settings → AI Providers — the default provider
  first, then the fallback — when that provider offers an embeddings
  API: OpenAI, Google Gemini, Ollama, or any other OpenAI-compatible
  endpoint. Anthropic Claude and DeepSeek have no embeddings API and
  are skipped. The model can be overridden per provider key with
  ``extra_config["embedding_model"]`` (Ollama needs an embedding model
  pulled, ``nomic-embed-text`` by default).
* **Lexical mode** (``LEXICAL_MODEL``). Deterministic, local,
  dependency-free: hashed word unigrams + bigrams + character
  4-grams, sublinear TF, L2-normalised. Similar wording gives similar
  vectors, so "similar past incidents" works for keyless, air-gapped
  and Claude/DeepSeek-only installs too.

External review (v1.2.13): this module used to read a global
``OPENAI_API_KEY`` env var — contradicting the README's "AI keys are
never read from the environment" — and fell back to a SHA-256 hash
whose vectors were random, so similar text never matched for anyone
without that env var (Ollama and air-gapped users included). The env
var is no longer read at all.

Vectors from different models (or dimensions) are never compared to
each other: ``vectors_comparable`` gates every comparison, and callers
fall back to lexical similarity computed on the fly from the text.

Security:

* Text sent to a provider is redacted via ``Utils.data_redaction``
  first — same policy as other outbound AI calls.
* Embeddings are stored per-org; ``find_similar`` filters by
  ``organisation`` — never cross-org leakage.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Lexical-mode identity. Bump the version whenever the feature recipe
# below changes: stored lexical vectors with an older id are then
# treated as a different model and recomputed on the fly instead of
# compared against new ones.
LEXICAL_MODEL = 'lexical-ngram-v1'
LEXICAL_DIM = 1024

# Minimum cosine for "this is the same kind of incident". The two
# modes live on different scales: dense semantic models put related
# RCA text around 0.75+, while sparse lexical vectors score paraphrased
# incidents ~0.5-0.75 and unrelated incidents below ~0.1 (calibrated on
# RCA-style samples, see Data/tests/test_embeddings_lexical.py).
SEMANTIC_MIN_SIMILARITY = 0.75
LEXICAL_MIN_SIMILARITY = 0.25

# Provider HTTP budget: embedding is an enrichment, never worth
# holding a request or a Celery worker for long.
_PROVIDER_TIMEOUT_SECONDS = 10

# Default embedding model per provider. Providers missing here (claude,
# deepseek) have no embeddings API; unknown custom providers that use
# the OpenAI-compatible adapter are tried with an explicit
# ``extra_config["embedding_model"]`` only.
_DEFAULT_EMBEDDING_MODELS = {
    'openai': 'text-embedding-3-small',
    'gemini': 'gemini-embedding-001',
    'ollama': 'nomic-embed-text',
}
_NO_EMBEDDINGS_API = frozenset({'claude', 'anthropic', 'deepseek'})

_OPENAI_COMPATIBLE_ADAPTER = 'ai_model.adapters.openai_generic.GenericOpenAIAdapter'
_GEMINI_ADAPTER = 'ai_model.adapters.gemini.GeminiAdapter'


@dataclass(frozen=True)
class Embedding:
    vector: List[float]
    model: str

    @property
    def is_lexical(self) -> bool:
        return self.model == LEXICAL_MODEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact(text: str) -> str:
    """Scrub PII before sending to a third-party embedding API.

    Fails closed: this used to return the original text when redaction
    raised, sending it to OpenAI unscanned (external review, v1.2.13). It
    now raises, ``_provider_embed`` returns None, and ``embed_text`` falls
    back to the local lexical embedding — nothing leaves the process.
    """
    from Utils.redaction_helpers import redact_for_ai
    return redact_for_ai(text or '')


def _l2_normalize(vector: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return list(vector)
    return [v / norm for v in vector]


# ---------------------------------------------------------------------------
# Lexical mode
# ---------------------------------------------------------------------------

# Words that carry no incident signal, plus the section labels
# ``text_for_issue`` writes into every issue's text — left in, they made
# any two issues look alike.
_STOPWORDS = frozenset('''
a an and are as at be been being but by can could did do does for from had
has have how i if in into is it its may might no not of on or our out over
so such than that the their them then there these they this to too under up
was we were what when where which while who why will with would you your
root cause recommendation description component type fix error issue
'''.split())

_CAMEL_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
_NON_WORD_RE = re.compile(r'[^a-z0-9]+')
_HEXISH_RE = re.compile(r'^[0-9a-f]{6,}$')


def _tokens(text: str) -> List[str]:
    """Lowercased content words. Splits camelCase / snake_case so
    ``ConnectionPoolTimeout`` and ``connection_pool timeout`` agree, and
    drops numbers, hex ids and UUID fragments — one-shot noise that
    differs between otherwise identical incidents."""
    text = _CAMEL_RE.sub(' ', text or '').lower()
    out = []
    for tok in _NON_WORD_RE.split(text):
        if len(tok) < 2 or tok in _STOPWORDS:
            continue
        if tok.isdigit() or _HEXISH_RE.match(tok):
            continue
        if sum(c.isdigit() for c in tok) * 2 > len(tok):
            continue
        out.append(tok)
    return out


def _bucket(feature: str) -> tuple:
    """Stable (index, sign) for a feature — the signed hashing trick.
    ``blake2b`` rather than ``hash()``: Python's string hash is salted
    per process, which would make stored vectors incomparable."""
    digest = hashlib.blake2b(feature.encode('utf-8'), digest_size=8).digest()
    value = int.from_bytes(digest, 'little')
    return value % LEXICAL_DIM, (1.0 if (value >> 63) & 1 else -1.0)


def _lexical_features(text: str) -> Dict[str, float]:
    tokens = _tokens(text)
    feats: Counter = Counter()
    for tok in tokens:
        feats['w:' + tok] += 1.0
        # Char 4-grams give stemming for free: "exhausted" / "exhaustion",
        # "timeout" / "timeouts" share most of their grams.
        padded = f'<{tok}>'
        for i in range(len(padded) - 3):
            feats['c:' + padded[i:i + 4]] += 0.25
    for a, b in zip(tokens, tokens[1:]):
        feats[f'b:{a} {b}'] += 0.5
    return feats


def lexical_embed(text: str) -> List[float]:
    """Deterministic, local lexical vector for ``text`` (lexical mode).

    Similar wording → high cosine; unrelated text → near zero. No
    network, no model download, same output on every machine.
    """
    vector = [0.0] * LEXICAL_DIM
    for feature, tf in _lexical_features(text).items():
        idx, sign = _bucket(feature)
        vector[idx] += sign * (1.0 + math.log(tf)) if tf >= 1 else sign * tf
    return [round(v, 6) for v in _l2_normalize(vector)]


# ---------------------------------------------------------------------------
# Provider mode
# ---------------------------------------------------------------------------


def _org_embedding_targets(organisation) -> List[dict]:
    """Candidate embedding providers for ``organisation``, in order:
    default provider, then fallback. Each entry carries everything the
    HTTP call needs. Empty when the org has nothing that can embed."""
    if organisation is None:
        return []
    try:
        from ai_model.ai_service import get_api_key_for_org
        from org_settings.models import OrganisationAISettings
    except Exception:
        return []

    settings = (
        OrganisationAISettings.objects
        .filter(organisation=organisation)
        .select_related('default_provider', 'fallback_provider')
        .first()
    )
    if settings is None:
        return []

    targets = []
    for provider in (settings.default_provider, settings.fallback_provider):
        if provider is None or not provider.is_active:
            continue
        name = (provider.name or '').lower()
        if name in _NO_EMBEDDINGS_API or any(t['provider'] == name for t in targets):
            continue
        api_key, base_url, extra = get_api_key_for_org(organisation, provider.name)
        model = (extra or {}).get('embedding_model') or _DEFAULT_EMBEDDING_MODELS.get(name)
        if not model:
            continue
        if provider.adapter_class == _GEMINI_ADAPTER:
            kind = 'gemini'
        elif provider.adapter_class == _OPENAI_COMPATIBLE_ADAPTER:
            kind = 'openai_compatible'
        else:
            continue
        if provider.requires_api_key and not api_key:
            continue
        targets.append({
            'provider': name,
            'kind': kind,
            'model': model,
            'api_key': api_key,
            'base_url': base_url or provider.api_base_url or None,
        })
    return targets


def _embed_openai_compatible(text: str, target: dict) -> List[float]:
    """OpenAI ``/v1/embeddings`` — also served by Ollama and most
    self-hosted gateways, so one code path covers them all."""
    import openai
    client_kwargs = {}
    if target['base_url']:
        # Same policy as the chat adapter: the per-organisation base URL is
        # checked before each call and redirects are not followed, or a
        # server that passed the check could bounce the request, key
        # included, to an internal address (review 2026-11-05). A refused
        # URL raises, and the caller falls back to the local embedding.
        from Utils.outbound import check_url
        check_url(target['base_url'])
        client_kwargs['http_client'] = openai.DefaultHttpxClient(follow_redirects=False)
    client = openai.OpenAI(
        api_key=target['api_key'] or 'ollama',  # Ollama ignores the key
        base_url=target['base_url'],
        timeout=_PROVIDER_TIMEOUT_SECONDS,
        max_retries=0,
        **client_kwargs,
    )
    resp = client.embeddings.create(model=target['model'], input=text)
    return list(resp.data[0].embedding)


def _embed_gemini(text: str, target: dict) -> List[float]:
    from google import genai
    client = genai.Client(api_key=target['api_key'])
    resp = client.models.embed_content(model=target['model'], contents=text)
    return list(resp.embeddings[0].values)


def _provider_embed(text: str, organisation) -> Optional[Embedding]:
    """Embed through the organisation's configured provider. ``None``
    when the org has no embedding-capable provider or every call fails
    (logged, never raised — similarity is an enrichment)."""
    from django.conf import settings
    if not getattr(settings, 'SEROPS_EMBEDDINGS_VIA_PROVIDER', True):
        return None
    targets = _org_embedding_targets(organisation)
    if not targets:
        return None
    try:
        payload = _redact(text)[:8000]
    except Exception as exc:
        # Fail closed: nothing goes to the provider; the caller falls
        # back to the local lexical embedding.
        logger.warning('Embedding redaction failed, embedding locally: %s', exc)
        return None
    for target in targets:
        try:
            if target['kind'] == 'gemini':
                vector = _embed_gemini(payload, target)
            else:
                vector = _embed_openai_compatible(payload, target)
            if not vector:
                raise ValueError('empty embedding')
            return Embedding(
                vector=_l2_normalize([float(v) for v in vector]),
                model=f"{target['provider']}:{target['model']}",
            )
        except Exception as exc:
            logger.warning(
                'Embedding via %s (%s) failed, trying next: %s',
                target['provider'], target['model'], exc,
            )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_text(text: str, organisation=None) -> Optional[Embedding]:
    """
    Embed ``text`` for ``organisation``. Returns ``None`` only for
    empty text.

    Provider mode when the org's AI provider can embed; otherwise (or
    when every provider call fails) lexical mode. The returned
    ``Embedding.model`` says which mode produced the vector.
    """
    if not text or not text.strip():
        return None
    result = _provider_embed(text, organisation)
    if result is not None:
        return result
    return Embedding(vector=lexical_embed(text), model=LEXICAL_MODEL)


def vectors_comparable(model_a, vec_a, model_b, vec_b) -> bool:
    """True only when two stored vectors came from the same model and
    have the same dimension. Rows written before ``embedding_model``
    existed (model ``None``) are never comparable — they were either
    random SHA-256 hashes or a model we can no longer identify."""
    return bool(
        model_a and model_a == model_b
        and vec_a and vec_b
        and isinstance(vec_a, list) and isinstance(vec_b, list)
        and len(vec_a) == len(vec_b)
    )


def min_similarity_for(model: Optional[str]) -> float:
    return LEXICAL_MIN_SIMILARITY if model == LEXICAL_MODEL else SEMANTIC_MIN_SIMILARITY


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity of two vectors. Returns 0.0 for zero vectors and
    for mismatched dimensions (never compares garbage, never raises).
    """
    if not a or not b or len(a) != len(b):
        return 0.0
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
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (na * nb)


def lexical_similarity(text_a: str, text_b: str) -> float:
    """Cosine of the lexical vectors of two texts."""
    if not (text_a or '').strip() or not (text_b or '').strip():
        return 0.0
    return cosine_similarity(lexical_embed(text_a), lexical_embed(text_b))


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


class SimilarityQuery:
    """Scores Issues against one query (an issue's text, or a batch's
    log digest) with the best comparison available per candidate.

    * Lexical similarity of the two texts, always — so an org that
      switched providers, rows written before ``embedding_model``
      existed, or rows not embedded yet still match on wording instead
      of comparing incompatible vectors (external review, v1.2.13).
    * Plus, when both vectors come from the same provider model and
      dimension, their cosine; the better of the two wins.

    ``score`` returns ``(similarity, relevance)``: ``relevance`` is the
    similarity rescaled against the threshold of the mode used — ≥ 0
    means a match — which puts semantic and lexical scores on one
    ranking scale.
    """

    def __init__(self, text: str, embedding: Optional[Embedding] = None):
        self.text = text or ''
        self.embedding = embedding
        self._lexical: Optional[List[float]] = None

    @property
    def lexical(self) -> List[float]:
        if self._lexical is None:
            if self.embedding is not None and self.embedding.is_lexical:
                self._lexical = self.embedding.vector
            else:
                self._lexical = lexical_embed(self.text)
        return self._lexical

    def score(self, candidate) -> tuple:
        cand_model = getattr(candidate, 'embedding_model', None)
        cand_vec = getattr(candidate, 'embedding', None)

        # Lexical always runs: it is local and cheap, and it is what
        # keeps a log-digest query (batch memory) matchable against RCA
        # text even where a semantic model scores the asymmetric pair
        # below its threshold.
        if cand_model == LEXICAL_MODEL and isinstance(cand_vec, list) \
                and len(cand_vec) == LEXICAL_DIM:
            cand_lexical = cand_vec
        else:
            cand_lexical = lexical_embed(text_for_issue(candidate))
        sim = cosine_similarity(self.lexical, cand_lexical) if self.text.strip() else 0.0
        best = (sim, _relevance(sim, LEXICAL_MIN_SIMILARITY))

        if (self.embedding is not None and not self.embedding.is_lexical
                and vectors_comparable(self.embedding.model, self.embedding.vector,
                                       cand_model, cand_vec)):
            sem = cosine_similarity(self.embedding.vector, cand_vec)
            sem_rel = _relevance(sem, min_similarity_for(self.embedding.model))
            if sem_rel > best[1]:
                best = (sem, sem_rel)
        return best


def _relevance(similarity: float, threshold: float) -> float:
    return (similarity - threshold) / max(1e-6, 1.0 - threshold)
