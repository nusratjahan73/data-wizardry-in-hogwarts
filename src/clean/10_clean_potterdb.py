"""Clean the PotterDB catalogue into flat tables.

Reads  : data/raw/potterdb/*.json
Writes : data/cleaned/potterdb/{characters,books,chapters,movies,spells,potions}.csv
Runtime: a few seconds.

JSON:API nests every field under `attributes`, so the main job is flattening
that, standardising column names to lower case with underscores, parsing dates
to ISO and turning list valued fields into a countable form.

Two choices worth explaining.

List fields are kept twice. `family_members` arrives as a JSON list. It is
stored as a pipe joined string for reading and as a count for analysis, because
a count is what any model would use and re-parsing a string later invites a
subtly different split each time.

Film money is cleaned but flagged. PotterDB's budget and box office fields are
free text with real errors in them, documented in data/external/films_notes.md.
They are parsed here so the error can be measured against the sourced table in
data/external, and the resulting columns are named with a `potterdb_` prefix so
that nothing downstream can mistake them for the authoritative figures.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import path
from src.utils.io import load_raw_json, relative, save_cleaned
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "10_clean_potterdb"
SOURCE = "potterdb"
logger = get_logger(SCRIPT)

# Fields that arrive as JSON lists and become a joined string plus a count.
LIST_FIELDS = {
    "characters": ["alias_names", "family_members", "jobs", "romances", "titles", "wands"],
    "movies": ["cinematographers", "directors", "distributors", "editors",
               "music_composers", "producers", "screenwriters"],
    "potions": ["characteristics", "ingredients", "inventors", "manufacturers", "side_effects"],
}


def flatten(records: list[dict]) -> pd.DataFrame:
    """Turn JSON:API records into a flat frame with id and type preserved."""
    rows = []
    for record in records:
        row = {"id": record.get("id"), "type": record.get("type")}
        row.update(record.get("attributes", {}) or {})
        # chapters carry the parent book stamped on during collection
        for extra in ("book_slug", "book_title"):
            if extra in record:
                row[extra] = record[extra]
        rows.append(row)
    return pd.DataFrame(rows)


def standardise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(column).lower()).strip("_") for column in frame.columns
    ]
    return frame


def split_list_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Store each list column as a joined string and a count."""
    for column in columns:
        if column not in frame.columns:
            continue
        values = frame[column]
        frame[f"{column}_count"] = values.map(lambda v: len(v) if isinstance(v, list) else 0)
        frame[column] = values.map(
            lambda v: " | ".join(str(item) for item in v) if isinstance(v, list) else ""
        )
    return frame


def parse_money_text(text: object) -> float | None:
    """Parse PotterDB's free text money fields into a number of dollars.

    Handles '$125 million', '$150-200 million' (takes the midpoint), '$1.342
    billion' and '$250 million (shared with part 1)'. Returns None when the text
    cannot be read at all. It deliberately does not try to repair the known
    errors in this source, because silently correcting a source hides that it
    was wrong; the comparison against data/external/films.csv is what surfaces it.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    lowered = text.lower().replace(",", "")
    multiplier = 1.0
    if "billion" in lowered:
        multiplier = 1_000_000_000
    elif "million" in lowered:
        multiplier = 1_000_000

    numbers = re.findall(r"\d+(?:\.\d+)?", lowered)
    if not numbers:
        return None

    # A range such as '150-200 million' becomes its midpoint, which is the only
    # defensible single number to take from it.
    if re.search(r"\d+\s*[-–]\s*\d+", lowered) and len(numbers) >= 2:
        value = (float(numbers[0]) + float(numbers[1])) / 2
    else:
        value = float(numbers[0])

    return value * multiplier


def parse_running_time(text: object) -> float | None:
    if not isinstance(text, str):
        return None
    match = re.search(r"(\d+)", text)
    return float(match.group(1)) if match else None


def clean_endpoint(name: str) -> int:
    """Clean one saved endpoint. Returns the row count written."""
    source_file = path("data_raw", SOURCE, f"{name}.json")
    if not source_file.exists():
        log_data_issue(
            SCRIPT, f"{SOURCE}.{name}",
            f"{relative(source_file)} does not exist",
            "endpoint skipped; run 01_potterdb.py to collect it",
            severity="error",
        )
        return 0

    records = load_raw_json(source_file)
    if not records:
        log_data_issue(
            SCRIPT, f"{SOURCE}.{name}", "raw file is empty",
            "endpoint skipped", severity="error",
        )
        return 0

    frame = standardise_columns(flatten(records))
    frame = split_list_columns(frame, LIST_FIELDS.get(name, []))

    if "release_date" in frame.columns:
        frame["release_date"] = pd.to_datetime(frame["release_date"], errors="coerce").dt.date

    if name == "movies":
        # Prefixed so no later script can mistake these for the sourced figures.
        frame["potterdb_budget_usd"] = frame.get("budget", pd.Series(dtype=object)).map(parse_money_text)
        frame["potterdb_box_office_usd"] = frame.get("box_office", pd.Series(dtype=object)).map(parse_money_text)
        frame["running_time_minutes"] = frame.get("running_time", pd.Series(dtype=object)).map(parse_running_time)

    if name == "chapters" and "order" in frame.columns:
        frame["order"] = pd.to_numeric(frame["order"], errors="coerce").astype("Int64")

    if name == "books" and "pages" in frame.columns:
        frame["pages"] = pd.to_numeric(frame["pages"], errors="coerce").astype("Int64")

    # Drop the columns that only hold a picture URL. They are not analysis
    # inputs, and section 4 says images belong under images/, not in a table.
    for column in ["image", "cover", "poster", "trailer"]:
        if column in frame.columns:
            frame = frame.drop(columns=[column])

    target = save_cleaned(SOURCE, f"{name}.csv", frame, endpoint=name)
    logger.info("%-12s %5d rows, %2d columns -> %s", name, len(frame), len(frame.columns), relative(target))
    return len(frame)


def main() -> None:
    endpoints = ["books", "chapters", "characters", "movies", "spells", "potions"]

    with RunTimer(SCRIPT, logger) as run:
        total = 0
        for name in endpoints:
            total += clean_endpoint(name)
        run.rows_out = total

        # The house field is the one the segmentation work would most like to
        # use, and it is mostly empty. Measure it rather than discover it later.
        characters_file = path("data_cleaned", SOURCE, "characters.csv")
        if characters_file.exists():
            characters = pd.read_csv(characters_file)
            if "house" in characters.columns:
                known = int(characters["house"].notna().sum())
                share = known / max(len(characters), 1)
                logger.info("house is populated on %d of %d characters (%.1f%%)", known, len(characters), share * 100)
                if share < 0.25:
                    log_data_issue(
                        SCRIPT, f"{SOURCE}.characters",
                        f"house is populated on only {known} of {len(characters)} characters ({share:.1%})",
                        "the HP API character set is joined in as a second source of house, "
                        "and any house based cut is restricted to characters where it is known",
                    )

    logger.info("PotterDB cleaning complete, %d rows across %d tables", total, len(endpoints))


if __name__ == "__main__":
    main()
