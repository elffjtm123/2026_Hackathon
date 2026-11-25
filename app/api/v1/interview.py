import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, Request, Response
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.responses import StreamingResponse

from app.api.disconnect import disconnected_request
from app.api.local_guard import GuardMessages, require_local_idle_request, require_no_offline_job
from app.core.errors import AppError
from app.modules.interview.composition import Composition
from app.modules.interview.documents import (
    DocumentExtractor,
    DocumentKind,
    DocumentLimits,
    DocumentText,
)
from app.modules.interview.evaluation import InterviewEvaluation
from app.schemas.interview import (
    InterviewDocumentOut,
    InterviewEvaluationOut,
    InterviewPlanOut,
    InterviewPlanRequest,
)

router = APIRouter(tags=["interview"])

DOCUMENT_GUARD = GuardMessages(
    local_mode_required="면접 연습은 로컬 AI 모드에서만 지원합니다.",
    development_only="로컬 개발 화면에서만 면접 연습을 쓸 수 있습니다.",
    practice_active="발표·면접 세션을 종료한 뒤 문서를 올려 주세요.",
    summary_busy="대본 요약을 마친 뒤 문서를 올려 주세요.",
    interview_busy="진행 중인 면접 준비가 끝난 뒤 문서를 올려 주세요.",
)

MAX_DOCUMENTS = 3
_FORM_OVERHEAD_BYTES = 64 * 1024  # multipart boundaries, headers and the `kinds` fields
_FIELD_MAX_BYTES = 256


def _invalid(message: str) -> AppError:
    return AppError("INTERVIEW_DOCUMENT_REQUEST_INVALID", message, 422)


def _too_large() -> AppError:
    return AppError(
        "INTERVIEW_DOCUMENT_TOO_LARGE", "파일이 너무 큽니다. 더 작은 파일을 올려 주세요.", 413
    )


