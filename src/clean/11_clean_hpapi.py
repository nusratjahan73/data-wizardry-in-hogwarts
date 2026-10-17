"""Cleaning the HP API character and spell tables.

Reading: data/raw/hpapi/*.json
Writing: data/cleaned/hpapi/{characters,spells}.csv
Running time: instant.

I use this source because it has full details for the characters people really
know. PotterDB is broad but has many empty fields. The wand arrives as a nested
object, so I flatten it into three plain columns here. That way no later script
has to parse a dictionary out of a CSV cell.

I add a `name_key` column, which is the name in lower case with the punctuation
removed. Module 1 joins on this key. I build it the same way in both cleaning
scripts, so the join gives the same result every time.
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

SCRIPT = "11_clean_hpapi"
SOURCE = "hpapi"
logger = get_logger(SCRIPT)


def name_key(name: object) -> str:
    """Turning a character name into a join key.

    I make it lower case, remove the punctuation and squeeze the spaces. I keep
    it simple on purpose. A fuzzy match would join 'Harry Potter' to 'Harry Potter
    (character)' and, on a bad day, also to 'James Potter'. A quiet wrong join is
    worse than a missed one.
    """
    if not isinstance(name, str):
        return ""
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_characters(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)

    # Splitting the wand, which arrives as {'wood': ..., 'core': ..., 'length': ...}.
    if "wand" in frame.columns:
        wand = frame["wand"].apply(lambda w: w if isinstance(w, dict) else {})
        frame["wand_wood"] = wand.map(lambda w: w.get("wood") or None)
        frame["wand_core"] = wand.map(lambda w: w.get("core") or None)
        frame["wand_length"] = pd.to_numeric(wand.map(lambda w: w.get("length")), errors="coerce")
        frame = frame.drop(columns=["wand"])

    if "alternate_names" in frame.columns:
        frame["alternate_names_count"] = frame["alternate_names"].map(
            lambda v: len(v) if isinstance(v, list) else 0
        )
        frame["alternate_names"] = frame["alternate_names"].map(
            lambda v: " | ".join(v) if isinstance(v, list) else ""
        )
    for column in ["alternate_actors"]:
        if column in frame.columns:
            frame[column] = frame[column].map(
                lambda v: " | ".join(v) if isinstance(v, list) else ""
            )

    if "dateOfBirth" in frame.columns:
        frame["date_of_birth"] = pd.to_datetime(
            frame["dateOfBirth"], format="%d-%m-%Y", errors="coerce"
        ).dt.date
        frame = frame.drop(columns=["dateOfBirth"])

    # Turning blank strings into missing values. A blank string is really a missing
    # value, but it would count as filled in any completeness check.
    frame = frame.replace({"": None})

    if "name" in frame.columns:
        frame["name_key"] = frame["name"].map(name_key)

    frame.columns = [
        re.sub(r"(?<!^)(?=[A-Z])", "_", str(c)).lower().replace("__", "_") for c in frame.columns
    ]
    return frame


def clean_spells(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records).replace({"": None})
    if "name" in frame.columns:
        frame["name_key"] = frame["name"].map(name_key)
    return frame


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        total = 0

        for name, cleaner in (("characters", clean_characters), ("spells", clean_spells)):
            source_file = path("data_raw", SOURCE, f"{name}.json")
            if not source_file.exists():
                log_data_issue(
                    SCRIPT, f"{SOURCE}.{name}",
                    f"{relative(source_file)} does not exist",
                    "skipped; run 02_hpapi.py to collect it",
                    severity="error",
                )
                continue

            records = load_raw_json(source_file)
            frame = cleaner(records)
            target = save_cleaned(SOURCE, f"{name}.csv", frame, endpoint=name)
            total += len(frame)
            logger.info("%-12s %4d rows, %2d columns -> %s", name, len(frame), len(frame.columns), relative(target))

            if name == "characters" and "house" in frame.columns:
                known = int(frame["house"].notna().sum())
                logger.info(
                    "house is populated on %d of %d HP API characters (%.1f%%)",
                    known, len(frame), known / max(len(frame), 1) * 100,
                )

        run.rows_out = total

    logger.info("HP API cleaning complete, %d rows", total)


if __name__ == "__main__":
    main()
