"""Short-lived local llama-server runner shared by script hints and interview generation."""

import asyncio
import json
import os
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError

MAX_FRAME_CHARS = 65536
MAX_OUTPUT_CHARS = 32768


async def _uninterrupted(work: Awaitable[Any]) -> Any:
    """Finish `work` even if this task is cancelled meanwhile, then re-raise the cancellation."""
    task = asyncio.ensure_future(work)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass  # surfaced by task.result() below
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    """Terminate, then kill after 5 seconds, and always reap the child."""
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


async def _read_response(reader: asyncio.StreamReader) -> bytes:
    """Everything up to EOF (HTTP/1.0 closes the connection), at most MAX_FRAME_CHARS."""
    data = bytearray()
    while len(data) < MAX_FRAME_CHARS:
        chunk = await reader.read(MAX_FRAME_CHARS - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


async def server_ready(port: int) -> bool:
    """One /health probe over a plain socket.

    Not httpx: it logs an INFO line per request, and this is polled every 250 ms.
    """
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 5)
    except (OSError, asyncio.TimeoutError):
        return False
    try:
        writer.write(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        raw = await asyncio.wait_for(_read_response(reader), 5)
    except (OSError, asyncio.TimeoutError):
        return False
    finally:
        writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    if b" 200" not in head.split(b"\r\n", 1)[0]:
        return False
    try:
        document = json.loads(body)
    except ValueError:
        return False
    return isinstance(document, dict) and document.get("status") == "ok"


class LlmSession:
    """A ready llama-server; valid only inside the `LocalLlm.loaded()` block that made it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def count_tokens(self, prompt: str) -> int:
        response = await self._client.post(
            "/tokenize", json={"content": prompt, "add_special": True}
        )
        response.raise_for_status()
        tokens = response.json()["tokens"]
        if not isinstance(tokens, list):
            raise ValueError("Invalid tokenizer response")
        return len(tokens)

    async def complete_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int,
        on_delta: Callable[[str], None] | None = None,
        schema_name: str = "response",
        seed: int = 42,
    ) -> Any:
        text, reason = "", None
        async with self._client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "top_p": 0.8,
                "top_k": 20,
                "min_p": 0,
                "seed": seed,
                "max_tokens": max_tokens,
                "stream": True,
                "cache_prompt": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema},
                },
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                if len(line) > MAX_FRAME_CHARS:
                    raise ValueError("Oversized model frame")
                if line[6:] == "[DONE]":
                    break
                choice = json.loads(line[6:])["choices"][0]
                reason = choice.get("finish_reason") or reason
                delta = choice.get("delta", {}).get("content") or ""
                text += delta
                if len(text) > MAX_OUTPUT_CHARS:
                    raise ValueError("Oversized model output")
                if on_delta is not None and delta:
                    on_delta(delta)
        document = json.loads(text)
        if reason != "stop":
            raise ValueError("Model output did not finish")
        return document


class LocalLlm:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _asset_paths(self) -> tuple[str, str]:
        paths = [Path(self.settings.summary_server_path), Path(self.settings.summary_model_path)]
        if not all(path.is_file() and path.stat().st_size > 0 for path in paths):
            raise AppError(
                "LOCAL_MODEL_UNAVAILABLE", "로컬 생성 모델과 실행 파일을 준비해 주세요.", 503
            )
        return str(paths[0].resolve()), str(paths[1].resolve())

    @asynccontextmanager
    async def loaded(self) -> AsyncIterator[LlmSession]:
        """Start llama-server and wait until ready; always terminate and reap it on exit."""
        server, model = await asyncio.to_thread(self._asset_paths)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                server,
                "-m",
                model,
                "-ngl",
                "999",
                "--no-repack",
                "--fit",
                "off",
                "-t",
                "4",
                "-tb",
                "4",
                "-c",
                "4096",
                "-np",
                "1",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-cache-prompt",
                "--cache-ram",
                "0",
                "--reasoning",
                "off",
                "--chat-template-kwargs",
                '{"enable_thinking":false}',
                "--no-webui",
                "--log-disable",
                creationflags=0x08000000 if os.name == "nt" else 0,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        # Cancellation may arrive after the OS child exists but before spawn returns its handle.
        cancelled = False
        while not spawn.done():
            try:
                await asyncio.shield(spawn)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                pass  # surfaced by spawn.result() below
        process = spawn.result()
        try:
            if cancelled:
                raise asyncio.CancelledError
            # Only this short-lived localhost process receives prompts; no proxy or logging.
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
            ) as client:
                for _ in range(240):
                    if process.returncode is not None:
                        raise ValueError("Native generation model failed to start")
                    if await server_ready(port):
                        break
                    await asyncio.sleep(0.25)
                else:
                    raise asyncio.TimeoutError()
                yield LlmSession(client)
        finally:
            await _uninterrupted(terminate_process(process))
