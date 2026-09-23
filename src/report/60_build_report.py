"""Build the Word documents: one combined report plus one file per document.

Reads  : docs/*.md (the generated documents)
         docs/word/*.docx (the authored documents)
         outputs/tables/retail_recommendation.csv
Writes : docs/word/Data_Wizardry_Report.docx   (everything, in reading order)
         docs/word/<generated document>.docx   (rebuilt each run)
Runtime: a few seconds.

**Two kinds of document, and the difference matters.**

*Generated* documents are written by code and hold results. findings.md is
rewritten by every analysis script, data_dictionary.md by 19_data_dictionary.py,
build_log.md as modules complete. They exist as Markdown because that is what
code can write and what `git diff` can show a line at a time, and this script
converts each into Word. Editing one of those .docx files is a mistake: the next
run overwrites it. Edit the analysis, or the Markdown.

*Authored* documents hold reasoning rather than results: the methods note, the
ethics note and the open questions. No script can produce the judgement in them,
so they live as Word only and this script never writes them. Edit them directly
in Word, like any other document. They are merged into the combined report as
they are.

That split is the whole design. A results document that a person can edit will
eventually disagree with the data. A reasoning document that a script can
overwrite will eventually lose the reasoning.

**Run it last.** The generated documents change whenever an analysis runs, so
building the report at the end of the pipeline keeps the Word files current.

**Why src/report rather than src/analysis.** Section 4 names six script folders
and analysis is numbered 20 to 29, which is full. This produces a deliverable
rather than an analysis, so it gets its own folder and number range. Recorded in
the open questions document.
"""

from __future__ import annotations

import copy
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from src.utils.config import path, repo_root
from src.utils.io import relative
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue
from src.utils.markdown_to_docx import (
    ACCENT,
    convert_file,
    new_document,
    render_markdown,
    title_page,
)

SCRIPT = "60_build_report"
logger = get_logger(SCRIPT)

WORD_DIR = repo_root() / "docs" / "word"

# Written by code, as Markdown, and converted here. Overwritten every run.
GENERATED = [
    ("findings.md", "Findings", "What the analysis found, with the evidence and the uncertainty for each."),
    ("data_dictionary.md", "Data dictionary", "Every column of every processed table."),
    ("build_log.md", "Build log", "What each module produced, and what it skipped."),
]

# Written by a person, as Word, and never touched by this script. Merged into the
# combined report exactly as they are.
AUTHORED = [
    ("methods.docx", "Methods and assumptions", "How I did it, and every assumption in one place."),
    ("ethics.docx", "Ethics, security and trust", "How I obtained, protected and interpreted the data."),
    ("open_questions.docx", "Open questions", "Decisions reserved for a person, and the default I am using meanwhile."),
    ("build_walkthrough.docx", "How I built this project",
     "The whole build from an empty folder, and what every file is for."),
]

# Reading order for the combined report: the answer, then how it was reached,
# then what was assumed, then governance, then the decisions still open, then the
# reference material. A reader who stops after two sections still has the answer.
#
# build_walkthrough.docx is authored but deliberately absent from this list. It
# is addressed to someone rebuilding the project, not to someone reading the
# recommendation, and folding a construction narrative into a business report
# would serve neither reader. It ships as a standalone document.
ORDER = ["findings.md", "methods.docx", "ethics.docx", "open_questions.docx",
         "data_dictionary.md", "build_log.md"]


def headline_recommendation() -> tuple[str, list[str]]:
    """The one-paragraph answer, read from the retail module's own output.

    Pulled from the table rather than typed, so the cover of the report cannot
    disagree with the analysis inside it.
    """
    table = path("outputs_tables", "retail_recommendation.csv")
    if not table.exists():
        log_data_issue(
            SCRIPT, "report",
            "retail_recommendation.csv is missing, so the report has no headline figure",
            "run src/retail/40_retail_recommendation.py first",
        )
        return "", []

    row = pd.read_csv(table).iloc[0]
    summary = (
        f"Commit a wizarding category buy of "
        f"${row['recommended_buy_cad_retail']:,.0f} at retail for November 2026 to March 2027, "
        f"about {row['recommended_units']:,.0f} units, and hold "
        f"{row['january_reserve_share']:.0%} of it for a January position rather than committing "
        f"it to the pre-Christmas window as this category normally would."
    )
    supporting = [
        f"Defensible range: ${row['low_season_demand_cad']:,.0f} to "
        f"${row['high_season_demand_cad']:,.0f}",
        f"Imported product for the January position was due on order by "
        f"{row['january_order_by_imported']}",
        f"Service level used: {row['service_level_used']:.0%}, derived from the cost of each error",
    ]
    return summary, supporting


