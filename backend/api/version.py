"""SerOps version metadata (Batch 43).

Convention borrowed from Grafana / Prometheus / n8n / Metabase — a
single ``__version__`` module the rest of the codebase imports, plus
an env-var override so the CI/CD pipeline can stamp the release tag
into the running image without editing source.

Precedence (highest wins):

1. ``SEROPS_VERSION`` environment variable — set by CI at image build
   time (see ``.github/workflows/docker.yml`` — the ``metadata-action``
   emits a ``{{version}}`` tag that mirrors the git tag) or by an
   operator overriding the image tag in their docker-compose.
2. Hardcoded fallback ``_FALLBACK_VERSION`` — used for local dev,
   ``manage.py`` invocations, tests. Follows SemVer with the ``-dev``
   pre-release identifier so it sorts *before* any real release
   ("1.0.0-dev" < "1.0.0" < "1.0.1" per PEP 440 / SemVer).

Additional metadata exposed for the ``/api/version/`` endpoint:

* ``git_sha`` — 7-char commit SHA, from ``SEROPS_GIT_SHA`` env
  (again CI-injected). Empty in dev.
* ``built_at`` — image build ISO timestamp, from ``SEROPS_BUILT_AT``
  env. Empty in dev.

Rationale for fallback ``1.0.0-dev`` (not ``0.0.0-dev``): matches the
plan's "SemVer from launch, no v0.x-beta" decision. The next public
tag will be ``v1.0.0``; developing on ``1.0.0-dev`` keeps the version
line honest.
"""

from __future__ import annotations

import os

_FALLBACK_VERSION = '1.0.0-dev'

__version__: str = os.getenv('SEROPS_VERSION') or _FALLBACK_VERSION


def version_info() -> dict:
    """Return the version block served by ``/api/version/``.

    Keys are stable — callers (self-metrics scrape, admin UI, support
    bug reports) may parse them.
    """
    return {
        'version': __version__,
        'git_sha': (os.getenv('SEROPS_GIT_SHA') or '')[:7],
        'built_at': os.getenv('SEROPS_BUILT_AT') or '',
    }
