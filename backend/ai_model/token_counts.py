"""Prompt token counts that remember how much of the prompt was cached.

Adapters return ``(text, error, tokens_input, tokens_output)`` and that
tuple travels through retries and fallbacks to ``log_usage``. Anthropic
reports a cached prompt in three parts (``input_tokens`` is only the
uncached remainder, plus ``cache_creation_input_tokens`` and
``cache_read_input_tokens``), and the three are billed at different
rates. Counting ``input_tokens`` alone under-reported both the prompt
size and the cost, so the monthly budget cap saw less than was spent.

``PromptTokens`` is an ``int`` (the whole prompt: uncached + written +
read), so every existing caller keeps working, and it carries the
cached parts so the cost estimate can price each at its own rate.
"""


def _count(value) -> int:
    """A token count, or 0 for anything that is not one (None, a mock)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


class PromptTokens(int):
    """Total prompt tokens, with the cache-write and cache-read shares."""

    def __new__(cls, uncached: int = 0, cache_write: int = 0, cache_read: int = 0):
        uncached, cache_write, cache_read = (_count(v) for v in (uncached, cache_write, cache_read))
        obj = super().__new__(cls, uncached + cache_write + cache_read)
        obj.uncached = uncached
        obj.cache_write = cache_write
        obj.cache_read = cache_read
        return obj

    def __reduce__(self):  # survive pickling (Celery results, caches)
        return (PromptTokens, (self.uncached, self.cache_write, self.cache_read))


def cache_parts(tokens_input) -> tuple:
    """``(uncached, cache_write, cache_read)`` for any prompt token count."""
    if isinstance(tokens_input, PromptTokens):
        return tokens_input.uncached, tokens_input.cache_write, tokens_input.cache_read
    return int(tokens_input or 0), 0, 0
