import asyncio

import pytest
from youtube_audio.events import EventBroker


@pytest.mark.asyncio
async def test_event_broker_fans_out_named_event() -> None:
    broker = EventBroker()
    async with broker.subscribe() as subscription:
        await broker.publish("queue_changed", {"id": "job"})
        event = await asyncio.wait_for(subscription.get(), timeout=1)
    assert event.type == "queue_changed"
    assert event.data == {"id": "job"}
