"""Test settings — uses a local PostgreSQL container for stability."""

# -----------------------------------------------------------------------------
# Stub optional AI SDK deps BEFORE anything else imports them
# -----------------------------------------------------------------------------
# ``anthropic`` and ``google-genai`` are heavyweight optional providers
# — they ship in production requirements but are frequently absent from
# slim CI / dev test containers. Every AI-adapter test mocks the SDK
# client at the boundary anyway, so a MagicMock module stub is enough
# to make ``import anthropic`` (inside ai_model/adapters/claude.py)
# and ``from google import genai`` (inside ai_model/adapters/gemini.py)
# succeed at import time. Without this stub, ``@patch(
# 'ai_model.adapters.claude.anthropic')`` — and every downstream test
# suite that reads the adapters module — hits AttributeError because
# the parent package never got the submodule attribute set.
#
# Placing this in test_settings.py guarantees the stubs are in
# sys.modules before Django's test runner touches any test module.
import os
import sys as _sys
from unittest.mock import MagicMock as _MM

for _dep in ('anthropic', 'google.genai'):
    if _dep not in _sys.modules:
        _sys.modules[_dep] = _MM()

# ``google`` is a namespace package — if nothing has imported it yet,
# stub it and pin our genai mock as an attribute so
# ``from google import genai`` resolves. If real ``google`` was already
# imported (e.g. by some other test dep), just pin genai onto it.
if 'google' not in _sys.modules:
    _google = _MM()
    _google.genai = _sys.modules['google.genai']
    _sys.modules['google'] = _google
else:
    _sys.modules['google'].genai = _sys.modules['google.genai']

from api.settings import *  # noqa: F401, F403, E402

# Allow Django test client's default hostname
ALLOWED_HOSTS = ALLOWED_HOSTS + ['testserver']

# The test database comes from TEST_DB_* variables, never DB_*. Local test
# runs load backend/.env, whose DB_HOST is a real server; honouring it here
# would point the test runner — which creates and destroys a database — at
# that server. The defaults are the local `serops_test_db` container. CI sets
# TEST_DB_HOST/TEST_DB_PASSWORD for its own Postgres service; the host used to
# be hardcoded, so CI's test step could never have reached its database.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('TEST_DB_NAME', 'test_serops'),
        'USER': os.getenv('TEST_DB_USER', 'postgres'),
        'PASSWORD': os.getenv('TEST_DB_PASSWORD', 'testpass123'),
        'HOST': os.getenv('TEST_DB_HOST', 'serops_test_db'),
        'PORT': os.getenv('TEST_DB_PORT', '5432'),
        'TEST': {
            'NAME': 'test_serops',
        },
    }
}

# Speed up password hashing in tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Use in-memory email backend for tests
EMAIL_BACKEND = 'django.core.mail.backends.locmem.LocMemBackend'

# Disable auth-endpoint throttles in tests. The wiring is asserted
# directly by Users/test/test_auth_hardening.AuthThrottleWiringTest, so
# we still cover that the views opt into ScopedRateThrottle; here we
# only want to stop the throttle cache from poisoning unrelated
# login / password-reset tests when they fire dozens of times.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_RATES': {
        scope: None
        for scope in REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
    },
}

# Override LOGGING to avoid the FileHandler in settings.py — CI runners do
# not have the logs/ directory and tests should not depend on disk paths.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}
