"""Clean Wikipedia pageviews into one long daily table and a weekly roll up.

Reads  : data/raw/pageviews/*.json
Writes : data/cleaned/pageviews/pageviews_daily.csv
         data/cleaned/pageviews/pageviews_weekly.csv
Runtime: about ten seconds.

This is the project's backbone attention series, so the shape it takes here is
what every later module inherits.

Long, not wide. One row per article per day, with the group as a column. A wide
table with one column per article would need a schema change every time an
article is added, and would make the group level roll ups awkward.

Weeks start on Monday, and a week is only kept if all seven of its days are
present. A partial week is a smaller number that looks like falling attention,
which is exactly the kind of artefact that would corrupt a seasonality reading.
The number of dropped partial weeks is logged rather than passed over.

Zero versus missing. A day the API did not return is not a day with no views.
Missing days are left missing here and are never filled with zero.
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
    """Turn one saved article response into a tidy daily frame."""
    payload = load_raw_json(file_path)
    items = payload.get("items", [])
    if not items:
        return pd.DataFrame()

    frame = pd.DataFrame(items)
    # timestamps arrive as YYYYMMDDHH with the hour always 00 for daily data
    frame["date"] = pd.to_datetime(frame["timestamp"].str[:8], format="%Y%m%d", errors="coerce")
    frame["views"] = pd.to_numeric(frame["views"], errors="coerce")

    # The group is the part of the filename before the double underscore, which
    # is how the collection script recorded it.
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
    """Roll daily views up to complete Monday weeks.

    Returns the weekly frame and the number of incomplete weeks dropped.
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

        # Rebuild a datetime column for the weekly roll up; the CSV keeps dates.
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
