"""Cleaning the PotterDB catalogue into flat tables.

Reading: data/raw/potterdb/*.json
Writing: data/cleaned/potterdb/{characters,books,chapters,movies,spells,potions}.csv
Running time: a few seconds.

JSON:API puts every field under `attributes`, so my main job is to flatten that.
I also make the column names lower case with underscores, turn dates into ISO
format, and turn list fields into something I can count.

I made two choices here.

I keep list fields twice. `family_members` arrives as a JSON list. I store it as
a pipe joined string for reading and as a count for analysis. A model would use
the count, and splitting the string again later could give a slightly different
result each time.

I clean the film money but I flag it. PotterDB's budget and box office fields are
free text with real errors in them, which I wrote down in
data/external/films_notes.md. I parse them here so I can measure the error against
my sourced table in data/external. The new columns start with `potterdb_`, so no
later script can mix them up with the trusted figures.
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

# Listing the fields that arrive as JSON lists. Each one becomes a joined string plus a count.
LIST_FIELDS = {
    "characters": ["alias_names", "family_members", "jobs", "romances", "titles", "wands"],
    "movies": ["cinematographers", "directors", "distributors", "editors",
               "music_composers", "producers", "screenwriters"],
    "potions": ["characteristics", "ingredients", "inventors", "manufacturers", "side_effects"],
}


def flatten(records: list[dict]) -> pd.DataFrame:
    """Turning JSON:API records into a flat table, keeping the id and type."""
    rows = []
    for record in records:
        row = {"id": record.get("id"), "type": record.get("type")}
        row.update(record.get("attributes", {}) or {})
        # Copying over the parent book that I stamped on each chapter during collection.
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
    """Storing each list column as a joined string and a count."""
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
    """Parsing PotterDB's free text money fields into a number of dollars.

    I handle '$125 million', '$150-200 million' (I take the midpoint), '$1.342
    billion' and '$250 million (shared with part 1)'. I return None when I cannot
    read the text at all. I do not fix the known errors in this source, because
    fixing them quietly would hide that the source was wrong. My comparison
    against data/external/films.csv is what shows them.
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

    # Turning a range such as '150-200 million' into its midpoint, because that is
    # the only fair single number I can take from it.
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
    """Cleaning one saved endpoint and returning the number of rows I wrote."""
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
        # Adding a prefix so no later script can mix these up with my sourced figures.
        frame["potterdb_budget_usd"] = frame.get("budget", pd.Series(dtype=object)).map(parse_money_text)
        frame["potterdb_box_office_usd"] = frame.get("box_office", pd.Series(dtype=object)).map(parse_money_text)
        frame["running_time_minutes"] = frame.get("running_time", pd.Series(dtype=object)).map(parse_running_time)

    if name == "chapters" and "order" in frame.columns:
        frame["order"] = pd.to_numeric(frame["order"], errors="coerce").astype("Int64")

    if name == "books" and "pages" in frame.columns:
        frame["pages"] = pd.to_numeric(frame["pages"], errors="coerce").astype("Int64")

    # Dropping the columns that only hold a picture URL. I do not use them in my
    # analysis, and pictures belong under images/, not in a table.
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

        # Measuring the house field now, so I do not find the gap later. It is the
        # field I most want for my segmentation work, and it is mostly empty.
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
