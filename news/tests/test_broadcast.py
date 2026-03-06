"""Tests for BroadcastHub pub/sub."""

import asyncio

import pytest

from src.api.broadcast import BroadcastHub


@pytest.fixture
def hub(event_loop):
    h = BroadcastHub(loop=event_loop)
    return h


@pytest.mark.asyncio
async def test_subscribe_unsubscribe():
    hub = BroadcastHub(loop=asyncio.get_running_loop())
    sub_id, q = hub.subscribe()
    assert hub.subscriber_count == 1
    hub.unsubscribe(sub_id)
    assert hub.subscriber_count == 0


@pytest.mark.asyncio
async def test_fanout():
    hub = BroadcastHub(loop=asyncio.get_running_loop())
    _, q1 = hub.subscribe()
    _, q2 = hub.subscribe()

    item = {"title": "test", "impact_level": "high"}
    hub.publish(item)

    # Both queues should receive the item
    assert await asyncio.wait_for(q1.get(), timeout=1.0) == item
    assert await asyncio.wait_for(q2.get(), timeout=1.0) == item


@pytest.mark.asyncio
async def test_queue_full_drops_item():
    hub = BroadcastHub(loop=asyncio.get_running_loop())
    _, q = hub.subscribe(maxsize=1)

    hub.publish({"n": 1})
    hub.publish({"n": 2})  # should be dropped, queue full

    assert await asyncio.wait_for(q.get(), timeout=1.0) == {"n": 1}
    assert q.empty()


@pytest.mark.asyncio
async def test_shutdown_sends_sentinel():
    hub = BroadcastHub(loop=asyncio.get_running_loop())
    _, q = hub.subscribe()

    await hub.shutdown()
    item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert item is None
    assert hub.subscriber_count == 0


@pytest.mark.asyncio
async def test_publish_no_subscribers():
    """publish() with no subscribers should not raise."""
    hub = BroadcastHub(loop=asyncio.get_running_loop())
    hub.publish({"x": 1})  # no-op, no error


@pytest.mark.asyncio
async def test_unsubscribe_unknown_id():
    """unsubscribe() with unknown id should not raise."""
    hub = BroadcastHub(loop=asyncio.get_running_loop())
    hub.unsubscribe("nonexistent")  # no-op, no error
