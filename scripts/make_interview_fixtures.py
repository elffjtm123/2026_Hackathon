"""Build the interview sample documents (PDF/DOCX/TXT) from the reviewable sources.

Sources live in tests/fixtures/interview/src as Markdown-ish text. All people in them are
fictional. Usage: .venv310/bin/python scripts/make_interview_fixtures.py

The PDFs need reportlab (dev tool only, not an app dependency). They use reportlab's built-in
CID font HYSMyeongJo-Medium, which is referenced by name and never embedded, so no font data
ends up in the repository.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "interview"
SOURCES = FIXTURES / "src"

# set directory -> {document name: output extension}; each set covers PDF, DOCX and TXT.
LAYOUT: dict[str, dict[str, str]] = {
    "a_ai_engineer": {"resume": "pdf", "cover_letter": "docx", "portfolio": "txt"},
    "b_backend": {"resume": "docx", "cover_letter": "txt", "portfolio": "pdf"},
    "c_frontend": {"resume": "txt", "cover_letter": "pdf", "portfolio": "docx"},
}


def parse(source: str) -> list[tuple[str, object]]:
    """Blocks: ("h1"|"h2"|"bullet"|"sub"|"para", text) and ("table", rows)."""
    blocks: list[tuple[str, object]] = []
    rows: list[list[str]] = []

    def flush() -> None:
        if rows:
            blocks.append(("table", list(rows)))
            rows.clear()

    for line in source.splitlines():
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r"-+", cell) for cell in cells):
                rows.append(cells)
            continue
        flush()
        if not line.strip():
            continue
        if line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
        elif line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
        elif line.startswith("  - "):
            blocks.append(("sub", line[4:].strip()))
        elif line.startswith("- "):
            blocks.append(("bullet", line[2:].strip()))
        else:
            blocks.append(("para", line.strip()))
    flush()
    return blocks


def write_txt(blocks: list[tuple[str, object]], path: Path) -> None:
    lines: list[str] = []
    for kind, value in blocks:
        if kind == "table":
            assert isinstance(value, list)
            lines.extend(" | ".join(row) for row in value)
        elif kind == "bullet":
            lines.append(f"- {value}")
        elif kind == "sub":
            lines.append(f"  - {value}")
        else:
            lines.append(str(value))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_docx(blocks: list[tuple[str, object]], path: Path) -> None:
    from docx import Document

    document = Document()
    for kind, value in blocks:
        if kind == "h1":
            document.add_heading(str(value), level=0)
        elif kind == "h2":
            document.add_heading(str(value), level=1)
        elif kind in ("bullet", "sub"):
            document.add_paragraph(str(value), style="List Bullet")
        elif kind == "table":
            assert isinstance(value, list)
            table = document.add_table(rows=len(value), cols=max(len(r) for r in value))
            table.style = "Table Grid"
            for r, row in enumerate(value):
                for c, text in enumerate(row):
                    table.cell(r, c).text = text
        else:
            document.add_paragraph(str(value))
    document.save(path)


def write_pdf(blocks: list[tuple[str, object]], path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))

    def style(name: str, size: int, **kw: object) -> ParagraphStyle:
        return ParagraphStyle(
            name, fontName="HYSMyeongJo-Medium", fontSize=size, leading=size * 1.5, **kw
        )

    styles = {
        "h1": style("h1", 20, spaceAfter=8),
        "h2": style("h2", 14, spaceBefore=10, spaceAfter=4),
        "para": style("para", 10, wordWrap="CJK", spaceAfter=4),
        "bullet": style("bullet", 10, wordWrap="CJK", leftIndent=10),
        "sub": style("sub", 10, wordWrap="CJK", leftIndent=24),
        "cell": style("cell", 9, wordWrap="CJK"),
    }

    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story: list[object] = []
    for kind, value in blocks:
        if kind == "table":
            assert isinstance(value, list)
            data = [[Paragraph(escape(c), styles["cell"]) for c in row] for row in value]
            table = Table(data)
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey)]))
            story += [table, Spacer(1, 4 * mm)]
        else:
            prefix = "- " if kind in ("bullet", "sub") else ""
            story.append(Paragraph(prefix + escape(str(value)), styles[kind]))
    SimpleDocTemplate(str(path), pagesize=A4, title="sample (fictional)").build(story)


def write_image_only_pdf(path: Path) -> None:
    """A page with only vector shapes: stands in for a scanned PDF with no text layer."""
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path))
    pdf.rect(80, 400, 300, 200, fill=1)
    pdf.line(80, 300, 500, 300)
    pdf.save()


WRITERS = {"txt": write_txt, "docx": write_docx, "pdf": write_pdf}


def main() -> None:
    for set_name, files in LAYOUT.items():
        out_dir = FIXTURES / set_name
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, extension in files.items():
            source = (SOURCES / set_name / f"{name}.md").read_text(encoding="utf-8")
            WRITERS[extension](parse(source), out_dir / f"{name}.{extension}")
    extra = FIXTURES / "extra"
    extra.mkdir(parents=True, exist_ok=True)
    for name in ("short.txt", "banned_topics_cover_letter.txt"):
        shutil.copyfile(SOURCES / "extra" / name, extra / name)
    write_image_only_pdf(extra / "image_only.pdf")
    # Not a document at all, only named like one.
    (extra / "not_a_document.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))


if __name__ == "__main__":
    main()
