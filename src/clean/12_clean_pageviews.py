"""Cleaning Wikipedia pageviews into one long daily table and a weekly roll up.

Reading: data/raw/pageviews/*.json
Writing: data/cleaned/pageviews/pageviews_daily.csv
         data/cleaned/pageviews/pageviews_weekly.csv
Running time: about ten seconds.

This is my main attention series, so every later module uses the shape I give it
here.

I keep it long, not wide. There is one row per article per day, with the group as
a column. A wide table with one column per article would need a new column every
time I add an article, and the group level roll ups would be awkward.

My weeks start on Monday, and I only keep a week if all seven of its days are
present. A partial week gives a smaller number that looks like falling attention,
and that would spoil my seasonality reading. I log how many partial weeks I drop.

Zero is not the same as missing. A day the API did not return is not a day with
no views. I leave missing days missing and never fill them with zero.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.io import load_raw_json, raw_files, relative, save_cleaned
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "12_clean_pageviews"
SOURCE = "pageviews"
logger = get_logger(SCRIPT)


def read_one(file_path: Path) -> pd.DataFrame:
    """Turning one saved article response into a tidy daily table."""
    payload = load_raw_json(file_path)
    items = payload.get("items", [])
    if not items:
        return pd.DataFrame()

    frame = pd.DataFrame(items)
    # Reading the timestamps, which arrive as YYYYMMDDHH with the hour always 00 for daily data.
    frame["date"] = pd.to_datetime(frame["timestamp"].str[:8], format="%Y%m%d", errors="coerce")
    frame["views"] = pd.to_numeric(frame["views"], errors="coerce")

    # Taking the group from the part of the file name before the double underscore,
    # which is how my collection script recorded it.
    group = file_path.stem.split("__", 1)[0]

    return pd.DataFrame(
        {
            "date": frame["date"],
            "article": frame["article"],
            "group": group,
            "views": frame["views"],
        }
    )


def build_weekly(daily: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Rolling daily views up to complete Monday weeks.

    I return the weekly table and the number of incomplete weeks I dropped.
    """
    working = daily.copy()
    working["week_start"] = working["date"] - pd.to_timedelta(working["date"].dt.weekday, unit="D")

    grouped = working.groupby(["article", "group", "week_start"], as_index=False).agg(
        views=("views", "sum"),
        days_present=("views", "count"),
    )

    incomplete = int((grouped["days_present"] < 7).sum())
    complete = grouped[grouped["days_present"] == 7].drop(columns=["days_present"])
    return complete.reset_index(drop=True), incomplete


def main() -> None:
    files = raw_files(SOURCE, "*.json")

    with RunTimer(SCRIPT, logger) as run:
        if not files:
            log_data_issue(
                SCRIPT, SOURCE, "no raw pageview files found",
                "run 03_pageviews.py first; without this series the forecast has no input",
                severity="critical",
            )
            logger.error("no raw pageview files, nothing to clean")
            run.rows_out = 0
            return

        frames = [read_one(f) for f in files]
        frames = [f for f in frames if not f.empty]
        daily = pd.concat(frames, ignore_index=True)
        run.rows_in = len(daily)

        before = len(daily)
        daily = daily.dropna(subset=["date", "views"])
        dropped = before - len(daily)
        if dropped:
            log_data_issue(
                SCRIPT, SOURCE,
                f"{dropped} rows had an unparseable date or view count",
                "rows dropped rather than filled with zero",
            )

        daily = daily.sort_values(["group", "article", "date"]).reset_index(drop=True)
        daily["date"] = daily["date"].dt.date

        duplicates = int(daily.duplicated(subset=["article", "date"]).sum())
        if duplicates:
            log_data_issue(
                SCRIPT, SOURCE,
                f"{duplicates} duplicate article and date pairs found",
                "kept the first occurrence of each",
            )
            daily = daily.drop_duplicates(subset=["article", "date"], keep="first")

        daily_target = save_cleaned(
            SOURCE, "pageviews_daily.csv", daily,
            articles=int(daily["article"].nunique()),
            first_date=str(daily["date"].min()),
            last_date=str(daily["date"].max()),
        )
        logger.info(
            "daily: %d rows, %d articles, %s to %s -> %s",
            len(daily), daily["article"].nunique(), daily["date"].min(), daily["date"].max(),
            relative(daily_target),
        )

        # Rebuilding a datetime column for the weekly roll up, because the CSV keeps plain dates.
        for_weekly = daily.copy()
        for_weekly["date"] = pd.to_datetime(for_weekly["date"])
        weekly, incomplete = build_weekly(for_weekly)
        weekly["week_start"] = weekly["week_start"].dt.date

        if incomplete:
            logger.info("dropped %d incomplete weeks at the series edges", incomplete)
            log_data_issue(
                SCRIPT, SOURCE,
                f"{incomplete} article weeks had fewer than seven days of data",
                "those weeks were dropped, because a partial week reads as a fall in attention",
                severity="note",
            )

        weekly_target = save_cleaned(
            SOURCE, "pageviews_weekly.csv", weekly,
            articles=int(weekly["article"].nunique()),
            first_week=str(weekly["week_start"].min()),
            last_week=str(weekly["week_start"].max()),
            note="complete Monday weeks only",
        )
        logger.info(
            "weekly: %d rows, %s to %s -> %s",
            len(weekly), weekly["week_start"].min(), weekly["week_start"].max(),
            relative(weekly_target),
        )

        run.rows_out = len(daily) + len(weekly)
        run.note = f"{daily['article'].nunique()} articles"


if __name__ == "__main__":
    main()
