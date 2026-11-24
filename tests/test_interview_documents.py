"""Seam: DocumentExtractor.extract / extract_many (bytes in, normalized text and warnings out)."""

import io
import zipfile
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfWriter

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.interview.documents import (
    DocumentExtractor,
    DocumentKind,
    DocumentLimits,
)

FIXTURES = Path(__file__).parent / "fixtures" / "interview"


def load(relative: str) -> tuple[str, bytes]:
    path = FIXTURES / relative
    return path.name, path.read_bytes()


def extract(relative: str, kind: DocumentKind = DocumentKind.RESUME, **limits: int):
    name, data = load(relative)
    return DocumentExtractor(DocumentLimits(**limits)).extract(kind, name, data)


def blank_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def error_code(call) -> str:
    with pytest.raises(AppError) as caught:
        call()
    return caught.value.code


def test_pdf_korean_text_is_extracted() -> None:
    result = extract("a_ai_engineer/resume.pdf")
    assert result.kind is DocumentKind.RESUME
    assert "한지우" in result.text
    assert "객체 검출" in result.text
    assert "정보처리기사" in result.text
    assert result.warnings == ()


def test_docx_extracts_paragraphs_and_table_cells_in_document_order() -> None:
    result = extract("b_backend/resume.docx")
    assert "오세진" in result.text
    assert "가상공과대학교" in result.text  # inside a table
    assert "정산 서비스 API 개선" in result.text  # inside a table
    # table 인적사항 comes before the 학력 heading and its table
    assert (
        result.text.index("오세진")
        < result.text.index("학력")
        < result.text.index("가상공과대학교")
    )
    assert "자격" in result.text and result.text.index("가상공과대학교") < result.text.index("SQLD")


def test_docx_table_row_cells_stay_on_one_line() -> None:
    result = extract("c_planning/portfolio.docx", DocumentKind.PORTFOLIO)
    assert any(
        "마케팅 학회 공모전" in line and "기획팀장" in line for line in result.text.splitlines()
    )


def test_txt_is_decoded_and_normalized() -> None:
    result = extract("a_ai_engineer/portfolio.txt", DocumentKind.PORTFOLIO)
    assert "소형 객체 검출 데이터 증강 연구" in result.text
    assert "58%" in result.text


def test_txt_strips_bom_and_falls_back_to_cp949() -> None:
    extractor = DocumentExtractor()
    bom = extractor.extract(DocumentKind.RESUME, "a.txt", "﻿안녕하세요".encode())
    assert bom.text == "안녕하세요"
    legacy = extractor.extract(
        DocumentKind.RESUME, "a.txt", "한글 이력서 내용입니다".encode("cp949")
    )
    assert legacy.text == "한글 이력서 내용입니다"


def test_whitespace_is_normalized_but_paragraphs_are_kept() -> None:
    raw = "첫   문단\t입니다.  \r\n\r\n\r\n\r\n둘째 문단 입니다.\n"
    result = DocumentExtractor().extract(DocumentKind.COVER_LETTER, "a.txt", raw.encode())
    assert result.text == "첫 문단 입니다.\n\n둘째 문단 입니다."


def test_pdf_page_number_only_lines_are_dropped() -> None:
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for number in (1, 2):
        pdf.drawString(72, 700, f"Project {number} overview")
        pdf.drawString(300, 40, f"- {number} -")
        pdf.showPage()
    pdf.save()
    result = DocumentExtractor().extract(DocumentKind.PORTFOLIO, "a.pdf", buffer.getvalue())
    assert "Project 1 overview" in result.text and "Project 2 overview" in result.text
    assert [line for line in result.text.splitlines() if line.strip("- ").isdigit()] == []


def test_format_is_detected_from_content_not_extension() -> None:
    name, data = load("a_ai_engineer/resume.pdf")
    extractor = DocumentExtractor()
    assert error_code(lambda: extractor.extract(DocumentKind.RESUME, "resume.txt", data)) == (
        "INTERVIEW_DOCUMENT_UNREADABLE"
    )
    text = "그냥 텍스트".encode()
    assert error_code(lambda: extractor.extract(DocumentKind.RESUME, "resume.pdf", text)) == (
        "INTERVIEW_DOCUMENT_UNREADABLE"
    )
    docx_name, docx_data = load("b_backend/resume.docx")
    assert error_code(lambda: extractor.extract(DocumentKind.RESUME, "resume.pdf", docx_data)) == (
        "INTERVIEW_DOCUMENT_UNREADABLE"
    )


