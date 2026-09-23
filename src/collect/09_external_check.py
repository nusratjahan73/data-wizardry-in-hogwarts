"""Validate the hand entered tables in data/external.

Reads  : data/external/films.csv, data/external/parks.csv.
Writes : nothing. Logs, and appends to logs/data_issues.md on a problem.
Runtime: instant.

The files in data/external are the only ones a script cannot rebuild, which
makes them the only ones where a typo can survive a full rebuild unnoticed. This
script is the guard against that. It is numbered with the collection scripts
because that is where it belongs in run order, even though it downloads nothing.

Section 6 sets two conditions on hand entered data: every figure carries its
source, and every row carries the date it was retrieved. Both are checked here
rather than trusted.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import get
from src.utils.io import read_external
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "09_external_check"
SOURCE = "external"
logger = get_logger(SCRIPT)

# column -> whether a blank is acceptable. CinemaScore is genuinely missing for
# three films, so it is allowed to be blank; a blank budget would be a mistake.
FILM_REQUIRED = [
    "film_id", "title", "series", "release_date", "release_date_na",
    "budget_usd", "domestic_gross_usd", "worldwide_gross_usd",
    "opening_weekend_domestic_usd", "rt_critic_score", "rt_audience_score",
    "retrieved_date",
]
PARK_REQUIRED = ["park", "year", "attendance", "wizarding_land_opened", "source", "retrieved_date"]


def check_sources_and_dates(frame: pd.DataFrame, name: str) -> list[str]:
    """Every row must say where it came from and when it was read."""
    problems: list[str] = []

    source_columns = [c for c in frame.columns if c.startswith("source")]
    if not source_columns:
        problems.append(f"{name} has no source column at all")
    for column in source_columns:
        blanks = int(frame[column].isna().sum())
        if blanks:
            problems.append(f"{name}.{column} is blank on {blanks} rows")

    if "retrieved_date" not in frame.columns:
        problems.append(f"{name} has no retrieved_date column")
        return problems

    parsed = pd.to_datetime(frame["retrieved_date"], errors="coerce")
    unparseable = int(parsed.isna().sum())
    if unparseable:
        problems.append(f"{name}.retrieved_date could not be parsed on {unparseable} rows")

    future = int((parsed.dt.date > date.today()).sum())
    if future:
        problems.append(f"{name}.retrieved_date is in the future on {future} rows")

    return problems


def check_films() -> tuple[int, list[str]]:
    problems: list[str] = []
    try:
        films = read_external("films.csv")
    except FileNotFoundError as exc:
        return 0, [str(exc)]

    expected_titles = get("films.titles")
    if len(films) != len(expected_titles):
        problems.append(
            f"films.csv has {len(films)} rows but config lists {len(expected_titles)} film titles"
        )

    for column in FILM_REQUIRED:
        if column not in films.columns:
            problems.append(f"films.csv is missing the required column {column}")
            continue
        blanks = int(films[column].isna().sum())
        if blanks:
            problems.append(f"films.csv.{column} is blank on {blanks} rows")

    if "film_id" in films.columns and films["film_id"].duplicated().any():
        problems.append("films.csv has duplicate film_id values")

    # Money columns must be positive, and gross must exceed nothing in particular
    # but must at least be a number. A negative here means a stray minus sign.
    for column in ["budget_usd", "domestic_gross_usd", "worldwide_gross_usd",
                   "opening_weekend_domestic_usd"]:
        if column in films.columns:
            values = pd.to_numeric(films[column], errors="coerce")
            if values.isna().any():
                problems.append(f"films.csv.{column} contains a value that is not a number")
            elif (values <= 0).any():
                problems.append(f"films.csv.{column} contains a value that is zero or negative")

    # Worldwide should never be less than domestic. If it is, two sources have
    # been mixed within one row.
    if {"domestic_gross_usd", "worldwide_gross_usd"} <= set(films.columns):
        domestic = pd.to_numeric(films["domestic_gross_usd"], errors="coerce")
        worldwide = pd.to_numeric(films["worldwide_gross_usd"], errors="coerce")
        bad = int((worldwide < domestic).sum())
        if bad:
            problems.append(
                f"films.csv has {bad} rows where worldwide gross is below domestic gross"
            )

    # Opening weekend cannot exceed the whole domestic run.
    if {"opening_weekend_domestic_usd", "domestic_gross_usd"} <= set(films.columns):
        opening = pd.to_numeric(films["opening_weekend_domestic_usd"], errors="coerce")
        domestic = pd.to_numeric(films["domestic_gross_usd"], errors="coerce")
        bad = int((opening > domestic).sum())
        if bad:
            problems.append(
                f"films.csv has {bad} rows where the opening weekend exceeds the total domestic gross"
            )

    for column in ["rt_critic_score", "rt_audience_score", "metacritic_score"]:
        if column in films.columns:
            values = pd.to_numeric(films[column], errors="coerce")
            out_of_range = int(((values < 0) | (values > 100)).sum())
            if out_of_range:
                problems.append(f"films.csv.{column} has {out_of_range} values outside 0 to 100")

    problems.extend(check_sources_and_dates(films, "films.csv"))
    return len(films), problems


def check_parks() -> tuple[int, list[str]]:
    problems: list[str] = []
    try:
        parks = read_external("parks.csv")
    except FileNotFoundError as exc:
        return 0, [str(exc)]

    for column in PARK_REQUIRED:
        if column not in parks.columns:
            problems.append(f"parks.csv is missing the required column {column}")
            continue
        blanks = int(parks[column].isna().sum())
        if blanks:
            problems.append(f"parks.csv.{column} is blank on {blanks} rows")

    if {"park", "year"} <= set(parks.columns) and parks.duplicated(subset=["park", "year"]).any():
        problems.append("parks.csv has more than one row for the same park and year")

    if "attendance" in parks.columns:
        values = pd.to_numeric(parks["attendance"], errors="coerce")
        if values.isna().any():
            problems.append("parks.csv.attendance contains a value that is not a number")
        elif (values <= 0).any():
            problems.append("parks.csv.attendance contains a value that is zero or negative")

    if "year" in parks.columns:
        years = pd.to_numeric(parks["year"], errors="coerce")
        if (years > date.today().year).any():
            problems.append("parks.csv.year contains a year in the future")

    # The open flag has to agree with the opening date, or the step change
    # analysis will attribute a rise to the wrong year.
    if {"year", "wizarding_land_opened", "wizarding_land_open_this_year"} <= set(parks.columns):
        opened_year = pd.to_datetime(parks["wizarding_land_opened"], errors="coerce").dt.year
        expected = (pd.to_numeric(parks["year"], errors="coerce") >= opened_year).astype("Int64")
        actual = pd.to_numeric(parks["wizarding_land_open_this_year"], errors="coerce").astype("Int64")
        mismatches = int((expected != actual).sum())
        if mismatches:
            problems.append(
                f"parks.csv has {mismatches} rows where wizarding_land_open_this_year "
                f"disagrees with wizarding_land_opened"
            )

    problems.extend(check_sources_and_dates(parks, "parks.csv"))
    return len(parks), problems


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        film_rows, film_problems = check_films()
        park_rows, park_problems = check_parks()
        problems = film_problems + park_problems

        logger.info("films.csv: %d rows, %d problems", film_rows, len(film_problems))
        logger.info("parks.csv: %d rows, %d problems", park_rows, len(park_problems))

        for problem in problems:
            logger.error("%s", problem)
            log_data_issue(
                SCRIPT, SOURCE, problem,
                "fix the hand entered file; nothing downstream can correct it",
                severity="error",
            )

        run.rows_in = film_rows + park_rows
        run.rows_out = film_rows + park_rows
        run.note = f"{len(problems)} problems found"

        if not problems:
            logger.info("hand entered tables passed every check")
        else:
            # Loud, but not fatal: the rest of the build should still run so that
            # every problem is visible in one pass rather than one per rerun.
            logger.error("%d problems found in data/external, see logs/data_issues.md", len(problems))


if __name__ == "__main__":
    main()
