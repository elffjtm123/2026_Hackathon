"""Turn an uploaded PDF, DOCX or TXT into plain text for question generation.

The extractor works on bytes in memory only; nothing is written to disk. The real format is
decided from the content (magic bytes), never from the file name alone. Any parser failure
becomes INTERVIEW_DOCUMENT_UNREADABLE so a hostile or broken file can never cause a 500.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from app.core.config import Settings
from app.core.errors import AppError

DocumentFormat = Literal["pdf", "docx", "txt"]


class DocumentKind(str, Enum):
    COVER_LETTER = "cover_letter"  # 자기소개서
    RESUME = "resume"  # 이력서
    PORTFOLIO = "portfolio"  # 포트폴리오


@dataclass(frozen=True)
class DocumentWarning:
    code: Literal["no_text", "truncated"]
    message: str


@dataclass(frozen=True)
class DocumentText:
    kind: DocumentKind
    text: str
    warnings: tuple[DocumentWarning, ...] = ()


def _default(name: str) -> Any:
    """Settings is the single source of the limit defaults."""
    return Settings.model_fields[f"interview_document_{name}"].default


@dataclass(frozen=True)
class DocumentLimits:
    max_bytes: int = _default("max_bytes")
    max_pages: int = _default("max_pages")
    max_chars: int = _default("max_chars")  # total across the files of one request
    max_uncompressed_bytes: int = _default("max_uncompressed_bytes")  # DOCX zip-bomb guard
    max_seconds: float = _default("extract_seconds")  # wall clock for one extract_many call
    max_stream_bytes: int = _default("max_stream_bytes")  # decoded size of one PDF stream

    @classmethod
    def from_settings(cls, settings: Settings) -> DocumentLimits:
        return cls(
            max_bytes=settings.interview_document_max_bytes,
            max_pages=settings.interview_document_max_pages,
            max_chars=settings.interview_document_max_chars,
            max_uncompressed_bytes=settings.interview_document_max_uncompressed_bytes,
            max_seconds=settings.interview_document_extract_seconds,
            max_stream_bytes=settings.interview_document_max_stream_bytes,
        )


_NO_TEXT = DocumentWarning(
    "no_text",
    "문서에서 텍스트를 찾지 못했습니다. 스캔 문서는 읽을 수 없으니 내용을 직접 붙여 넣어 주세요.",
)
_TRUNCATED = DocumentWarning(
    "truncated", "텍스트가 너무 길어 허용 길이까지만 사용합니다. 뒤쪽 내용은 제외되었습니다."
)
_PAGE_NUMBER = re.compile(r"^[-–\s]*\d{1,3}(\s*/\s*\d{1,3})?[-–\s]*$")


def _unreadable() -> AppError:
    return AppError(
        "INTERVIEW_DOCUMENT_UNREADABLE",
        "문서를 읽을 수 없습니다. 파일이 PDF, DOCX, TXT 형식인지 확인해 주세요.",
        422,
    )


def _too_large(message: str = "문서가 너무 큽니다. 더 작은 파일을 올려 주세요.") -> AppError:
    return AppError("INTERVIEW_DOCUMENT_TOO_LARGE", message, 413)


def normalize_text(raw: str) -> str:
    """Collapse runs of spaces, keep line and paragraph breaks (at most one blank line)."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f​﻿]", "", raw)
    lines = (re.sub(r"[ \t 　]+", " ", line).strip() for line in raw.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _detect(data: bytes, extension: str) -> DocumentFormat | None:
    if (
        extension == "txt"
        and b"\x00" not in data[:4096]
        and not data.startswith((b"%PDF-", b"PK\x03\x04"))
    ):
        return "txt"  # a text file may mention %PDF- somewhere in its first KB
    if b"%PDF-" in data[:1024]:
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                return "docx" if "word/document.xml" in archive.namelist() else None
        except zipfile.BadZipFile:
            return None
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" not in data[:4096]:
        return "txt"
    return None


def _decode_text(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp949")  # superset of euc-kr


def _timeout() -> AppError:
    return AppError(
        "INTERVIEW_DOCUMENT_UNREADABLE",
        "문서를 처리하는 데 시간이 너무 오래 걸립니다. "
        "더 단순한 파일을 올리거나 내용을 직접 붙여 넣어 주세요.",
        422,
    )


def _pdf_text(data: bytes, limits: DocumentLimits, expired: Callable[[], bool]) -> str:
    from pypdf import PdfReader, apply_configuration

    # Scoped to this call (a ContextVar), so other pypdf users in the process are unaffected.
    with apply_configuration(
        zlib_maximum_output_length=limits.max_stream_bytes,
        stream_decoding_work_maximum_length=limits.max_stream_bytes * 2,
        maximum_declared_stream_length=limits.max_stream_bytes,
    ):
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise _unreadable()
        if len(reader.pages) > limits.max_pages:
            raise _too_large(f"문서가 {limits.max_pages}쪽을 넘습니다. 쪽수를 줄여 올려 주세요.")
        pages: list[str] = []
        total = 0
        for page in reader.pages:
            if expired():
                raise _timeout()
            lines = (page.extract_text() or "").splitlines()
            # Drop a lone page number at the top or bottom of a page.
            for index in (-1, 0):
                if lines and _PAGE_NUMBER.match(lines[index]):
                    lines.pop(index)
            pages.append("\n".join(lines))
            total += len(pages[-1])
            if total > limits.max_chars * 2:  # far past the budget; stop parsing the rest
                break
        if expired():
            raise _timeout()
        return "\n\n".join(pages)


def _docx_text(data: bytes, limits: DocumentLimits) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(info.file_size for info in archive.infolist()) > limits.max_uncompressed_bytes:
            raise _too_large()
    document = Document(io.BytesIO(data))
    lines: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            lines.append(Paragraph(child, document).text)
        elif child.tag.endswith("}tbl"):
            for row in Table(child, document).rows:
                cells: list[str] = []
                seen: set[int] = set()
                for cell in row.cells:  # merged cells repeat the same underlying cell
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(" ".join(p.text for p in cell.paragraphs).strip())
                lines.append(" | ".join(cells))
    return "\n".join(lines)


class DocumentExtractor:
    """`extract` reads one file; `extract_many` also applies the shared character budget."""

    def __init__(
        self,
        limits: DocumentLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits or DocumentLimits()
        self._clock = clock

    def extract(self, kind: DocumentKind, filename: str, data: bytes) -> DocumentText:
        return self.extract_many([(kind, filename, data)])[0]

    def extract_many(self, files: Sequence[tuple[DocumentKind, str, bytes]]) -> list[DocumentText]:
        """Files are read in order; later files get whatever character budget is left."""
        budget = self.limits.max_chars
        deadline = self._clock() + self.limits.max_seconds

        def expired() -> bool:
            return self._clock() > deadline

        results: list[DocumentText] = []
        for kind, filename, data in files:
            if expired():
                raise _timeout()
            text = self._read(filename, data, expired)
            warnings: list[DocumentWarning] = []
            if len(text) > budget:
                text, warnings = text[:budget].rstrip(), [_TRUNCATED]
            elif not text:
                warnings = [_NO_TEXT]
            budget -= len(text)
            results.append(DocumentText(kind, text, tuple(warnings)))
        return results

    def _read(self, filename: str, data: bytes, expired: Callable[[], bool]) -> str:
        if len(data) > self.limits.max_bytes:
            raise _too_large("파일이 너무 큽니다. 더 작은 파일을 올려 주세요.")
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        detected = _detect(data, extension)
        if detected is None or detected != extension:
            raise _unreadable()
        try:
            if detected == "pdf":
                raw = _pdf_text(data, self.limits, expired)
            elif detected == "docx":
                raw = _docx_text(data, self.limits)
            else:
                raw = _decode_text(data)
        except AppError:
            raise
        except Exception as exc:  # parsers raise many types on hostile or broken input
            raise _unreadable() from exc
        return normalize_text(raw)
