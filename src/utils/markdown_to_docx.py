"""Turn the project's Markdown documentation into Word documents.

The documentation is written and generated as Markdown because that is what code
can write and what `git diff` can show line by line. Word is what a reader who is
not opening a code editor actually wants. This module bridges the two, so the
Markdown stays the single source and the Word files are built from it rather than
maintained alongside it.

Nothing here is hand-maintained. Editing a `.docx` produced by this module is a
mistake: the next build overwrites it. Edit the Markdown.

Supported Markdown, which is all the project's documents use: headings to three
levels, paragraphs, bullet and numbered lists, tables, fenced code blocks, block
quotes, horizontal rules, and inline bold, italic, code and links.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

# Matches the project palette in src/utils/plotting.py and web/css/base.css.
INK = RGBColor(0x10, 0x26, 0x2B)
ACCENT = RGBColor(0x0E, 0x7C, 0x86)
MUTED = RGBColor(0x5F, 0x7A, 0x80)

BODY_FONT = "Segoe UI"
MONO_FONT = "Consolas"

# Inline markup, resolved in one pass so that bold inside a link, or code inside
# a bullet, does not need a second rule.
INLINE = re.compile(
    r"(\*\*.+?\*\*)"          # bold
    r"|(`[^`]+`)"             # inline code
    r"|(\[[^\]]+\]\([^)]+\))"  # link
    r"|(\*[^*]+\*)"           # italic
)


def _style_document(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.15

    for level, size in ((1, 19), (2, 14), (3, 11.5)):
        style = document.styles[f"Heading {level}"]
        style.font.name = BODY_FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = ACCENT if level == 1 else INK
        style.paragraph_format.space_before = Pt(16 if level == 1 else 12)
        style.paragraph_format.space_after = Pt(5)


def _add_runs(paragraph, text: str) -> None:
    """Write text into a paragraph, honouring inline bold, italic, code and links."""
    position = 0
    for match in INLINE.finditer(text):
        if match.start() > position:
            paragraph.add_run(text[position:match.start()])

        bold, code, link, italic = match.groups()
        if bold:
            paragraph.add_run(bold[2:-2]).bold = True
        elif code:
            run = paragraph.add_run(code[1:-1])
            run.font.name = MONO_FONT
            run.font.size = Pt(9.5)
            run.font.color.rgb = ACCENT
        elif link:
            # The link text alone. A Word hyperlink needs a relationship on the
            # document part, and these mostly point at files inside the repo,
            # which would be broken links for anyone reading the .docx on its own.
            label = re.match(r"\[([^\]]+)\]", link).group(1)
            run = paragraph.add_run(label)
            run.font.color.rgb = ACCENT
        elif italic:
            paragraph.add_run(italic[1:-1]).italic = True

        position = match.end()

    if position < len(text):
        paragraph.add_run(text[position:])


def _add_table(document: Document, rows: list[str]) -> None:
    """Render a Markdown pipe table."""
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = cells(rows[0])
    body = [cells(r) for r in rows[2:]]  # row 1 is the --- separator

    table = document.add_table(rows=1, cols=len(header))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = True

    for cell, text in zip(table.rows[0].cells, header, strict=False):
        cell.text = ""
        paragraph = cell.paragraphs[0]
        run = paragraph.add_run(text)
        run.bold = True
        run.font.size = Pt(9)

    for record in body:
        cells_out = table.add_row().cells
        for cell, text in zip(cells_out, record, strict=False):
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(2)
            _add_runs(paragraph, text)
            for run in paragraph.runs:
                run.font.size = Pt(9)

    document.add_paragraph()


def _add_code_block(document: Document, lines: list[str]) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.25)
    paragraph.paragraph_format.space_before = Pt(4)
    run = paragraph.add_run("\n".join(lines))
    run.font.name = MONO_FONT
    run.font.size = Pt(9)
    run.font.color.rgb = MUTED


def render_markdown(document: Document, markdown: str, heading_offset: int = 0) -> None:
    """Append one Markdown document to an open Word document.

    `heading_offset` pushes every heading down a level, so several documents can
    be combined under one report title without three competing Heading 1s.
    """
    lines = markdown.split("\n")
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # fenced code
        if stripped.startswith("```"):
            block = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            _add_code_block(document, block)
            index += 1
            continue

        # table
        if stripped.startswith("|") and index + 1 < len(lines) and set(lines[index + 1].strip()) <= set("|-: "):
            block = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            if len(block) >= 2:
                _add_table(document, block)
            continue

        # headings
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = min(len(heading.group(1)) + heading_offset, 4)
            paragraph = document.add_heading("", level=level)
            _add_runs(paragraph, heading.group(2))
            index += 1
            continue

        # horizontal rule: a spacer, not a line, which Word renders badly
        if stripped in {"---", "***", "___"}:
            document.add_paragraph()
            index += 1
            continue

        # block quote
        if stripped.startswith(">"):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Inches(0.3)
            _add_runs(paragraph, stripped.lstrip("> ").strip())
            for run in paragraph.runs:
                run.italic = True
                run.font.color.rgb = MUTED
            index += 1
            continue

        # bullet
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            paragraph = document.add_paragraph(style="List Bullet")
            _add_runs(paragraph, bullet.group(1))
            index += 1
            continue

        # numbered
        numbered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if numbered:
            paragraph = document.add_paragraph(style="List Number")
            _add_runs(paragraph, numbered.group(1))
            index += 1
            continue

        # blank
        if not stripped:
            index += 1
            continue

        # paragraph, joining wrapped lines until a blank or a new block
        block = [stripped]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if not nxt or re.match(r"^(#{1,6}\s|[-*+]\s|\d+[.)]\s|\||>|```)", nxt) or nxt in {"---", "***", "___"}:
                break
            block.append(nxt)
            index += 1

        paragraph = document.add_paragraph()
        _add_runs(paragraph, " ".join(block))

    return None


def new_document() -> Document:
    document = Document()
    _style_document(document)
    section = document.sections[0]
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    section.top_margin = Inches(0.9)
    section.bottom_margin = Inches(0.9)
    return document


def title_page(document: Document, title: str, subtitle: str, meta: list[str]) -> None:
    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = heading.add_run(title)
    run.bold = True
    run.font.size = Pt(26)
    run.font.color.rgb = ACCENT

    sub = document.add_paragraph()
    run = sub.add_run(subtitle)
    run.font.size = Pt(12.5)
    run.font.color.rgb = MUTED

    document.add_paragraph()
    for line in meta:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(2)
        run = paragraph.add_run(line)
        run.font.size = Pt(9.5)
        run.font.color.rgb = MUTED


def convert_file(source: Path, target: Path, title: str, subtitle: str, meta: list[str]) -> Path:
    """Convert one Markdown file to a standalone Word document."""
    document = new_document()
    title_page(document, title, subtitle, meta)
    document.add_paragraph()

    # Drop the Markdown's own leading H1. The title page above already carries
    # the document name, and printing it twice reads as a mistake.
    body = source.read_text(encoding="utf-8")
    if body.startswith("# "):
        body = body.split("\n", 1)[1]

    render_markdown(document, body, heading_offset=0)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target)
    return target