def test_unknown_formats_are_unreadable() -> None:
    extractor = DocumentExtractor()
    name, data = load("extra/not_a_document.pdf")
    for filename, content in [
        (name, data),
        ("resume.hwp", b"\xd0\xcf\x11\xe0" + bytes(100)),
        ("resume.txt", b"abc\x00def"),
        ("resume.doc", "텍스트".encode()),
    ]:
        assert error_code(
            lambda c=content, f=filename: extractor.extract(DocumentKind.RESUME, f, c)
        ) == ("INTERVIEW_DOCUMENT_UNREADABLE")


def test_zip_that_is_not_docx_is_unreadable() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<x/>")
    code = error_code(
        lambda: DocumentExtractor().extract(DocumentKind.RESUME, "a.docx", buffer.getvalue())
    )
    assert code == "INTERVIEW_DOCUMENT_UNREADABLE"


def test_corrupt_pdf_and_docx_are_unreadable_not_crashes() -> None:
    extractor = DocumentExtractor()
    broken_pdf = b"%PDF-1.7\n" + b"garbage" * 50
    broken_docx = b"PK\x03\x04" + bytes(50)
    assert error_code(lambda: extractor.extract(DocumentKind.RESUME, "a.pdf", broken_pdf)) == (
        "INTERVIEW_DOCUMENT_UNREADABLE"
    )
    assert error_code(lambda: extractor.extract(DocumentKind.RESUME, "a.docx", broken_docx)) == (
        "INTERVIEW_DOCUMENT_UNREADABLE"
    )


def test_image_only_pdf_returns_empty_text_with_no_text_warning() -> None:
    result = extract("extra/image_only.pdf")
    assert result.text == ""
    assert [w.code for w in result.warnings] == ["no_text"]
    assert "직접 붙여" in result.warnings[0].message


def test_empty_txt_has_no_text_warning() -> None:
    result = DocumentExtractor().extract(DocumentKind.RESUME, "a.txt", b"  \n\n ")
    assert result.text == ""
    assert [w.code for w in result.warnings] == ["no_text"]


def test_password_protected_pdf_is_unreadable() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    code = error_code(
        lambda: DocumentExtractor().extract(DocumentKind.RESUME, "a.pdf", buffer.getvalue())
    )
    assert code == "INTERVIEW_DOCUMENT_UNREADABLE"


def test_oversize_bytes_are_too_large() -> None:
    data = b"a" * 30
    with pytest.raises(AppError) as caught:
        DocumentExtractor(DocumentLimits(max_bytes=20)).extract(DocumentKind.RESUME, "a.txt", data)
    error = caught.value
    assert (error.code, error.status_code) == ("INTERVIEW_DOCUMENT_TOO_LARGE", 413)


def test_too_many_pages_are_too_large() -> None:
    extractor = DocumentExtractor(DocumentLimits(max_pages=3))
    assert extractor.extract(DocumentKind.RESUME, "a.pdf", blank_pdf(3)).text == ""
    with pytest.raises(AppError) as caught:
        extractor.extract(DocumentKind.RESUME, "a.pdf", blank_pdf(4))
    assert (caught.value.code, caught.value.status_code) == ("INTERVIEW_DOCUMENT_TOO_LARGE", 413)


def test_docx_zip_bomb_is_rejected_before_parsing() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/media/bomb.bin", bytes(5_000_000))
    assert len(buffer.getvalue()) < 100_000
    extractor = DocumentExtractor(DocumentLimits(max_uncompressed_bytes=1_000_000))
    with pytest.raises(AppError) as caught:
        extractor.extract(DocumentKind.RESUME, "a.docx", buffer.getvalue())
    assert (caught.value.code, caught.value.status_code) == ("INTERVIEW_DOCUMENT_TOO_LARGE", 413)


