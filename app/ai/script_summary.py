"""On-demand sentence hints; the native model never remains loaded after a request."""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.ai.local_llm import LlmSession, LocalLlm, terminate_process
from app.ai.model_execution import ModelExecution
from app.core.config import Settings
from app.core.errors import AppError
from app.modules.script_sync.service import analyze_script, normalize_script

INSTRUCTION = """발표자가 내용을 떠올릴 수 있도록 인접 문장들을 의미 단위로 묶고 요약하세요.
같은 대상의 주장과 부연, 문제와 해결, 인사와 소개는 하나의 묶음으로 만드세요.
짧은 문장마다 따로 요약하지 마세요. 독립적인 주제나 중요한 주장이 바뀌면 나누세요.
같은 서비스 이야기여도 기능 소개와 보정 시간 개선은 다른 주제입니다.
한 힌트에 여러 독립적인 정보를 나열하게 되면 묶음을 나누세요.
입력 문장 번호는 0부터 시작합니다. 모든 문장을 순서대로 정확히 한 번 포함하세요.
start_sentence, end_sentence는 포함 범위입니다. 떨어진 문장을 합치지 마세요.
hint는 대상과 핵심 행동을 연결한 짧은 한 줄 메모(권장 20~70자, 최대160자)입니다.
부정·조건·수치·고유명사·완료와 계획의 구분은 보존하고 없는 내용은 만들지 마세요.
원문을 반복하지 말고 JSON만 출력하세요.
예시 입력: [0] 문제가 있었습니다. [1] 짧은 답변이 누락됐습니다. [2] STT를 교체해 해결했습니다.
예시 출력: {"groups":[{"start_sentence":0,"end_sentence":2,
"hint":"짧은 답변 누락 문제 → STT 교체로 해결"}]}"""


