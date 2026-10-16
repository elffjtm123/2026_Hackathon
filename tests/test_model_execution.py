import asyncio
from uuid import uuid4

import pytest


class Runtime:
    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.loaded = False
        self.started = asyncio.Event()
        self.finish_start = asyncio.Event()
        self.finish_start.set()
        self.stopping = asyncio.Event()
        self.finish_stop = asyncio.Event()
        self.finish_stop.set()

    async def start(self):
        self.starts += 1
        self.started.set()
        await self.finish_start.wait()
        self.loaded = True

    async def stop(self):
        self.stopping.set()
        await self.finish_stop.wait()
        self.stops += 1
        self.loaded = False


@pytest.mark.asyncio
async def test_summary_and_realtime_ownership_are_exclusive():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    execution.reserve_summary()
    with pytest.raises(ValueError, match="SUMMARY_BUSY"):
        await execution.start_session(session)
    assert runtime.starts == 0
    execution.release_summary()
    await execution.start_session(session)
    await execution.start_session(session)
    assert runtime.starts == 1
    with pytest.raises(ValueError, match="PRACTICE_ACTIVE"):
        execution.reserve_summary()
    with pytest.raises(ValueError, match="SESSION_BUSY"):
        await execution.start_session(uuid4())
    await execution.stop_session(uuid4())
    assert runtime.loaded
    await execution.stop_session(session)
    assert not runtime.loaded
    execution.reserve_summary()
    execution.release_summary()


@pytest.mark.asyncio
async def test_loading_and_repeated_cancelled_teardown_keep_ownership():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    runtime.finish_start.clear()
    runtime.finish_stop.clear()
    execution = ModelExecution(runtime)
    session = uuid4()
    starting = asyncio.create_task(execution.start_session(session))
    await runtime.started.wait()
    with pytest.raises(ValueError, match="PRACTICE_ACTIVE"):
        execution.reserve_summary()
    starting.cancel()
    await runtime.stopping.wait()
    for _ in range(3):
        starting.cancel()
        await asyncio.sleep(0)
    with pytest.raises(ValueError, match="PRACTICE_ACTIVE"):
        execution.reserve_summary()
    runtime.finish_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert not runtime.loaded
    execution.reserve_summary()
    execution.release_summary()


def test_service_startup_does_not_load_models(client):
    assert all(module.status == "idle" for module in client.app.state.module_status.values())
    assert client.app.state.model_execution.runtime.process is None


def test_failed_demo_prepare_and_cleanup_do_not_keep_session_ownership(client, monkeypatch):
    from tests.test_session_flow import send_v2

    original = client.app.state.state_store.set

    async def unavailable(*args):
        raise OSError("test state store down")

    monkeypatch.setattr(client.app.state.state_store, "set", unavailable)
    with pytest.raises(OSError):
        with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
            send_v2(ws, "session.start", 1)
            ws.receive_json()
    assert not client.app.state.live_sessions
    assert client.app.state.model_execution.owner is None
    monkeypatch.setattr(client.app.state.state_store, "set", original)
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
        send_v2(ws, "session.start", 1)
        assert ws.receive_json()["event"] == "session.ready"
