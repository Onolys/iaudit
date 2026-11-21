"""Fake LiteLLM completion helpers (also used by core's client tests)."""

from types import SimpleNamespace


def completion(content: str, **usage):
    u = dict(prompt_tokens=10, completion_tokens=5, cache_read_input_tokens=3)
    u.update(usage)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(**u),
    )


class Fake:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        r = self.results.pop(0)
        if isinstance(r, BaseException):
            raise r
        if callable(r):
            return await r()
        return r
