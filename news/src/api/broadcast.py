"""Thread-safe asyncio pub/sub hub for SSE fan-out."""

from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


class BroadcastHub:
    """Fan-out hub: publish items to all subscriber queues.

    Thread-safe — ``publish()`` detects whether it is called from a worker
    thread and schedules via ``call_soon_threadsafe`` when needed.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None):
        self._subscribers: dict[str, asyncio.Queue] = {}
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, maxsize: int = 256) -> tuple[str, asyncio.Queue]:
        sub_id = uuid.uuid4().hex[:12]
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers[sub_id] = q
        logger.info("SSE subscriber %s connected (%d total)", sub_id, len(self._subscribers))
        return sub_id, q

    def unsubscribe(self, sub_id: str) -> None:
        self._subscribers.pop(sub_id, None)
        logger.info("SSE subscriber %s disconnected (%d total)", sub_id, len(self._subscribers))

    def publish(self, item: dict) -> None:
        """Publish an item to all subscribers (thread-safe)."""
        if not self._subscribers:
            return

        loop = self._loop
        if loop is None:
            return

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is loop:
            self._deliver(item)
        else:
            loop.call_soon_threadsafe(self._deliver, item)

    def _deliver(self, item: dict) -> None:
        for sub_id, q in list(self._subscribers.items()):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                logger.warning("SSE subscriber %s queue full — dropping item", sub_id)

    async def shutdown(self) -> None:
        """Send None sentinel to all queues so SSE generators exit cleanly."""
        for q in self._subscribers.values():
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()
        logger.info("BroadcastHub shut down")
