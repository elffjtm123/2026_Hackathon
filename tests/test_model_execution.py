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


async def done_within(awaitable, timeout=2):
    """Await with a hard deadline; unlike wait_for it cannot be defeated by a swallowed cancel."""
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=timeout)
    assert done, "hung"
    return task.result()


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


# --- offline kinds, suspend/resume and borrowing (spec 4.4) ---

OFFLINE_KINDS = ["summary", "interview_plan", "interview_evaluation"]


def _busy_code(kind):
    return "SUMMARY_BUSY" if kind == "summary" else "INTERVIEW_BUSY"


@pytest.mark.parametrize("owner_kind", OFFLINE_KINDS)
@pytest.mark.parametrize("kind", OFFLINE_KINDS)
@pytest.mark.asyncio
async def test_reserve_offline_rejects_every_other_offline_owner(owner_kind, kind):
    from app.ai.model_execution import ModelExecution

    execution = ModelExecution(Runtime())
    execution.reserve_offline(owner_kind)
    assert execution.busy
    with pytest.raises(ValueError, match=_busy_code(owner_kind)):
        execution.reserve_offline(kind)
    assert execution.owner == owner_kind
    execution.release_offline(owner_kind)
    assert not execution.busy
    execution.reserve_offline(kind)


@pytest.mark.asyncio
async def test_reserve_offline_rejected_while_session_owns_and_release_is_owner_scoped():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    for kind in OFFLINE_KINDS:
        with pytest.raises(ValueError, match="PRACTICE_ACTIVE"):
            execution.reserve_offline(kind)
        execution.release_offline(kind)
    assert execution.owner == session
    await execution.stop_session(session)
    execution.reserve_offline("interview_plan")
    execution.release_offline("summary")
    assert execution.busy
    execution.release_offline("interview_plan")


@pytest.mark.parametrize("kind", ["interview_plan", "interview_evaluation"])
@pytest.mark.asyncio
async def test_start_session_rejected_while_interview_kind_owns(kind):
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    execution.reserve_offline(kind)
    with pytest.raises(ValueError, match="INTERVIEW_BUSY"):
        await execution.start_session(uuid4())
    assert runtime.starts == 0


@pytest.mark.asyncio
async def test_suspend_keeps_ownership_and_rejects_everyone_else():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    assert not runtime.loaded
    assert execution.busy and execution.owner == session
    await execution.suspend_session(session)
    assert runtime.stops == 1
    for kind in OFFLINE_KINDS:
        with pytest.raises(ValueError, match="PRACTICE_ACTIVE"):
            execution.reserve_offline(kind)
    with pytest.raises(ValueError, match="SESSION_BUSY"):
        await execution.start_session(uuid4())
    with pytest.raises(ValueError, match="SESSION_SUSPENDED"):
        await execution.start_session(session)
    assert runtime.starts == 1


@pytest.mark.asyncio
async def test_suspend_resume_borrowing_require_ownership():
    from app.ai.model_execution import ModelExecution

    execution = ModelExecution(Runtime())
    other = uuid4()
    for call in (execution.suspend_session, execution.resume_session):
        with pytest.raises(ValueError, match="SESSION_NOT_OWNER"):
            await call(other)
    with pytest.raises(ValueError, match="SESSION_NOT_OWNER"):
        async with execution.borrowing(other):
            pass
    session = uuid4()
    await execution.start_session(session)
    with pytest.raises(ValueError, match="SESSION_NOT_OWNER"):
        await execution.suspend_session(other)
    with pytest.raises(ValueError, match="SESSION_NOT_OWNER"):
        async with execution.borrowing(other):
            pass


@pytest.mark.asyncio
async def test_resume_restarts_runtime_and_is_noop_when_running():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.resume_session(session)
    assert runtime.starts == 1
    await execution.suspend_session(session)
    await execution.resume_session(session)
    assert runtime.starts == 2 and runtime.loaded
    await execution.start_session(session)
    assert runtime.starts == 2
    await execution.suspend_session(session)


@pytest.mark.asyncio
async def test_borrowing_only_while_suspended_and_one_at_a_time():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    with pytest.raises(ValueError, match="SESSION_NOT_SUSPENDED"):
        async with execution.borrowing(session):
            pytest.fail("must not enter")
    await execution.suspend_session(session)
    async with execution.borrowing(session):
        assert execution.busy
        with pytest.raises(ValueError, match="BORROW_ACTIVE"):
            async with execution.borrowing(session):
                pytest.fail("must not enter")
        with pytest.raises(ValueError, match="BORROW_ACTIVE"):
            await execution.resume_session(session)
        with pytest.raises(ValueError, match="SESSION_SUSPENDED"):
            await execution.start_session(session)
        with pytest.raises(ValueError, match="PRACTICE_ACTIVE"):
            execution.reserve_offline("interview_plan")
        with pytest.raises(ValueError, match="SESSION_BUSY"):
            await execution.start_session(uuid4())
        await execution.suspend_session(session)
        assert runtime.starts == 1
    await execution.resume_session(session)
    assert runtime.starts == 2


