"""On-demand sentence hints; the native model never remains loaded after a request."""

import asyncio
import socket
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.script_sync.service import analyze_script, normalize_script

INSTRUCTION = """다음 발표문을 발표자가 말할 내용을 떠올릴 수 있는 한 줄 요지 메모로 압축하세요.
대상과 핵심 행동을 연결하고, 긴 배경이나 군더더기는 생략하세요.
완전한 문장 대신 개발·해결·유지·판정·예정 같은 메모체를 쓰세요.
중요한 부정·조건·수치·고유명사·완료와 계획의 구분은 유지하세요.
원문에 없는 내용, 제목, 해설은 쓰지 말고 메모 하나만 출력하세요.
예시 입력: 체험 부스를 3개에서 5개로 늘렸지만, 행사 총예산은 200만원으로 유지했습니다.
예시 메모: 체험 부스 3→5개 확대, 총예산 200만원 유지"""


class LocalScriptSummarizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.busy = False
        self._process: asyncio.subprocess.Process | None = None
        self._owner: asyncio.Task[Any] | None = None

    async def summarize(self, script: str) -> dict[str, Any]:
        if self.busy:
            raise AppError("SUMMARY_BUSY", "요약 처리와 모델 정리가 끝난 뒤 다시 시도하세요.", 409)
        normalized = normalize_script(script)
        if not normalized or len(normalized) > self.settings.max_script_chars:
            raise AppError("INVALID_SCRIPT", "대본 길이를 확인해 주세요.", 422)
        groups: dict[int, list[str]] = {}
        for token in analyze_script(normalized, 60).timeline:
            groups.setdefault(token["sentence_index"], []).append(token["text"])
        sentences = [" ".join(tokens) for tokens in groups.values()]
        if len(sentences) > 200 or any(len(s) > 1000 for s in sentences):
            raise AppError(
                "SUMMARY_INPUT_TOO_LONG", "200문장 이하, 문장당 1,000자 이하로 나눠 주세요.", 422
            )
        self.busy = True
        self._owner = asyncio.current_task()
        started = time.perf_counter()
        inference = asyncio.create_task(self._run(sentences))
        try:
            items = await asyncio.wait_for(
                asyncio.shield(inference), timeout=self.settings.summary_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise AppError(
                "SUMMARY_TIMEOUT", "요약 시간이 초과되었습니다. 다시 시도하세요.", 504
            ) from exc
        except (OSError, httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise AppError(
                "SUMMARY_FAILED", "요약 모델 실행에 실패했습니다. 다시 시도하세요.", 503
            ) from exc
        finally:

            async def reap() -> None:
                inference.cancel()
                await asyncio.gather(inference, return_exceptions=True)
                await self._stop()

            cleanup = asyncio.create_task(reap())
            cancelled = False
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
            cleanup.result()
            self.busy = False
            self._owner = None
            if cancelled:
                raise asyncio.CancelledError
        return {
            "normalized_script": normalized,
            "sentences": items,
            "model": "Qwen3.5-0.8B Q8_0",
            "elapsed_seconds": time.perf_counter() - started,
        }

    async def _run(self, sentences: list[str]) -> list[dict[str, Any]]:
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
        self._process = spawn.result()
        if cancelled:
            raise asyncio.CancelledError
        # Only this short-lived localhost process receives the script; no proxy or logging.
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False
        ) as client:
            for _ in range(240):
                if self._process.returncode is not None:
                    raise ValueError("Native summary model failed to start")
                try:
                    response = await client.get("/health")
                    if response.status_code == 200 and response.json().get("status") == "ok":
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.25)
            else:
                raise asyncio.TimeoutError()
            items = []
            for index, sentence in enumerate(sentences):
                prompt = INSTRUCTION + "\n<발표문>\n" + sentence + "\n</발표문>\n요지 메모:"
                response = await client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "top_p": 0.8,
                        "top_k": 20,
                        "min_p": 0,
                        "seed": 42,
                        "max_tokens": 160,
                        "stream": False,
                        "cache_prompt": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                response.raise_for_status()
                choice = response.json()["choices"][0]
                hint = choice["message"]["content"]
                valid = (
                    isinstance(hint, str)
                    and bool(hint.strip())
                    and len(hint.strip()) <= 160
                    and choice["finish_reason"] == "stop"
                )
                items.append(
                    {
                        "sentence_index": index,
                        "original": sentence,
                        "hint": hint.strip() if valid else None,
                        "error": None
                        if valid
                        else "요약이 비어 있거나 길이 제한을 넘었습니다. 직접 작성해 주세요.",
                    }
                )
        return items

    def _asset_paths(self) -> tuple[str, str]:
        paths = [Path(self.settings.summary_server_path), Path(self.settings.summary_model_path)]
        if not all(path.is_file() for path in paths):
            raise AppError("SUMMARY_UNAVAILABLE", "요약 모델과 실행 파일을 준비해 주세요.", 503)
        return str(paths[0].resolve()), str(paths[1].resolve())

    async def _stop(self) -> None:
        process = self._process
        if process is not None:
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
            self._process = None

    async def close(self) -> None:
        if self._owner is not None and self._owner is not asyncio.current_task():
            self._owner.cancel()
            await asyncio.gather(self._owner, return_exceptions=True)
        await self._stop()
