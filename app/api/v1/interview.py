import asyncio
from typing import Any

from fastapi import APIRouter, Request
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from app.api.local_guard import GuardMessages, require_local_idle_request, require_no_offline_job
from app.core.errors import AppError
from app.modules.interview.documents import DocumentExtractor, DocumentKind, DocumentLimits
from app.schemas.interview import InterviewDocumentOut

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