@pytest.mark.asyncio
async def test_borrowing_clears_on_exception():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    with pytest.raises(RuntimeError):
        async with execution.borrowing(session):
            raise RuntimeError("boom")
    async with execution.borrowing(session):
        pass
    await execution.resume_session(session)
    assert runtime.loaded


@pytest.mark.asyncio
async def test_suspend_in_flight_blocks_borrow_resume_and_start_until_done():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    runtime.finish_stop.clear()
    suspending = asyncio.create_task(execution.suspend_session(session))
    await runtime.stopping.wait()
    with pytest.raises(ValueError, match="SESSION_NOT_SUSPENDED"):
        async with execution.borrowing(session):
            pytest.fail("must not enter")
    with pytest.raises(ValueError, match="MODEL_UNAVAILABLE_OR_BUSY"):
        await execution.resume_session(session)
    with pytest.raises(ValueError, match="SESSION_SUSPENDED"):
        await execution.start_session(session)
    runtime.finish_stop.set()
    await suspending
    async with execution.borrowing(session):
        pass


@pytest.mark.asyncio
async def test_suspend_rejected_while_start_in_flight():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    runtime.finish_start.clear()
    execution = ModelExecution(runtime)
    session = uuid4()
    starting = asyncio.create_task(execution.start_session(session))
    await runtime.started.wait()
    with pytest.raises(ValueError, match="MODEL_UNAVAILABLE_OR_BUSY"):
        await execution.suspend_session(session)
    runtime.finish_start.set()
    await starting
    assert runtime.loaded


@pytest.mark.asyncio
async def test_cancelled_suspend_still_stops_runtime_and_ends_suspended():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    runtime.finish_stop.clear()
    suspending = asyncio.create_task(execution.suspend_session(session))
    await runtime.stopping.wait()
    suspending.cancel()
    await asyncio.sleep(0)
    assert not suspending.done()  # waits for runtime.stop() to finish
    runtime.finish_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await suspending
    assert runtime.stops == 1 and not runtime.loaded
    assert execution.owner == session
    async with execution.borrowing(session):
        pass
    await execution.resume_session(session)
    assert runtime.loaded


@pytest.mark.asyncio
async def test_resume_in_flight_is_not_borrowable_and_cancel_tears_down():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    runtime.finish_start.clear()
    runtime.started.clear()
    resuming = asyncio.create_task(execution.resume_session(session))
    await runtime.started.wait()
    with pytest.raises(ValueError, match="SESSION_NOT_SUSPENDED"):
        async with execution.borrowing(session):
            pytest.fail("must not enter")
    with pytest.raises(ValueError, match="SESSION_SUSPENDED"):
        await execution.start_session(session)
    with pytest.raises(ValueError, match="MODEL_UNAVAILABLE_OR_BUSY"):
        await execution.suspend_session(session)
    runtime.stopping.clear()
    runtime.finish_stop.clear()
    resuming.cancel()
    await runtime.stopping.wait()
    assert execution.owner == session
    with pytest.raises(ValueError, match="PRACTICE_ACTIVE"):
        execution.reserve_offline("summary")
    runtime.finish_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await resuming
    assert execution.owner is None and not runtime.loaded
    execution.reserve_offline("interview_plan")


@pytest.mark.asyncio
async def test_resume_failure_fully_stops_session():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)

    async def broken():
        raise OSError("spawn failed")

    runtime.start = broken
    with pytest.raises(OSError):
        await execution.resume_session(session)
    assert execution.owner is None
    execution.reserve_offline("summary")


@pytest.mark.asyncio
async def test_stop_while_borrowing_waits_for_borrowed_work_cleanup():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    log = []
    entered = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def borrowed_work():
        async with execution.borrowing(session):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                await release_cleanup.wait()
                log.append(("cleanup", execution.owner))

    work = asyncio.create_task(borrowed_work())
    await entered.wait()
    stopping = asyncio.create_task(execution.stop_session(session))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not stopping.done() and execution.owner == session
    with pytest.raises(ValueError, match="SESSION_NOT_SUSPENDED"):
        async with execution.borrowing(session):
            pytest.fail("must not enter")
    release_cleanup.set()
    await done_within(stopping)
    assert log == [("cleanup", session)]
    assert execution.owner is None
    with pytest.raises(asyncio.CancelledError):
        await done_within(work)
    assert runtime.stops == 1  # runtime was already stopped by suspend
    execution.reserve_offline("interview_plan")
    execution.release_offline("interview_plan")
    await execution.start_session(uuid4())