class LocalScriptSummarizer:
    def __init__(self, settings: Settings, execution: ModelExecution | None = None) -> None:
        self.settings = settings
        self.execution = execution
        self.llm = LocalLlm(settings)
        self.busy = False
        self._process: asyncio.subprocess.Process | None = None
        self._owner: asyncio.Task[Any] | None = None
        self._progress: Callable[[dict[str, Any]], None] | None = None
        self._total = 0
        self._completed = 0
        self._failed = 0

    async def summarize(
        self, script: str, on_progress: Callable[[dict[str, Any]], None] | None = None
    ) -> dict[str, Any]:
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
        if self.execution is not None:
            try:
                self.execution.reserve_summary()
            except ValueError as exc:
                raise AppError(
                    str(exc), "모델 정리 또는 진행 중인 세션이 끝난 뒤 시도하세요.", 409
                ) from exc
        self.busy = True
        self._progress = on_progress
        self._total, self._completed, self._failed = len(sentences), 0, 0
        self._notify("preparing")
        self._owner = asyncio.current_task()
        started = time.perf_counter()
        inference = asyncio.create_task(self._run(sentences))
        try:
            items = await asyncio.wait_for(
                asyncio.shield(inference), timeout=self.settings.summary_timeout_seconds
            )
        except AppError as exc:
            if exc.code != "LOCAL_MODEL_UNAVAILABLE":
                raise
            raise AppError(
                "SUMMARY_UNAVAILABLE", "요약 모델과 실행 파일을 준비해 주세요.", 503
            ) from exc
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
                self._notify("cleaning")
                await self._stop()

            cleanup = asyncio.create_task(reap())
            cancelled = False
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
            cleanup.result()
            if self.execution is not None:
                self.execution.release_summary()
            self.busy = False
            self._owner = None
            self._progress = None
            if cancelled:
                raise asyncio.CancelledError
        return {
            "normalized_script": normalized,
            "groups": items,
            "model": "Qwen3.5-9B Q4_K_M",
            "elapsed_seconds": time.perf_counter() - started,
        }

    def _notify(self, stage: str) -> None:
        if self._progress is not None:
            # A broken observer must not interrupt native-process cleanup.
            try:
                self._progress(
                    {
                        "stage": stage,
                        "completed_sentences": self._completed,
                        "total_sentences": self._total,
                        "failed_sentences": self._failed,
                    }
                )
            except Exception:
                pass

    @staticmethod
    def _group(raw: Any, sentences: list[str], expected: int, limit: int) -> dict[str, Any]:
        if not isinstance(raw, dict) or set(raw) != {"start_sentence", "end_sentence", "hint"}:
            raise ValueError("Invalid summary group")
        start, end, hint = raw["start_sentence"], raw["end_sentence"], raw["hint"]
        if (
            type(start) is not int
            or type(end) is not int
            or start != expected
            or not start <= end < limit
            or not isinstance(hint, str)
            or not 0 < len(hint.strip()) <= 160
        ):
            raise ValueError("Invalid summary range or hint")
        return {
            "start_sentence": start,
            "end_sentence": end,
            "original": " ".join(sentences[start : end + 1]),
            "hint": hint.strip(),
            "error": None,
        }

    async def _batch(
        self, client: httpx.AsyncClient, prompt: str, sentences: list[str], start: int, end: int
    ) -> list[dict[str, Any]]:
        return await self._summarize_batch(LlmSession(client), prompt, sentences, start, end)

    async def _summarize_batch(
        self, session: LlmSession, prompt: str, sentences: list[str], start: int, end: int
    ) -> list[dict[str, Any]]:
        schema = {
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": end - start,
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_sentence": {
                                "type": "integer",
                                "minimum": start,
                                "maximum": end - 1,
                            },
                            "end_sentence": {
                                "type": "integer",
                                "minimum": start,
                                "maximum": end - 1,
                            },
                            "hint": {"type": "string", "minLength": 1, "maxLength": 160},
                        },
                        "required": ["start_sentence", "end_sentence", "hint"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["groups"],
            "additionalProperties": False,
        }
        items: list[dict[str, Any]] = []
        text, position = "", None
        decoder = json.JSONDecoder()

        def on_delta(delta: str) -> None:
            nonlocal text, position
            text += delta
            if position is None:
                opening = text.find("[")
                if opening < 0:
                    return
                position = opening + 1
            while True:
                while position < len(text) and text[position] in " \r\n\t,":
                    position += 1
                if position == len(text) or text[position] == "]":
                    break
                try:
                    raw, consumed = decoder.raw_decode(text, position)
                except json.JSONDecodeError:
                    break
                item = self._group(
                    raw, sentences, items[-1]["end_sentence"] + 1 if items else start, end
                )
                items.append(item)
                position = consumed
                self._completed = item["end_sentence"] + 1
                self._total = len(sentences)
                self._notify("generating")

        document = await session.complete_json(
            prompt, schema, max_tokens=1536, on_delta=on_delta, schema_name="summary"
        )
        if (
            not isinstance(document, dict)
            or set(document) != {"groups"}
            or not isinstance(document["groups"], list)
            or len(document["groups"]) != len(items)
            or not items
            or items[-1]["end_sentence"] != end - 1
        ):
            raise ValueError("Incomplete summary groups")
        return items

    async def _run(self, sentences: list[str]) -> list[dict[str, Any]]:
        async with self.llm.loaded() as session:
            try:
                items: list[dict[str, Any]] = []
                self._notify("generating")
                start = 0
                while start < len(sentences):
                    # shortcut: no cross-batch groups; add overlap if real scripts need it.
                    end = min(start + 16, len(sentences))
                    while True:
                        prompt = (
                            INSTRUCTION
                            + "\n<발표문>\n"
                            + "\n".join(f"[{i}] {sentences[i]}" for i in range(start, end))
                            + "\n</발표문>"
                        )
                        count = await session.count_tokens(prompt)
                        if count <= 2304 or end - start == 1:
                            break
                        end = start + (end - start) // 2
                    try:
                        if count > 2304:
                            raise ValueError("Sentence exceeds context budget")
                        batch = await self._summarize_batch(session, prompt, sentences, start, end)
                    except (ValueError, KeyError, IndexError, TypeError):
                        batch = [
                            {
                                "start_sentence": start,
                                "end_sentence": end - 1,
                                "original": " ".join(sentences[start:end]),
                                "hint": None,
                                "error": "이 구간 요약 실패: 직접 작성하거나 다시 시도하세요.",
                            }
                        ]
                        self._failed += end - start
                    items.extend(batch)
                    self._completed = end
                    self._notify("generating")
                    start = end
            finally:
                # Announce cleanup before loaded() terminates the server on exit.
                self._notify("cleaning")
        return items

    async def _stop(self) -> None:
        # loaded() already reaps its child; this covers a process handed in from elsewhere.
        process = self._process
        if process is not None:
            await terminate_process(process)
            self._process = None

    async def close(self) -> None:
        if self._owner is not None and self._owner is not asyncio.current_task():
            self._owner.cancel()
            await asyncio.gather(self._owner, return_exceptions=True)
        await self._stop()
