"""Pluggable LLM clients for the bench/v2 harness.

Each client module exposes a `Client` class with a uniform `complete()`
interface. The harness imports them by family name. When the relevant
API key environment variable is unset, `available()` returns False and
the harness falls back to the deterministic `mock` client.
"""

from . import anthropic, gemini, mock, openai

FAMILIES = {
    "claude": anthropic,
    "anthropic": anthropic,
    "gpt4": openai,
    "openai": openai,
    "gemini": gemini,
    "google": gemini,
    "llama3": mock,  # Together AI client not implemented in v2 round-1; mock-only
    "mock": mock,
}


def get_client(family: str, *, force_mock: bool = False):
    """Return an instantiated client for the requested model family.

    If `force_mock` is True or the live client reports `available()` is
    False (e.g. no API key in env), return the mock client instead.
    """
    module = FAMILIES.get(family.lower())
    if module is None:
        raise ValueError(
            f"Unknown model family: {family!r}. "
            f"Known: {sorted(set(FAMILIES))}"
        )
    if force_mock or not module.Client.available():
        return mock.Client(family_alias=family)
    return module.Client()


__all__ = ["FAMILIES", "get_client", "anthropic", "openai", "gemini", "mock"]