@pytest.mark.asyncio
async def test_stop_from_inside_borrowing_task_does_not_deadlock():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)

    async def borrowed_work():
        async with execution.borrowing(session):
            await execution.stop_session(session)
            assert execution.owner == session  # released only after leaving the block

    await done_within(borrowed_work())
    for _ in range(5):
        await asyncio.sleep(0)
    assert execution.owner is None
    await execution.start_session(uuid4())


@pytest.mark.asyncio
async def test_stop_from_suspended_does_not_stop_runtime_twice():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    await execution.stop_session(session)
    assert runtime.stops == 1 and execution.owner is None
    await execution.start_session(session)
    assert runtime.loaded
    await execution.stop_session(session)


@pytest.mark.asyncio
async def test_stop_during_suspend_in_flight_waits_and_releases():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    runtime.finish_stop.clear()
    suspending = asyncio.create_task(execution.suspend_session(session))
    await runtime.stopping.wait()
    stopping = asyncio.create_task(execution.stop_session(session))
    await asyncio.sleep(0)
    assert execution.owner == session
    runtime.finish_stop.set()
    await stopping
    await suspending
    assert execution.owner is None and not runtime.loaded
    assert runtime.stops == 1
    await execution.start_session(session)


@pytest.mark.asyncio
async def test_stop_during_resume_in_flight_releases_after_runtime_stops():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    runtime.finish_start.clear()
    runtime.started.clear()
    resuming = asyncio.create_task(execution.resume_session(session))
    await runtime.started.wait()
    await execution.stop_session(session)
    assert execution.owner is None and not runtime.loaded
    with pytest.raises(asyncio.CancelledError):
        await resuming
    runtime.finish_start.set()
    await execution.start_session(session)


@pytest.mark.asyncio
async def test_repeated_cancelled_stop_while_borrowing_keeps_ownership_until_clean():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    entered = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def borrowed_work():
        async with execution.borrowing(session):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                await release_cleanup.wait()

    work = asyncio.create_task(borrowed_work())
    await entered.wait()
    stopping = asyncio.create_task(execution.stop_session(session))
    for _ in range(3):
        await asyncio.sleep(0)
        stopping.cancel()
    await asyncio.sleep(0)
    assert execution.owner == session
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await done_within(stopping)
    assert execution.owner is None
    with pytest.raises(asyncio.CancelledError):
        await done_within(work)


@pytest.mark.asyncio
async def test_close_works_while_suspended_and_borrowing():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    await execution.close()
    assert execution.owner is None

    await execution.start_session(session)
    await execution.suspend_session(session)
    entered = asyncio.Event()

    async def borrowed_work():
        async with execution.borrowing(session):
            entered.set()
            await asyncio.Event().wait()

    work = asyncio.create_task(borrowed_work())
    await entered.wait()
    await done_within(execution.close())
    assert execution.owner is None
    with pytest.raises(asyncio.CancelledError):
        await done_within(work)


@pytest.mark.parametrize("how", ["task", "wait_for", "finish"])
@pytest.mark.asyncio
async def test_stop_from_child_task_of_borrower_does_not_deadlock(how):
    from app.ai.model_execution import ModelExecution, finish

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)

    async def borrowed_work():
        async with execution.borrowing(session):
            if how == "task":
                await asyncio.create_task(execution.stop_session(session))
            elif how == "wait_for":
                await asyncio.wait_for(execution.stop_session(session), 5)
            else:
                await finish(asyncio.create_task(execution.stop_session(session)))
            assert execution.owner == session

    await done_within(borrowed_work())
    for _ in range(5):
        await asyncio.sleep(0)
    assert execution.owner is None
    await execution.start_session(uuid4())


@pytest.mark.asyncio
async def test_generation_active_for_offline_owner_and_borrow_only():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    assert not execution.generation_active
    for kind in OFFLINE_KINDS:
        execution.reserve_offline(kind)
        assert execution.generation_active
        execution.release_offline(kind)
        assert not execution.generation_active
    session = uuid4()
    await execution.start_session(session)
    assert not execution.generation_active
    await execution.suspend_session(session)
    assert not execution.generation_active
    async with execution.borrowing(session):
        assert execution.generation_active
    assert not execution.generation_active
    await execution.stop_session(session)


@pytest.mark.asyncio
async def test_borrowing_exit_in_different_task_still_clears_state():
    from app.ai.model_execution import ModelExecution

    runtime = Runtime()
    execution = ModelExecution(runtime)
    session = uuid4()
    await execution.start_session(session)
    await execution.suspend_session(session)
    cm = execution.borrowing(session)
    await asyncio.create_task(cm.__aenter__())
    assert execution.generation_active
    await asyncio.create_task(cm.__aexit__(None, None, None))
    assert not execution.generation_active
    await done_within(execution.stop_session(session))
    assert execution.owner is None
