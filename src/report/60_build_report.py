"""Building the Word documents: one combined report plus one Word copy of every document.

Reading: docs/*.md (every document I keep, generated or written by hand)
         outputs/tables/retail_recommendation.csv
Writing: docs/word/Data_Wizardry_Report.docx   (six documents, in reading order)
         docs/word/<document>.docx             (one per Markdown file, rebuilt each run)
Running time: a few seconds.

I have two kinds of document, and the difference matters.

Generated documents hold results and are written by code: findings.md by every analysis
script, data_dictionary.md by 19_data_dictionary.py, and build_log.md as modules finish.

Authored documents hold my reasoning: the methods note, the ethics note, the open questions
and the build walkthrough. No script can write that, so I write them by hand.

Both kinds now live as Markdown in docs/, and this script turns every one of them into Word.
I first kept the authored documents as Word only, and they drifted: every time the project
changed, they kept describing the old version. Now the Markdown is the only thing I edit,
and the Word files are outputs that this script overwrites on every run.

I run this script last, because the generated documents change every time an analysis runs.
It sits in src/report and not src/analysis, because the analysis numbers 20 to 29 are full
and this script makes a report, not an analysis. I noted this in my open questions document.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from docx import Document
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

# Listing every Markdown document I keep. I convert each one to Word here, and every
# run overwrites the Word copies, so I only ever edit the Markdown.
GENERATED = [
    ("findings.md", "Findings", "What the analysis found, with the evidence and the uncertainty for each."),
    ("data_dictionary.md", "Data dictionary", "Every column of every processed table."),
    ("build_log.md", "Build log", "What each module produced, and what it skipped."),
    ("methods.md", "Methods and assumptions", "How I did it, and every assumption in one place."),
    ("ethics.md", "Ethics, security and trust", "How I obtained, protected and interpreted the data."),
    ("open_questions.md", "Open questions",
     "Decisions reserved for a person, and the default I am using meanwhile."),
    ("build_walkthrough.md", "How I built this project",
     "The whole build from an empty folder, and what every file is for."),
]


# Setting the reading order for the combined report: the answer, then how I reached it,
# then what I assumed, then governance, then the decisions still open, then the
# reference material. A reader who stops after two sections still has the answer.
# I wrote build_walkthrough.docx myself too, but I leave it out of this list on purpose.
# It is for someone rebuilding the project, not for someone reading the recommendation.
# Putting the story of the build inside a business report would help neither reader, so
# it stays a separate document.
ORDER = ["findings.md", "methods.md", "ethics.md", "open_questions.md",
         "data_dictionary.md", "build_log.md"]


def headline_recommendation() -> tuple[str, list[str]]:
    """Building the one paragraph answer from my retail module's own output.

    I read it from the table and do not type it, so the cover of the report cannot
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
        f"it to the pre Christmas window as this category normally would."
    )
    supporting = [
        f"Defensible range: ${row['low_season_demand_cad']:,.0f} to "
        f"${row['high_season_demand_cad']:,.0f}",
        f"Imported product for the January position was due on order by "
        f"{row['january_order_by_imported']}",
        f"Service level used: {row['service_level_used']:.0%}, derived from the cost of each error",
    ]
    return summary, supporting


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

    for name in ORDER:
        title, blurb = generated[name]
        source = path("docs", name)
        if not source.exists():
            log_data_issue(
                SCRIPT, "report",
                f"{name} does not exist, so it is missing from the report",
                "run the module that writes it, or restore it from git history, then rebuild",
            )
            continue
        section_heading(document, title, blurb)
        body = source.read_text(encoding="utf-8")
        body = "\n".join(body.split("\n")[1:]) if body.startswith("# ") else body
        render_markdown(document, body, heading_offset=1)

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

        combined = build_combined(meta)
        logger.info("combined report -> %s", relative(combined))

        run.rows_out = written + 1
        run.note = f"{written} Word documents rebuilt from Markdown"

    logger.info("report build complete")


if __name__ == "__main__":
    main()