async def read_documents(request: Request, max_file_bytes: int) -> list[tuple[str, str, bytes]]:
    """Parse the multipart body in memory, rejecting oversize files as soon as they cross the limit.

    Starlette's own form parser spools files above 1 MB to a temp file; uploads must never touch
    disk, so this streams the body through python-multipart and keeps each file in a bytearray.
    Returns (kind_value, filename, data) in upload order.
    """
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary:
        raise _invalid("파일은 multipart/form-data로 올려 주세요.")
    body_limit = MAX_DOCUMENTS * max_file_bytes + _FORM_OVERHEAD_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > body_limit:
        raise _too_large()

    files: list[tuple[str, bytes]] = []
    kinds: list[str] = []
    headers: dict[bytes, bytes] = {}
    state: dict[str, Any] = {"field": b"", "value": b"", "part": None}

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state["field"] += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state["value"] += data[start:end]

    def on_header_end() -> None:
        headers[state["field"].lower()] = state["value"]
        state["field"] = state["value"] = b""

    def on_headers_finished() -> None:
        _, disposition = parse_options_header(headers.get(b"content-disposition", b""))
        name = disposition.get(b"name", b"").decode("utf-8", "replace")
        filename = disposition.get(b"filename")
        headers.clear()
        state["part"] = (
            name,
            None if filename is None else filename.decode("utf-8", "replace"),
            bytearray(),
        )

    def on_part_data(data: bytes, start: int, end: int) -> None:
        name, filename, buffer = state["part"]
        buffer += data[start:end]
        if filename is None and len(buffer) > _FIELD_MAX_BYTES:
            raise _invalid("요청 형식이 올바르지 않습니다.")
        if filename is not None and len(buffer) > max_file_bytes:
            raise _too_large()

    def on_part_end() -> None:
        name, filename, buffer = state["part"]
        state["part"] = None
        if filename is not None and name == "files":
            if len(files) >= MAX_DOCUMENTS:
                raise _invalid(f"문서는 한 번에 최대 {MAX_DOCUMENTS}개까지 올릴 수 있습니다.")
            files.append((filename, bytes(buffer)))
        elif filename is None and name == "kinds":
            kinds.append(bytes(buffer).decode("utf-8", "replace"))

    parser = MultipartParser(
        boundary,
        {
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > body_limit:
                raise _too_large()
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError:
        raise _invalid("요청 형식이 올바르지 않습니다.") from None

    if not 1 <= len(files) <= MAX_DOCUMENTS:
        raise _invalid(f"문서를 1~{MAX_DOCUMENTS}개 올려 주세요.")
    if len(kinds) != len(files) or len(set(kinds)) != len(kinds):
        raise _invalid("파일마다 서로 다른 종류(kinds)를 하나씩 지정해 주세요.")
    return [(kind, filename, data) for kind, (filename, data) in zip(kinds, files, strict=True)]


@router.post("/interview/documents", response_model=list[InterviewDocumentOut])
async def extract_interview_documents(request: Request) -> list[dict[str, Any]]:
    """Multipart: repeated `files` parts plus a same-length, same-order list of `kinds` fields
    (cover_letter, resume, portfolio; each at most once). Nothing is stored on the server."""
    settings = request.app.state.settings
    require_local_idle_request(request, DOCUMENT_GUARD)
    require_no_offline_job(request, DOCUMENT_GUARD)

    uploads = await read_documents(request, settings.interview_document_max_bytes)
    parsed: list[tuple[DocumentKind, str, bytes]] = []
    for kind, filename, data in uploads:
        try:
            parsed.append((DocumentKind(kind), filename, data))
        except ValueError:
            raise _invalid(
                "문서 종류는 cover_letter, resume, portfolio 중 하나여야 합니다."
            ) from None
    extractor = DocumentExtractor(DocumentLimits.from_settings(settings))
    # One extraction at a time: a worker thread cannot be cancelled, so cap the CPU it can take.
    async with request.app.state.interview_document_gate:
        results = await asyncio.to_thread(extractor.extract_many, parsed)
    return [
        {
            "kind": item.kind.value,
            "text": item.text,
            "warnings": [{"code": w.code, "message": w.message} for w in item.warnings],
        }
        for item in results
    ]


PLAN_GUARD = GuardMessages(
    local_mode_required="면접 연습은 로컬 AI 모드에서만 지원합니다.",
    development_only="로컬 개발 화면에서만 면접 연습을 쓸 수 있습니다.",
    practice_active="발표·면접 세션을 종료한 뒤 질문을 만들어 주세요.",
    summary_busy="대본 요약을 마친 뒤 질문을 만들어 주세요.",
    interview_busy="진행 중인 면접 준비가 끝난 뒤 질문을 만들어 주세요.",
)
_PLAN_FAILED = "질문 생성에 실패했습니다. 다시 시도하세요."


def _reserve_plan(request: Request) -> None:
    execution = request.app.state.model_execution
    try:
        execution.reserve_offline("interview_plan")
    except ValueError as exc:
        raise AppError(
            str(exc), "모델 정리 또는 진행 중인 작업이 끝난 뒤 시도하세요.", 409
        ) from exc


def _validated_documents(request: Request, payload: InterviewPlanRequest) -> list[DocumentText]:
    limit = request.app.state.settings.interview_document_max_chars
    if sum(len(d.text) for d in payload.documents) > limit:
        raise AppError(
            "INTERVIEW_PLAN_REQUEST_INVALID",
            f"서류 텍스트는 합계 {limit:,}자까지 쓸 수 있습니다.",
            422,
        )
    # Only the model call reads this text; it is neither stored nor logged.
    return [DocumentText(DocumentKind(d.kind), d.text) for d in payload.documents]


async def _make_plan(
    request: Request,
    payload: InterviewPlanRequest,
    documents: list[DocumentText],
    on_progress: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    state = request.app.state
    try:
        plan = await state.interview_llm.plan(
            documents, payload.job, Composition(), payload.exclude_common_ids, on_progress
        )
    except AppError:
        raise
    except Exception as exc:
        # Includes failures the generator did not map; never echo their text (may hold input).
        raise AppError("INTERVIEW_PLAN_FAILED", _PLAN_FAILED, 503) from exc
    interview_id = state.interview_store.create(plan)
    return InterviewPlanOut.model_validate(
        {
            "interview_id": interview_id,
            "questions": [
                {**vars(q), "rubric_items": [r.value for r in q.rubric_items]}
                for q in plan.questions
            ],
            "warnings": plan.warnings,
        }
    ).model_dump()


@router.post("/interview/plans")
async def create_interview_plan(payload: InterviewPlanRequest, request: Request) -> Any:
    """Make the interview questions. `Accept: application/x-ndjson` streams
    `{"event": "progress", "data": {"stage", ...}}` lines and ends with one
    `{"event": "complete", "data": {interview_id, questions, warnings}}` or
    `{"event": "error", "data": {code, message}}` line; otherwise the plan is returned as JSON.

    The model reservation is released only after the generator (and so llama-server) is done,
    also when the client disconnects.
    """
    require_local_idle_request(request, PLAN_GUARD)
    require_no_offline_job(request, PLAN_GUARD)
    documents = _validated_documents(request, payload)
    execution = request.app.state.model_execution
    _reserve_plan(request)
    if "application/x-ndjson" not in request.headers.get("accept", ""):
        try:
            async with disconnected_request(
                request, "INTERVIEW_PLAN_CANCELLED", "연결이 종료되어 질문 생성을 중단했습니다."
            ):
                return await _make_plan(request, payload, documents, None)
        finally:
            execution.release_offline("interview_plan")

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)

    def progress(data: dict[str, Any]) -> None:
        # Progress is advisory: drop frames instead of failing when a slow reader fills the queue.
        try:
            queue.put_nowait({"event": "progress", "data": data})
        except asyncio.QueueFull:
            pass

    async def produce() -> None:
        try:
            result = await _make_plan(request, payload, documents, progress)
            # The terminal frame must never be dropped or the client hangs.
            await queue.put({"event": "complete", "data": result})
        except AppError as exc:
            await queue.put({"event": "error", "data": {"code": exc.code, "message": exc.message}})
        except Exception:
            # Anything else (store, response building) must still end the stream.
            await queue.put(
                {
                    "event": "error",
                    "data": {"code": "INTERVIEW_PLAN_FAILED", "message": _PLAN_FAILED},
                }
            )

    # Started now, not when the response is first iterated, so the reservation is always
    # released: the done callback runs after the generator has exited, even if the task is
    # cancelled before its first step.
    producer = asyncio.create_task(produce())
    producer.add_done_callback(lambda _: execution.release_offline("interview_plan"))

    async def stream() -> AsyncIterator[str]:
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["event"] in {"complete", "error"}:
                    break
        finally:
            producer.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(producer, return_exceptions=True)

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ evaluation

EVALUATION_GUARD = GuardMessages(
    local_mode_required="면접 연습은 로컬 AI 모드에서만 지원합니다.",
    development_only="로컬 개발 화면에서만 면접 연습을 쓸 수 있습니다.",
    practice_active="발표·면접 세션을 종료한 뒤 평가해 주세요.",
    summary_busy="대본 요약을 마친 뒤 평가해 주세요.",
    interview_busy="진행 중인 면접 준비 또는 평가가 끝난 뒤 시도하세요.",
)
_EVALUATION_FAILED = "답변 평가에 실패했습니다. 다시 시도하세요."
_EVALUATION_CANCELLED = "평가를 중단했습니다."


def _evaluation_output(evaluation: InterviewEvaluation) -> dict[str, Any]:
    return InterviewEvaluationOut.model_validate(
        {
            **vars(evaluation),
            "items": [
                {
                    **vars(item),
                    "grades": {k.value: vars(g) for k, g in item.grades.items()},
                    "excluded_items": [k.value for k in item.excluded_items],
                }
                for item in evaluation.items
            ],
            "summary": vars(evaluation.summary),
        }
    ).model_dump()


def _ndjson(lines: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        lines,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _evaluate_stored_items(
    request: Request,
    interview_id: str,
    on_progress: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    """Load the generation model once, evaluate the stored items and keep the result.

    Failures of single model calls are not errors (they become failed items and warnings);
    only a model that cannot start, or an unexpected failure, raises.
    """
    state = request.app.state
    items = list(state.interview_store.get(interview_id).items)

    def progress(stage: str) -> None:
        if on_progress is not None:
            try:
                on_progress({"stage": stage})
            except Exception:
                pass  # advisory, and must not interrupt native-process cleanup

    try:
        progress("loading")
        async with state.local_llm.loaded() as session:
            try:
                evaluation = await state.interview_llm.evaluate(items, session, on_progress)
            finally:
                progress("cleaning")  # llama-server is terminated when this block exits
        output = _evaluation_output(evaluation)
        state.interview_store.set_evaluation(interview_id, evaluation)
        return output
    except AppError as exc:
        if exc.code == "LOCAL_MODEL_UNAVAILABLE":
            raise AppError(
                "INTERVIEW_MODEL_UNAVAILABLE", "로컬 생성 모델과 실행 파일을 준비해 주세요.", 503
            ) from exc
        raise
    except asyncio.TimeoutError as exc:  # llama-server never became ready
        raise AppError(
            "INTERVIEW_EVALUATION_FAILED", "생성 모델이 시작되지 않았습니다. 다시 시도하세요.", 504
        ) from exc
    except Exception as exc:
        # Never echo the text of the failure: it may hold the user's answers.
        raise AppError("INTERVIEW_EVALUATION_FAILED", _EVALUATION_FAILED, 503) from exc


def _start_evaluation(
    request: Request, interview_id: str, job: Callable[[], Coroutine[Any, Any, Any]]
) -> asyncio.Task[Any]:
    """Run `job` as the evaluation of `interview_id` (the caller has reserved the models).

    The task is started now, and the done callback runs after llama-server has been reaped even
    if the task is cancelled: it frees the reservation, the running flag and the DELETE handle.
    """
    state = request.app.state
    state.interview_store.begin_evaluation(interview_id)
    task = asyncio.create_task(job())
    state.interview_evaluations[interview_id] = task

    def finish(done: asyncio.Task[Any]) -> None:
        if state.interview_evaluations.get(interview_id) is done:
            del state.interview_evaluations[interview_id]
        state.interview_store.end_evaluation(interview_id)
        state.model_execution.release_offline("interview_evaluation")

    task.add_done_callback(finish)
    return task


@router.get("/interview/{interview_id}/evaluation")
async def evaluate_interview(interview_id: str, request: Request) -> Any:
    """Evaluate the answers of a finished interview. `Accept: application/x-ndjson` streams
    `{"event": "progress", "data": {"stage", ...}}` lines and ends with one
    `{"event": "complete", "data": <evaluation>}` or `{"event": "error", "data": {code, message}}`
    line; otherwise the evaluation is returned as JSON. A stored result is replayed without the
    model. The model reservation is released only after llama-server is gone, also when the
    client disconnects or the evaluation is cancelled.
    """
    require_local_idle_request(request, EVALUATION_GUARD)
    state = request.app.state
    store = state.interview_store
    stored = store.get(interview_id)
    if not stored.items_saved:
        raise AppError("INTERVIEW_NOT_READY", "면접이 끝난 뒤 평가할 수 있습니다.", 409)
    streaming = "application/x-ndjson" in request.headers.get("accept", "")
    if stored.evaluation is not None:
        result = _evaluation_output(stored.evaluation)
        store.mark_delivered(interview_id)
        if not streaming:
            return result

        async def replay() -> AsyncIterator[str]:
            yield json.dumps({"event": "complete", "data": result}, ensure_ascii=False) + "\n"

        return _ndjson(replay())
    if stored.evaluating:
        raise AppError("INTERVIEW_BUSY", EVALUATION_GUARD.interview_busy, 409)
    require_no_offline_job(request, EVALUATION_GUARD)
    try:
        state.model_execution.reserve_offline("interview_evaluation")
    except ValueError as exc:
        raise AppError(
            str(exc), "모델 정리 또는 진행 중인 작업이 끝난 뒤 시도하세요.", 409
        ) from exc

    if not streaming:
        task: asyncio.Task[Any] | None = None
        try:
            # The disconnect watcher starts before the task: a watcher still starting when the
            # task has already ended hangs its own cancellation behind BaseHTTPMiddleware.
            async with disconnected_request(
                request, "INTERVIEW_EVALUATION_CANCELLED", _EVALUATION_CANCELLED
            ):
                task = _start_evaluation(
                    request,
                    interview_id,
                    lambda: _evaluate_stored_items(request, interview_id, None),
                )
                await asyncio.wait({task})  # a cancelled wait must not cancel the task itself
        finally:
            if task is None:  # never started, so nothing else will free the reservation
                state.model_execution.release_offline("interview_evaluation")
            else:
                task.cancel()
                with CancelScope(shield=True):
                    await asyncio.gather(task, return_exceptions=True)
        if task.cancelled():  # DELETE cancelled it
            raise AppError("INTERVIEW_EVALUATION_CANCELLED", _EVALUATION_CANCELLED, 499)
        result_out: dict[str, Any] = task.result()
        store.mark_delivered(interview_id)
        return result_out

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)

    def progress(data: dict[str, Any]) -> None:
        try:
            queue.put_nowait({"event": "progress", "data": data})
        except asyncio.QueueFull:
            pass  # advisory

    def error_frame(code: str, message: str) -> dict[str, Any]:
        return {"event": "error", "data": {"code": code, "message": message}}

    async def produce() -> None:
        try:
            result = await _evaluate_stored_items(request, interview_id, progress)
            await queue.put({"event": "complete", "data": result})
        except asyncio.CancelledError:
            try:
                queue.put_nowait(
                    error_frame("INTERVIEW_EVALUATION_CANCELLED", _EVALUATION_CANCELLED)
                )
            except asyncio.QueueFull:
                pass
            raise
        except AppError as exc:
            await queue.put(error_frame(exc.code, exc.message))
        except Exception:
            await queue.put(error_frame("INTERVIEW_EVALUATION_FAILED", _EVALUATION_FAILED))

    producer = _start_evaluation(request, interview_id, produce)

    async def stream() -> AsyncIterator[str]:
        try:
            while True:
                event = await queue.get()
                if event["event"] == "complete":
                    store.mark_delivered(interview_id)
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["event"] in {"complete", "error"}:
                    break
        finally:
            producer.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(producer, return_exceptions=True)

    return _ndjson(stream())


@router.delete("/interview/{interview_id}/evaluation", status_code=204)
async def cancel_interview_evaluation(interview_id: str, request: Request) -> Response:
    """Cancel a running evaluation; returns once llama-server is gone and the models are free."""
    require_local_idle_request(request, EVALUATION_GUARD)
    state = request.app.state
    state.interview_store.get(interview_id)  # 404 for an unknown interview
    task = state.interview_evaluations.get(interview_id)
    if task is not None and not task.done():
        task.cancel()
        with CancelScope(shield=True):
            await asyncio.gather(task, return_exceptions=True)
    return Response(status_code=204)
