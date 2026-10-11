"""Domain exceptions for the ai_model app.

These surface at the API/task boundary so callers can distinguish
"user hasn't configured a provider yet" from "provider returned an
error." Previously both cases collapsed into a generic ``AUTH_MISSING``
adapter error, which the onboarding wizard cannot key off of.
"""


class NoAIProviderConfigured(Exception):
    """No usable AI provider is configured for the organisation.

    Raised when no ``OrganisationAPIKey`` (or keyless provider like
    Ollama) exists for the caller's org, or ``OrganisationAISettings``
    has no ``default_provider``. Onboarding wizard step 2 gates on
    this — it's the "you haven't picked a model yet" signal.
    """


class ModelDeprecated(Exception):
    """The configured model ID is scheduled for provider shutdown.

    Raised eagerly at adapter entry so a stale config surfaces before
    we spend tokens on a request that will 404. Currently guards the
    OpenAI ``gpt-3.5-turbo`` and ``gpt-4`` shutdowns (2026-10-23).
    """
