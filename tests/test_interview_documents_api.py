"""Seam: POST /api/v1/interview/documents (multipart `files` + parallel `kinds`)."""

import tempfile
from pathlib import Path

import pytest
import starlette.formparsers
from fastapi.testclient import TestClient

from app.modules.interview.documents import DocumentExtractor

URL = "/api/v1/interview/documents"
ORIGIN = {"Origin": "http://testserver"}
FIXTURES = Path(__file__).parent / "fixtures" / "interview"
THREE = [
    ("resume", "a_ai_engineer/resume.pdf"),
    ("cover_letter", "a_ai_engineer/cover_letter.docx"),
    ("portfolio", "a_ai_engineer/portfolio.txt"),
]


def upload(client: TestClient, parts: list[tuple[str, str, bytes]], headers=ORIGIN):
    """parts: (kind, filename, data)."""
    return client.post(
        URL,
        headers=headers,
        files=[("files", (name, data)) for _, name, data in parts],
        data={"kinds": [kind for kind, _, _ in parts]},
    )


def fixture_parts(selection=THREE) -> list[tuple[str, str, bytes]]:
    return [(kind, Path(rel).name, (FIXTURES / rel).read_bytes()) for kind, rel in selection]


def code(response) -> str:
    return response.json()["error"]["code"]


def test_three_fixtures_return_kind_text_and_warnings(client: TestClient) -> None:
    response = upload(client, fixture_parts())
    assert response.status_code == 200
    body = response.json()
    assert [item["kind"] for item in body] == ["resume", "cover_letter", "portfolio"]
    assert "한지우" in body[0]["text"]
    assert "물체의 재현율" in body[1]["text"]
    assert "소형 객체 검출 데이터 증강 연구" in body[2]["text"]
    assert all(item["warnings"] == [] for item in body)


def test_warnings_are_reported_per_file(client: TestClient) -> None:
    parts = [("resume", "image_only.pdf", (FIXTURES / "extra/image_only.pdf").read_bytes())]
    body = upload(client, parts).json()
    assert body[0]["text"] == ""
    assert body[0]["warnings"][0]["code"] == "no_text"
    assert "붙여" in body[0]["warnings"][0]["message"]


def test_requires_local_ai_mode(client: TestClient) -> None:
    client.app.state.settings.ai_mode = "http"
    response = upload(client, fixture_parts(THREE[:1]))
    assert (response.status_code, code(response)) == (409, "LOCAL_MODE_REQUIRED")


def test_requires_allowed_origin(client: TestClient) -> None:
    for headers in ({}, {"Origin": "https://evil.example"}):
        response = upload(client, fixture_parts(THREE[:1]), headers=headers)
        assert (response.status_code, code(response)) == (403, "DEVELOPMENT_ONLY")


def test_blocked_while_practicing(client: TestClient) -> None:
    client.app.state.live_sessions.add("test-session")
    response = upload(client, fixture_parts(THREE[:1]))
    assert (response.status_code, code(response)) == (409, "PRACTICE_ACTIVE")


@pytest.mark.parametrize(
    ("owner", "expected"),
    [
        ("summary", "SUMMARY_BUSY"),
        ("interview_plan", "INTERVIEW_BUSY"),
        ("interview_evaluation", "INTERVIEW_BUSY"),
    ],
)
def test_blocked_while_an_offline_job_owns_the_models(
    client: TestClient, owner: str, expected: str
) -> None:
    client.app.state.model_execution.owner = owner
    response = upload(client, fixture_parts(THREE[:1]))
    assert (response.status_code, code(response)) == (409, expected)


def test_more_than_three_files_are_rejected(client: TestClient) -> None:
    parts = [("resume", "a.txt", b"x")] * 4
    response = upload(client, parts)
    assert (response.status_code, code(response)) == (422, "INTERVIEW_DOCUMENT_REQUEST_INVALID")


@pytest.mark.parametrize(
    "kinds",
    [[], ["resume", "resume"], ["resume", "diary"], ["resume"]],
    ids=["no-kinds", "duplicate-kind", "unknown-kind", "fewer-kinds-than-files"],
)
def test_bad_kinds_are_rejected(client: TestClient, kinds: list[str]) -> None:
    response = client.post(
        URL,
        headers=ORIGIN,
        files=[("files", ("a.txt", b"hello")), ("files", ("b.txt", b"hello"))],
        data={"kinds": kinds} if kinds else {},
    )
    assert response.status_code == 422
    assert code(response) in {"INTERVIEW_DOCUMENT_REQUEST_INVALID", "VALIDATION_ERROR"}


def test_no_files_is_rejected(client: TestClient) -> None:
    response = client.post(URL, headers=ORIGIN, data={"kinds": ["resume"]})
    assert response.status_code == 422


def test_unreadable_file_is_422_with_korean_message(client: TestClient) -> None:
    parts = [("resume", "resume.pdf", (FIXTURES / "extra/not_a_document.pdf").read_bytes())]
    response = upload(client, parts)
    assert (response.status_code, code(response)) == (422, "INTERVIEW_DOCUMENT_UNREADABLE")
    assert "문서" in response.json()["error"]["message"]


def test_oversize_file_is_413_without_buffering_it_all(client: TestClient) -> None:
    client.app.state.settings.interview_document_max_bytes = 1_000
    response = upload(client, [("resume", "a.txt", b"a" * 5_000)])
    assert (response.status_code, code(response)) == (413, "INTERVIEW_DOCUMENT_TOO_LARGE")