def append_docx(target: Document, source_path: Path) -> None:
    """Copy an authored Word document into the combined report.

    Body elements are deep-copied rather than re-rendered, because these files
    are the source: anything a person typed in Word, including formatting this
    project's Markdown converter would not produce, has to survive the merge.

    Two details that are easy to get wrong, and were:

    Elements must go *before* the body's trailing sectPr, which carries the page
    setup. Appending to the end of the body puts them after it, where Word
    silently ignores them: the merge appears to work, the file opens without
    complaint, and the section is simply empty.

    The source document's own title page is skipped. These files each open with
    a title, a subtitle and the author block, which would repeat inside the
    combined report under a heading that already says the same thing. Everything
    from the first real heading onward is kept.
    """
    source = Document(str(source_path))
    body = target.element.body
    section_properties = body.find(qn("w:sectPr"))

    def place(element) -> None:
        clone = copy.deepcopy(element)
        if section_properties is not None:
            section_properties.addprevious(clone)
        else:
            body.append(clone)

    started = False
    for element in source.element.body:
        if element.tag == qn("w:sectPr"):
            continue

        # Skip the title block: everything before the document's first heading.
        if not started:
            style = element.find(qn("w:pPr"))
            style_name = ""
            if style is not None:
                reference = style.find(qn("w:pStyle"))
                if reference is not None:
                    style_name = reference.get(qn("w:val")) or ""
            if element.tag == qn("w:tbl") or style_name.startswith("Heading"):
                started = True
            else:
                continue

        place(element)


def section_heading(document: Document, title: str, blurb: str) -> None:
    heading = document.add_heading("", level=1)
    heading.add_run(title).font.color.rgb = ACCENT
    note = document.add_paragraph()
    run = note.add_run(blurb)
    run.italic = True
    run.font.size = Pt(9.5)


def build_combined(meta: list[str]) -> Path:
    document = new_document()
    title_page(
        document,
        "Data Wizardry in Hogwarts",
        "Forecasting a Canadian retail buy before the December 2026 wizarding revival",
        meta,
    )

    summary, supporting = headline_recommendation()
    if summary:
        document.add_paragraph()
        heading = document.add_heading("", level=1)
        heading.add_run("The recommendation").font.color.rgb = ACCENT

        paragraph = document.add_paragraph()
        run = paragraph.add_run(summary)
        run.bold = True
        run.font.size = Pt(11.5)

        for line in supporting:
            bullet = document.add_paragraph(style="List Bullet")
            bullet.add_run(line).font.size = Pt(10)

    document.add_page_break()

    generated = {name: (title, blurb) for name, title, blurb in GENERATED}
    authored = {name: (title, blurb) for name, title, blurb in AUTHORED}

    for name in ORDER:
        if name in generated:
            title, blurb = generated[name]
            source = path("docs", name)
            if not source.exists():
                log_data_issue(
                    SCRIPT, "report",
                    f"{name} does not exist, so it is missing from the report",
                    "run the module that writes it, then rebuild",
                )
                continue
            section_heading(document, title, blurb)
            body = source.read_text(encoding="utf-8")
            body = "\n".join(body.split("\n")[1:]) if body.startswith("# ") else body
            render_markdown(document, body, heading_offset=1)

        else:
            title, blurb = authored[name]
            source = WORD_DIR / name
            if not source.exists():
                log_data_issue(
                    SCRIPT, "report",
                    f"{name} is an authored document and does not exist",
                    "it is not generated by anything, so it has to be restored from git "
                    "history rather than rebuilt",
                    severity="error",
                )
                continue
            section_heading(document, title, blurb)
            append_docx(document, source)

        document.add_page_break()

    target = WORD_DIR / "Data_Wizardry_Report.docx"
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target)
    return target


def main() -> None:
    stamp = datetime.now(UTC).strftime("%d %B %Y")
    meta = [
        "Nusrat Jahan",
        "Master of Business Analytics and AI, Ontario Tech University",
        f"Generated {stamp}",
    ]

    with RunTimer(SCRIPT, logger) as run:
        WORD_DIR.mkdir(parents=True, exist_ok=True)

        written = 0
        for name, title, blurb in GENERATED:
            source = path("docs", name)
            if not source.exists():
                continue
            target = WORD_DIR / f"{source.stem}.docx"
            convert_file(source, target, title, blurb, meta)
            logger.info("rebuilt   %-22s -> %s", name, relative(target))
            written += 1

        for name, _, _ in AUTHORED:
            if (WORD_DIR / name).exists():
                logger.info("left alone %-21s (authored, not generated)", name)
            else:
                logger.warning("missing   %-22s (authored; restore from git)", name)

        combined = build_combined(meta)
        logger.info("combined report -> %s", relative(combined))

        run.rows_out = written + 1
        run.note = f"{written} generated documents rebuilt, {len(AUTHORED)} authored left alone"

    logger.info("report build complete")


if __name__ == "__main__":
    main()
