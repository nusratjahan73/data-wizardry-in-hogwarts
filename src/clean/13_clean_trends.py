"""Cleaning search interest and stitching the overlapping weekly windows into one series.

Reading: data/raw/trends/interest_{monthly,weekly}__*.csv
Writing: data/cleaned/trends/interest_monthly.csv
         data/cleaned/trends/interest_weekly.csv
         data/cleaned/trends/weekly_stitch_check.csv
Running time: a few seconds.

The stitch is the main job of this script. Google scales every request so that
its highest value is 100. So a 60 in the 2004 to 2008 window and a 60 in the 2019
to 2023 window mean very different amounts of searching. If I just joined the
windows, the series would look flat across twenty years.

I fix this with the year of overlap that each window shares with the next one.
Starting from the earliest window, I divide the two windows' totals across their
shared weeks. That factor puts the later window on the earlier window's scale.

I use a ratio of sums, not a median of weekly ratios. Trends returns small whole
numbers for low volume terms, so single weeks read 1 against 2, or 0 against 2.
A median of those lands on 0.5 or 0, and a factor of 0 wipes out every week after
the join. A ratio of sums follows the weeks that carry real signal.

I write the disagreement in each overlap to weekly_stitch_check.csv. A stitch
that lines up within a few per cent can be trusted. One that does not is a limit
I have to state in my report.

At the end I rescale the stitched series to 0 to 100, so it reads like a Trends
series. It is my own index and I never present it as a raw Google figure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from src.utils.io import raw_files, relative, save_cleaned
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "13_clean_trends"
SOURCE = "trends"
logger = get_logger(SCRIPT)

FILENAME = re.compile(
    r"^interest_(?P<granularity>\w+?)__(?P<group>\w+?)__(?P<geo>\w+?)__(?P<window>\w+)$"
)


def read_interest_file(file_path: Path) -> pd.DataFrame:
    """Reading one saved interest file into long form: date, term, interest."""
    match = FILENAME.match(file_path.stem)
    if not match:
        log_data_issue(
            SCRIPT, SOURCE, f"filename {file_path.name} does not match the expected pattern",
            "file skipped",
        )
        return pd.DataFrame()

    parts = match.groupdict()
    frame = pd.read_csv(file_path)
    date_column = frame.columns[0]
    frame = frame.rename(columns={date_column: "date"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")

    # Dropping the periods marked isPartial, which had not finished when the data
    # was served. Their value is lower than the finished period would be, so keeping
    # them would look like a fall in interest.
    if "isPartial" in frame.columns:
        partial = frame["isPartial"].astype(str).str.lower().eq("true")
        if partial.any():
            frame = frame[~partial]
        frame = frame.drop(columns=["isPartial"])

    value_columns = [c for c in frame.columns if c != "date"]
    long = frame.melt(id_vars="date", value_vars=value_columns, var_name="term", value_name="interest")
    long["interest"] = pd.to_numeric(long["interest"], errors="coerce")
    long = long.dropna(subset=["date", "interest"])

    long["group"] = parts["group"]
    long["geo"] = parts["geo"]
    long["window"] = parts["window"]
    long["granularity"] = parts["granularity"]
    return long


def stitch_windows(windows: dict[str, pd.DataFrame], term: str, group: str, geo: str) -> tuple[pd.DataFrame, list[dict]]:
    """Putting a term's overlapping windows onto one scale, earliest window first.

    I return the stitched table and one check row per join.
    """
    ordered = sorted(windows.items(), key=lambda item: item[0])
    checks: list[dict] = []

    running_factor = 1.0
    stitched_parts: list[pd.DataFrame] = []
    previous_scaled: pd.DataFrame | None = None

    for index, (window_tag, frame) in enumerate(ordered):
        scaled = frame.copy()

        if index > 0 and previous_scaled is not None:
            overlap = previous_scaled.merge(
                frame, on="date", suffixes=("_prev", "_curr")
            )
            usable = overlap[
                (overlap["interest_curr"] > 0) & overlap["interest_prev"].notna()
            ]

            # Working out the factor as the ratio of the two windows' totals across
            # the overlap, not the median of the weekly ratios. Trends returns small
            # whole numbers for low volume terms, so a week reading 1 against 2 gives
            # 0.5 and a week reading 0 against 2 gives 0. A median of those can drop
            # the factor to zero and wipe out everything after the join. A ratio of
            # sums follows the weeks that carry real signal, which is what I want.
            previous_total = float(usable["interest_prev"].sum())
            current_total = float(usable["interest_curr"].sum())

            if len(usable) >= 4 and current_total > 0 and previous_total > 0:
                running_factor = previous_total / current_total
                scaled["interest"] = frame["interest"] * running_factor
                merged_check = usable.assign(rescaled=usable["interest_curr"] * running_factor)
                disagreement = float(
                    (
                        (merged_check["rescaled"] - merged_check["interest_prev"]).abs()
                        / merged_check["interest_prev"].replace(0, np.nan)
                    ).median() * 100
                )
                note = "stitched on the measured overlap"
            else:
                # Carrying the previous factor forward, because the overlap has too
                # little signal to measure a new one. This is a guess, so I label it
                # as one in the note and do not quietly write a series of zeros.
                scaled["interest"] = frame["interest"] * running_factor
                disagreement = np.nan
                if len(usable) < 4:
                    note = (
                        f"only {len(usable)} usable overlapping weeks; factor carried "
                        f"forward, treat this join with caution"
                    )
                else:
                    note = (
                        "one side of the overlap was entirely zero, so no factor could be "
                        "measured; factor carried forward and the level before this join "
                        "is not comparable with the level after it"
                    )

            checks.append({
                "group": group, "geo": geo, "term": term,
                "window": window_tag,
                "overlap_periods": len(usable),
                "scale_factor": running_factor,
                "median_absolute_percent_difference": disagreement,
                "note": note,
            })
        else:
            checks.append({
                "group": group, "geo": geo, "term": term,
                "window": window_tag,
                "overlap_periods": 0,
                "scale_factor": 1.0,
                "median_absolute_percent_difference": np.nan,
                "note": "base window, defines the scale",
            })

        scaled["window"] = window_tag
        stitched_parts.append(scaled)
        previous_scaled = scaled[["date", "interest"]]

    combined = pd.concat(stitched_parts, ignore_index=True)

    # Averaging the two scaled values I get for a week where windows overlap. The
    # mean gives a smoother join than picking one of them at random.
    combined = (
        combined.groupby("date", as_index=False)
        .agg(interest=("interest", "mean"), windows_contributing=("window", "nunique"))
        .sort_values("date")
    )
    combined["term"] = term
    combined["group"] = group
    combined["geo"] = geo
    return combined, checks


def main() -> None:
    monthly_files = raw_files(SOURCE, "interest_monthly__*.csv")
    weekly_files = raw_files(SOURCE, "interest_weekly__*.csv")

    with RunTimer(SCRIPT, logger) as run:
        if not monthly_files and not weekly_files:
            log_data_issue(
                SCRIPT, SOURCE, "no interest files found",
                "pageviews becomes the sole attention series; record the substitution",
                severity="error",
            )
            logger.error("no raw interest files, nothing to clean")
            run.rows_out = 0
            return

        rows_out = 0

        # Cleaning the monthly files, which hold the long history. There is one file
        # per group and geography, so I have nothing to stitch. Each one is already
        # on its own single scale.
        if monthly_files:
            monthly = pd.concat([read_interest_file(f) for f in monthly_files], ignore_index=True)
            monthly = monthly[monthly["interest"].notna()]
            monthly["date"] = monthly["date"].dt.date
            target = save_cleaned(
                SOURCE, "interest_monthly.csv",
                monthly.drop(columns=["window", "granularity"]),
                first_month=str(monthly["date"].min()),
                last_month=str(monthly["date"].max()),
                note="each group and geography is on its own 0 to 100 scale; only compare within one",
            )
            rows_out += len(monthly)
            logger.info(
                "monthly: %d rows, %d group and geography pairs, %s to %s -> %s",
                len(monthly),
                monthly.groupby(["group", "geo"]).ngroups,
                monthly["date"].min(), monthly["date"].max(), relative(target),
            )

        # Cleaning the weekly files and stitching them across windows.
        if weekly_files:
            raw_weekly = pd.concat([read_interest_file(f) for f in weekly_files], ignore_index=True)
            stitched_parts: list[pd.DataFrame] = []
            all_checks: list[dict] = []

            for (group, geo, term), subset in raw_weekly.groupby(["group", "geo", "term"]):
                windows = {
                    window: part[["date", "interest"]].sort_values("date").reset_index(drop=True)
                    for window, part in subset.groupby("window")
                }
                stitched, checks = stitch_windows(windows, term, group, geo)
                stitched_parts.append(stitched)
                all_checks.extend(checks)

            weekly = pd.concat(stitched_parts, ignore_index=True)

            # Rescaling each series to 0 to 100 so it reads like a Trends series.
            weekly["interest_index"] = weekly.groupby(["group", "geo", "term"])["interest"].transform(
                lambda s: s / s.max() * 100 if s.max() and s.max() > 0 else s
            )
            weekly = weekly.rename(columns={"interest": "interest_stitched_raw"})
            weekly["date"] = weekly["date"].dt.date

            target = save_cleaned(
                SOURCE, "interest_weekly.csv", weekly,
                first_week=str(weekly["date"].min()),
                last_week=str(weekly["date"].max()),
                note=(
                    "stitched from overlapping four year windows and rescaled to 0-100. "
                    "This is a constructed index, not a raw Google figure."
                ),
            )
            rows_out += len(weekly)
            logger.info(
                "weekly: %d rows, %d series, %s to %s -> %s",
                len(weekly), weekly.groupby(["group", "geo", "term"]).ngroups,
                weekly["date"].min(), weekly["date"].max(), relative(target),
            )

            check_frame = pd.DataFrame(all_checks)
            check_target = save_cleaned(
                SOURCE, "weekly_stitch_check.csv", check_frame,
                note="how well consecutive windows agreed once rescaled",
            )
            logger.info("stitch check -> %s", relative(check_target))

            worst = check_frame["median_absolute_percent_difference"].max()
            if pd.notna(worst):
                logger.info("worst overlap disagreement after rescaling: %.1f%%", worst)
                if worst > 15:
                    log_data_issue(
                        SCRIPT, SOURCE,
                        f"stitched weekly windows disagree by up to {worst:.1f}% on their overlaps",
                        "the weekly series is kept for shape and timing but not for level "
                        "comparisons across eras; the monthly series is preferred for long "
                        "run level, and the report says so",
                    )

            thin = int((check_frame["overlap_periods"] < 4).sum())
            if thin:
                log_data_issue(
                    SCRIPT, SOURCE,
                    f"{thin} window joins had fewer than four usable overlapping weeks",
                    "the previous scale factor was carried forward for those joins",
                )

            # Naming the terms that are zero for most of their history, because they
            # have no weekly signal to measure. This stops a later module from reading
            # a flat line of zeros as no interest, when the search term is really just
            # too rare to register.
            sparsity = (
                weekly.assign(is_zero=weekly["interest_stitched_raw"].fillna(0) <= 0)
                .groupby(["group", "geo", "term"], as_index=False)["is_zero"]
                .mean()
                .rename(columns={"is_zero": "zero_share"})
            )
            too_sparse = sparsity[sparsity["zero_share"] > 0.6]
            for _, row in too_sparse.iterrows():
                log_data_issue(
                    SCRIPT, f"{SOURCE}.{row['group']}.{row['geo']}",
                    f"term '{row['term']}' is zero in {row['zero_share']:.0%} of weeks",
                    "too rare to carry a weekly series; use it only at monthly granularity "
                    "and never read its flat stretches as measured low interest",
                    severity="note",
                )
            if len(too_sparse):
                logger.info(
                    "%d of %d weekly series are mostly zero and are flagged as too sparse",
                    len(too_sparse), len(sparsity),
                )

        run.rows_out = rows_out

    logger.info("trends cleaning complete")


if __name__ == "__main__":
    main()
