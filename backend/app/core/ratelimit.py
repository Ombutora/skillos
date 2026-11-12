"""Small fixed-window rate limiter.

In-memory per process: fine for a single API container. Swap for a Redis
counter when running several replicas.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_hits: dict[tuple[str, str, int], int] = defaultdict(int)


def limiter(name: str, per_minute: int):
    def dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        window = int(time.time() // 60)
        key = (name, ip, window)
        _hits[key] += 1
        if _hits[key] > per_minute:
            raise HTTPException(429, "too many requests, try again in a minute")
        if len(_hits) > 10_000:
            for k in [k for k in _hits if k[2] < window]:
                _hits.pop(k, None)

    return dep


def reset() -> None:
    _hits.clear()
