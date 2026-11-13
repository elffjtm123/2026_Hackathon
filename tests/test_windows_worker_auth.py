"""Windows IPC refuses unauthenticated peers before exchanging model data."""

import asyncio
import os
import sys

import pytest

from app.ai.realtime_process import RealtimeModelProcess
from app.core.config import Settings


@pytest.mark.skipif(os.name != 'nt', reason='Windows loopback transport')
async def test_wrong_token_is_rejected_before_real_worker_connects(monkeypatch):
    spawn = asyncio.create_subprocess_exec
    waiting, proceed = asyncio.Event(), asyncio.Event()

    async def delayed(*args, **kwargs):
        waiting.set()
        await proceed.wait()
        return await spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed)
    runtime = RealtimeModelProcess(Settings(_env_file=None),
        command=[sys.executable, '-m', 'tests.model_worker_fixture'])
    starting = asyncio.create_task(runtime.start())
    try:
        await asyncio.wait_for(waiting.wait(), 3)
        port = runtime._server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        writer.write(b'x' * 64)
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 2) == b''
        writer.close()
        await writer.wait_closed()
        proceed.set()
        await asyncio.wait_for(starting, 5)
        assert all(module.status == 'ready' for module in runtime.modules.values())
    finally:
        proceed.set()
        await asyncio.gather(starting, return_exceptions=True)
        await runtime.stop()
