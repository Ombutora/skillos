"""In-process WebSocket fan-out for live session updates.

Single-process only. With several API replicas, publish through Redis pub/sub instead.
"""

import asyncio
from collections import defaultdict

from fastapi import WebSocket

_subs: dict[str, set[WebSocket]] = defaultdict(set)
_loop: asyncio.AbstractEventLoop | None = None


async def subscribe(session_id: str, ws: WebSocket) -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    _subs[session_id].add(ws)


def unsubscribe(session_id: str, ws: WebSocket) -> None:
    _subs[session_id].discard(ws)


async def _send(session_id: str, message: dict) -> None:
    for ws in list(_subs.get(session_id, ())):
        try:
            await ws.send_json(message)
        except Exception:
            _subs[session_id].discard(ws)


def publish(session_id: str, message: dict) -> None:
    """Safe to call from sync route handlers (which run in a worker thread)."""
    if not _subs.get(session_id) or _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_send(session_id, message), _loop)
