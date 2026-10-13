"""Startup checks for AI provider configuration.

SerOps does not read AI provider keys from the environment. They live on
``OrganisationAPIKey``, per organisation, Fernet-encrypted at rest, and are
entered in the UI. The env-var fallback that once existed was removed in
``org_settings`` migration 0011, which also blanked ``env_key_name`` so the
catalogue would stop advertising a mechanism that no longer worked.

The documentation did not keep up, and the misconception reappeared in five
separate places: ``.env.example``, the quick-start README, the backend README,
the Helm chart's production values example, and the ``env_key_name`` help text.
Each was written by someone reasonably assuming a provider key behaves like
every other credential. Fixing prose only helps the person who reads that
particular file, and the person who needs help has already set the variable and
is wondering why nothing happens.

So the application says it itself. ``manage.py check`` runs on every
``runserver`` and ``migrate``, which means the warning appears exactly when
someone has just configured a deployment and is watching the logs.
"""

import os

from django.core import checks

# Variables that nothing in the codebase reads. Setting one has no effect
# whatsoever, which is precisely why it needs saying out loud.
UNUSED_PROVIDER_ENV_VARS = (
    'ANTHROPIC_API_KEY',
    'CLAUDE_API_KEY',
    'GOOGLE_API_KEY',
    'GEMINI_API_KEY',
    'DEEPSEEK_API_KEY',
)

# Read, but only by Data/embeddings.py for issue-similarity embeddings — never
# for root-cause analysis. Worth distinguishing: warning about it would be
# wrong, and saying nothing leaves someone who set it for RCA none the wiser.
EMBEDDINGS_ONLY_ENV_VAR = 'OPENAI_API_KEY'

# Phrased as a clause so it reads correctly whether it opens a sentence or
# continues one.
_WHERE_KEYS_GO = (
    'keys belong in the UI under Settings → AI Providers, stored per '
    'organisation and encrypted at rest, so one deployment can serve several '
    'organisations without pooling their quota or billing'
)


@checks.register('ai')
def ai_provider_env_keys_unused(app_configs, **kwargs):
    """Warn when an AI provider key is set in the environment.

    Returns a warning per variable rather than one combined message, so the
    output names the exact variable the operator set.
    """
    found = []

    for name in UNUSED_PROVIDER_ENV_VARS:
        if os.environ.get(name):
            found.append(checks.Warning(
                f'{name} is set in the environment but SerOps never reads it.',
                hint=(
                    f'AI provider keys are not configured through the '
                    f'environment — {_WHERE_KEYS_GO}. Unset {name} so a live '
                    f'credential is not sitting in your deployment config for '
                    f'no benefit.'
                ),
                id='ai.W001',
            ))

    if os.environ.get(EMBEDDINGS_ONLY_ENV_VAR):
        found.append(checks.Info(
            f'{EMBEDDINGS_ONLY_ENV_VAR} is set and will be used for issue '
            f'similarity embeddings only.',
            hint=(
                'This key does not drive root-cause analysis. If you set it '
                f'expecting SerOps to analyse with OpenAI, {_WHERE_KEYS_GO}.'
            ),
            id='ai.I001',
        ))

    return found
