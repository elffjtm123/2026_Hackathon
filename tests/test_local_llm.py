import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from app.ai.local_llm import LocalLlm
from app.core.config import Settings
from app.core.errors import AppError

SCHEMA = {"type": "object"}


def write_assets(
    tmp_path: Path, *, ignore_sigterm: bool = False, exit_early: bool = False
) -> tuple[Path, Path, Path]:
    # Test-only native HTTP boundary; exercises real spawning and termination.
    executable = tmp_path / "llm-server"
    pid_file = tmp_path / "pid"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, signal, sys, time\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_sigterm else "")
        + "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        + ("sys.exit(3)\n" if exit_early else "")
        + "class Handler(BaseHTTPRequestHandler):\n"
        " def log_message(self, *args): pass\n"
        " def do_GET(self):\n"
        '  self.send_response(200); self.end_headers(); self.wfile.write(b\'{"status":"ok"}\')\n'
        " def do_POST(self):\n"
        "  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))\n"
        "  if self.path=='/tokenize':\n"
        "   self.send_response(200); self.end_headers()\n"
        "   self.wfile.write(json.dumps({'tokens':[0,1,2]}).encode()); return\n"
        "  prompt=data['messages'][0]['content']\n"
        "  if prompt.startswith('hang'): time.sleep(60)\n"
        "  if prompt=='frame':\n"
        "   self.send_response(200); self.end_headers()\n"
        "   self.wfile.write(('data: '+'x'*70000+'\\n\\n').encode()); return\n"
        "  if prompt=='big': result=json.dumps({'text':'x'*40000})\n"
        "  else: result=json.dumps({'echo':prompt,'max':data['max_tokens'],"
        "'seed':data['seed']},ensure_ascii=False)\n"
        "  reason='length' if prompt=='length' else 'stop'\n"
        "  self.send_response(200); self.send_header('Content-Type','text/event-stream')\n"
        "  self.end_headers()\n"
        "  for f in [result[i:i+8] for i in range(0,len(result),8)]:\n"
        "   e={'choices':[{'delta':{'content':f},'finish_reason':None}]}\n"
        "   self.wfile.write(('data: '+json.dumps(e)+'\\n\\n').encode()); self.wfile.flush()\n"
        "  fin=json.dumps({'choices':[{'delta':{},'finish_reason':reason}]})\n"
        "  self.wfile.write(('data: '+fin+'\\n\\ndata: [DONE]\\n\\n').encode())\n"
        "HTTPServer(('127.0.0.1',int(sys.argv[sys.argv.index('--port')+1])),Handler)"
        ".serve_forever()\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"test-only boundary fixture")
    return executable, model, pid_file


@pytest.fixture
def assets(tmp_path: Path) -> tuple[Path, Path, Path]:
    return write_assets(tmp_path)


def llm(assets: tuple[Path, Path, Path]) -> LocalLlm:
    return LocalLlm(
        Settings(
            _env_file=None, summary_server_path=str(assets[0]), summary_model_path=str(assets[1])
        )
    )


def assert_gone(pid_file: Path) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


@pytest.mark.asyncio
async def test_server_is_reaped_on_normal_exit(assets) -> None:
    async with llm(assets).loaded() as session:
        assert (await session.complete_json("hi", SCHEMA, max_tokens=7))["echo"] == "hi"
        os.kill(int(assets[2].read_text()), 0)  # alive inside the block
    assert_gone(assets[2])


@pytest.mark.asyncio
async def test_server_is_reaped_when_block_raises(assets) -> None:
    with pytest.raises(RuntimeError):
        async with llm(assets).loaded():
            raise RuntimeError("boom")
    assert_gone(assets[2])


@pytest.mark.asyncio
async def test_server_is_reaped_on_cancellation(assets) -> None:
    inside = asyncio.Event()

    async def work() -> None:
        async with llm(assets).loaded():
            inside.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(work())
    await inside.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_gone(assets[2])


@pytest.mark.asyncio
async def test_multiple_calls_share_one_server(assets) -> None:
    async with llm(assets).loaded() as session:
        pid = assets[2].read_text()
        first = await session.complete_json("one", SCHEMA, max_tokens=11)
        second = await session.complete_json("two", SCHEMA, max_tokens=22)
        assert assets[2].read_text() == pid
    assert (first["echo"], first["max"], first["seed"]) == ("one", 11, 42)
    assert (second["echo"], second["max"]) == ("two", 22)


@pytest.mark.asyncio
async def test_oversized_output_is_rejected(assets) -> None:
    async with llm(assets).loaded() as session:
        with pytest.raises(ValueError, match="Oversized"):
            await session.complete_json("big", SCHEMA, max_tokens=7)
    assert_gone(assets[2])


@pytest.mark.asyncio
async def test_finish_reason_other_than_stop_is_rejected(assets) -> None:
    async with llm(assets).loaded() as session:
        with pytest.raises(ValueError):
            await session.complete_json("length", SCHEMA, max_tokens=7)


@pytest.mark.asyncio
async def test_on_delta_receives_every_content_delta(assets) -> None:
    deltas: list[str] = []
    async with llm(assets).loaded() as session:
        result = await session.complete_json("hello", SCHEMA, max_tokens=7, on_delta=deltas.append)
    assert len(deltas) > 1
    assert json.loads("".join(deltas)) == result


@pytest.mark.asyncio
async def test_missing_assets_raise_unavailable(assets) -> None:
    service = llm(assets)
    service.settings.summary_model_path = "/definitely-missing-model.gguf"
    with pytest.raises(AppError) as info:
        async with service.loaded():
            pass
    assert info.value.code == "LOCAL_MODEL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_oversized_frame_is_rejected(tmp_path: Path) -> None:
    assets = write_assets(tmp_path)
    async with llm(assets).loaded() as session:
        with pytest.raises(ValueError, match="Oversized model frame"):
            await session.complete_json("frame", SCHEMA, max_tokens=7)


@pytest.mark.asyncio
async def test_child_exiting_during_health_check_is_a_start_failure(tmp_path: Path) -> None:
    assets = write_assets(tmp_path, exit_early=True)
    with pytest.raises(ValueError, match="failed to start"):
        async with llm(assets).loaded():
            pass
    assert_gone(assets[2])


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_stubborn_child_to_be_reaped(tmp_path: Path) -> None:
    assets = write_assets(tmp_path, ignore_sigterm=True)
    inside = asyncio.Event()

    async def work() -> None:
        async with llm(assets).loaded() as session:
            inside.set()
            await session.complete_json("hang", SCHEMA, max_tokens=7)

    task = asyncio.create_task(work())
    await inside.wait()
    for _ in range(4):
        task.cancel()
        await asyncio.sleep(0.05)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_gone(assets[2])