def test_oversize_declared_body_is_rejected_before_reading(client: TestClient) -> None:
    client.app.state.settings.interview_document_max_bytes = 1_000
    response = client.post(
        URL,
        headers={**ORIGIN, "Content-Type": "multipart/form-data; boundary=x"},
        content=b"x" * 500_000,
    )
    assert (response.status_code, code(response)) == (413, "INTERVIEW_DOCUMENT_TOO_LARGE")


def test_char_budget_comes_from_settings(client: TestClient) -> None:
    client.app.state.settings.interview_document_max_chars = 50
    body = upload(client, [("resume", "a.txt", ("가" * 80).encode())]).json()
    assert len(body[0]["text"]) == 50
    assert body[0]["warnings"][0]["code"] == "truncated"


def test_uploads_are_never_spooled_to_disk(client: TestClient, monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("upload was written to disk")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", refuse)
    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", refuse)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", refuse)
    monkeypatch.setattr(tempfile, "TemporaryFile", refuse)
    big = ("가나다라 " * 500_000).encode()  # ~5MB, well past Starlette's 1MB spool threshold
    assert len(big) > 4_000_000
    response = upload(client, [("resume", "big.txt", big)])
    assert response.status_code == 200
    assert response.json()[0]["warnings"][0]["code"] == "truncated"


def multipart(body: bytes, boundary: str = "x"):
    return {"Content-Type": f"multipart/form-data; boundary={boundary}", **ORIGIN}, body


@pytest.mark.parametrize(
    "body",
    [
        b"--x\r\nNoColonHeader\r\n\r\nhello\r\n--x--\r\n",
        b"this is not multipart at all",
        b'--x\r\nContent-Disposition: form-data; name="files"; filename="a.txt"\r\n'
        + b"X-Pad: "
        + b"a" * 20_000_000
        + b"\r\n\r\nhello\r\n--x--\r\n",
    ],
    ids=["header-without-colon", "no-boundary", "huge-part-header"],
)
def test_malformed_multipart_is_a_4xx_not_a_500(client: TestClient, body: bytes) -> None:
    headers, content = multipart(body)
    response = client.post(URL, headers=headers, content=content)
    assert 400 <= response.status_code < 500
    assert code(response) in {"INTERVIEW_DOCUMENT_REQUEST_INVALID", "INTERVIEW_DOCUMENT_TOO_LARGE"}


class ExtractorMustNotRun:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("the upload guard should have rejected this before extraction")


def test_per_file_cap_rejects_while_streaming_not_after_extraction(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr("app.api.v1.interview.DocumentExtractor", ExtractorMustNotRun)
    client.app.state.settings.interview_document_max_bytes = 1_000
    response = upload(client, [("resume", "a.txt", b"a" * 5_000)])
    assert (response.status_code, code(response)) == (413, "INTERVIEW_DOCUMENT_TOO_LARGE")


def test_streaming_body_cap_applies_without_content_length(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.interview.DocumentExtractor", ExtractorMustNotRun)
    client.app.state.settings.interview_document_max_bytes = 1_000
    # Preamble bytes before the first boundary are ignored by the parser, so only the body cap
    # can stop this stream; a generator body is sent chunked, with no Content-Length.
    valid = (
        b'--x\r\nContent-Disposition: form-data; name="files"; filename="a.txt"\r\n\r\nhi\r\n'
        b'--x\r\nContent-Disposition: form-data; name="kinds"\r\n\r\nresume\r\n--x--\r\n'
    )

    def body():
        for _ in range(100):
            yield b"p" * 4_000
        yield valid

    headers, _ = multipart(b"")
    response = client.post(URL, headers=headers, content=body())
    assert (response.status_code, code(response)) == (413, "INTERVIEW_DOCUMENT_TOO_LARGE")


def test_declared_content_length_is_rejected_without_reading_the_body(
    client: TestClient, monkeypatch
) -> None:
    async def refuse(self):
        raise AssertionError("body was read")
        yield b""

    monkeypatch.setattr("starlette.requests.Request.stream", refuse)
    client.app.state.settings.interview_document_max_bytes = 1_000
    headers, content = multipart(b"x" * 500_000)
    response = client.post(URL, headers=headers, content=content)
    assert (response.status_code, code(response)) == (413, "INTERVIEW_DOCUMENT_TOO_LARGE")


def test_kinds_field_is_capped_at_256_bytes(client: TestClient) -> None:
    response = client.post(
        URL,
        headers=ORIGIN,
        files=[("files", ("a.txt", b"hello"))],
        data={"kinds": "r" * 300},
    )
    assert (response.status_code, code(response)) == (422, "INTERVIEW_DOCUMENT_REQUEST_INVALID")
    assert "요청 형식" in response.json()["error"]["message"]


def test_extraction_runs_one_at_a_time(client: TestClient, monkeypatch) -> None:
    import threading
    import time

    active = 0
    peak = 0
    lock = threading.Lock()
    real = DocumentExtractor.extract_many

    def slow(self, files):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.2)
        try:
            return real(self, files)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(DocumentExtractor, "extract_many", slow)
    results: list[int] = []

    threads = [
        threading.Thread(
            target=lambda: results.append(upload(client, fixture_parts(THREE[2:])).status_code)
        )
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [200, 200, 200]
    assert peak == 1