def test_char_total_is_shared_across_files_and_truncated_with_warning() -> None:
    document = Document()
    document.add_paragraph("가" * 60)
    buffer = io.BytesIO()
    document.save(buffer)
    extractor = DocumentExtractor(DocumentLimits(max_chars=100))
    results = extractor.extract_many(
        [
            (DocumentKind.RESUME, "a.txt", ("나" * 70).encode()),
            (DocumentKind.COVER_LETTER, "b.docx", buffer.getvalue()),
            (DocumentKind.PORTFOLIO, "c.txt", ("다" * 10).encode()),
        ]
    )
    assert [len(r.text) for r in results] == [70, 30, 0]
    assert [[w.code for w in r.warnings] for r in results] == [[], ["truncated"], ["truncated"]]
    assert sum(len(r.text) for r in results) == 100


def test_a_document_exactly_at_the_budget_is_not_truncated() -> None:
    result = DocumentExtractor(DocumentLimits(max_chars=10)).extract_many(
        [(DocumentKind.RESUME, "a.txt", ("가" * 10).encode())]
    )[0]
    assert len(result.text) == 10 and result.warnings == ()


def test_fixture_sets_cover_every_kind_with_key_phrases() -> None:
    expected = {
        "a_ai_engineer/cover_letter.docx": "물체의 재현율",
        "b_backend/cover_letter.txt": "정산 배치",
        "b_backend/portfolio.pdf": "Redis",
        "c_planning/cover_letter.pdf": "기획팀장",
        "c_planning/resume.txt": "문하린",
    }
    for relative, phrase in expected.items():
        assert phrase in extract(relative, DocumentKind.COVER_LETTER).text, relative


def test_short_and_banned_topic_fixtures_are_plain_readable_text() -> None:
    short = extract("extra/short.txt")
    assert 0 < len(short.text) < 80
    banned = extract("extra/banned_topics_cover_letter.txt", DocumentKind.COVER_LETTER)
    for phrase in ("속초", "3남매", "만 27세"):
        assert phrase in banned.text


def test_a_txt_file_may_mention_pdf_markers() -> None:
    text = "메모: %PDF- 는 PDF 파일의 시작 표시입니다.\n프로젝트 설명".encode()
    result = DocumentExtractor().extract(DocumentKind.PORTFOLIO, "notes.txt", text)
    assert "프로젝트 설명" in result.text


def test_limit_defaults_come_from_settings() -> None:
    limits = DocumentLimits()
    settings = Settings(_env_file=None)
    assert limits == DocumentLimits.from_settings(settings)
    assert limits.max_pages == settings.interview_document_max_pages
    assert limits.max_seconds == settings.interview_document_extract_seconds


def test_extraction_stops_at_the_wall_clock_deadline() -> None:
    ticks = iter(range(1_000))
    extractor = DocumentExtractor(DocumentLimits(max_seconds=3), clock=lambda: next(ticks))
    with pytest.raises(AppError) as caught:
        extractor.extract(DocumentKind.RESUME, "a.pdf", blank_pdf(20))
    assert (caught.value.code, caught.value.status_code) == ("INTERVIEW_DOCUMENT_UNREADABLE", 422)
    assert "시간" in caught.value.message


def test_deadline_is_shared_across_files() -> None:
    ticks = iter(range(0, 1_000, 6))  # every clock read advances 6 seconds
    extractor = DocumentExtractor(DocumentLimits(max_seconds=10), clock=lambda: next(ticks))
    files = [(DocumentKind.RESUME, "a.txt", b"hello"), (DocumentKind.PORTFOLIO, "b.txt", b"hi")]
    with pytest.raises(AppError) as caught:
        extractor.extract_many(files)
    assert caught.value.code == "INTERVIEW_DOCUMENT_UNREADABLE"


def padded_content_pdf(padding: int) -> bytes:
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf (HELLO) Tj ET" + b" " * padding)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode(level=9))
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_content_streams_above_the_decode_cap_are_not_decoded() -> None:
    data = padded_content_pdf(3_000_000)  # a few KB on disk, 3 MB once decoded
    assert len(data) < 100_000
    allowed = DocumentExtractor(DocumentLimits(max_stream_bytes=8_000_000))
    assert "HELLO" in allowed.extract(DocumentKind.RESUME, "a.pdf", data).text
    capped = DocumentExtractor(DocumentLimits(max_stream_bytes=1_000_000))
    assert error_code(lambda: capped.extract(DocumentKind.RESUME, "a.pdf", data)) == (
        "INTERVIEW_DOCUMENT_UNREADABLE"
    )
