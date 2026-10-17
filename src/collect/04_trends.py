"""Collecting Google search interest for four keyword groups, worldwide and in Canada.

Reading: config.yaml (sources.trends, dates).
Writing: data/raw/trends/interest_<granularity>__<group>__<geo>__<window>.csv
         data/raw/trends/related__<group>__<geo>.json
         data/raw/trends/region__<group>__<geo>.csv
Runtime: fifteen to twenty five minutes, and almost all of it is waiting on purpose.

The library. pytrends was archived in April 2025 and fails on a first call from a clean address, so
I use trendspy, which replaced it and is still maintained. I checked that it worked on 2 September
2026.

The fragility. Google throttles this endpoint hard and it is not a documented public API, so any
group can fail at any time. I pull and save every group on its own, log a failure to
logs/data_issues.md and keep going. If every group fails my project still runs, because Wikipedia
pageviews answer the same question from 2015 onward. My module 5 records that switch if it happens.

The granularity. Google picks it from the width of the window. Asking for 2004 to 2026 in one
request gave me 273 monthly values on 2 September 2026, not the weekly ones I need. So I collect
twice: one full range monthly pull, and overlapping four year windows for weekly detail. The windows
overlap by a year, so my cleaning step can put them on one scale. I cannot assume that 100 means the
same thing in two windows.

The values are relative within one request and capped at 100. They are never search counts, and I
cannot compare two files before rescaling them.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import get
from src.utils.io import relative, save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "04_trends"
SOURCE = "trends"
logger = get_logger(SCRIPT)


def geo_label(geo: str) -> str:
    """Making a label I can use in a filename. An empty geo means worldwide."""
    return geo.lower() if geo else "worldwide"


def detect_granularity(dates: pd.Series) -> str:
    """Working out whether a returned series is daily, weekly or monthly.

    Google picks the granularity from the width of the window and does not say
    which one it used. So I measure the median gap between points to label the
    file. A wrong label here would turn into a wrong axis in my module 3.
    """
    if len(dates) < 3:
        return "unknown"
    gap = pd.to_datetime(dates).diff().dt.days.median()
    if gap <= 2:
        return "daily"
    if gap <= 10:
        return "weekly"
    if gap <= 45:
        return "monthly"
    return "coarser_than_monthly"


def collect_interest(
    client,
    terms: list[str],
    timeframe: str,
    geo: str,
    group: str,
    window_tag: str = "full",
) -> int:
    """Pulling interest over time for one group, geography and time window.

    I return the number of rows saved, or 0 if the pull failed. The filename
    records the granularity that really came back, not the one I hoped for.
    """
    label = geo_label(geo)
    try:
        frame = client.interest_over_time(terms, timeframe=timeframe, geo=geo)
    except Exception as exc:  # Catching everything, as the library raises many kinds of network errors
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{group}.{label}",
            f"interest_over_time failed: {type(exc).__name__}: {exc}",
            "group skipped; Wikipedia pageviews remains available as an independent series",
            severity="error",
        )
        logger.error("interest %s/%s failed: %s", group, label, exc)
        return 0

    if frame is None or frame.empty:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{group}.{label}",
            "interest_over_time returned an empty frame",
            "group skipped, not recorded as zero interest",
        )
        return 0

    # Resetting the index, which is the period start date. This way my CSV has the
    # date as a normal column and does not depend on an index being read back right.
    frame = frame.reset_index()
    granularity = detect_granularity(frame.iloc[:, 0])

    target = save_raw(
        SOURCE,
        f"interest_{granularity}__{group}__{label}__{window_tag}.csv",
        frame.to_csv(index=False),
        source_url="google trends via trendspy interest_over_time",
        group=group,
        geo=geo or "worldwide",
        terms=terms,
        timeframe=timeframe,
        window=window_tag,
        granularity=granularity,
        rows=len(frame),
        note=(
            "values are relative to the maximum within this request, capped at 100. "
            "They are not search counts, and two files are only comparable after "
            "rescaling on their overlap."
        ),
    )
    logger.info(
        "interest %-16s %-9s %-10s %-9s %4d rows -> %s",
        group, label, window_tag, granularity, len(frame), relative(target),
    )
    return len(frame)


def collect_related(client, terms: list[str], timeframe: str, geo: str, group: str) -> None:
    """Pulling related queries for the anchor term only.

    Related queries come per term. Pulling five terms for four groups in two
    geographies would be forty extra throttled calls for very little extra
    signal. The anchor term is the one I need to read product intent.
    """
    label = geo_label(geo)
    anchor = terms[0]
    try:
        related = client.related_queries(anchor, timeframe=timeframe, geo=geo)
    except Exception as exc:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{group}.{label}.related",
            f"related_queries failed: {type(exc).__name__}: {exc}",
            "related queries skipped; the interest series is unaffected",
        )
        return

    if not related:
        return

    serialisable = {
        key: (value.to_dict(orient="records") if isinstance(value, pd.DataFrame) else value)
        for key, value in (related.items() if isinstance(related, dict) else {"related": related}.items())
    }
    target = save_raw(
        SOURCE,
        f"related__{group}__{label}.json",
        serialisable,
        source_url="google trends via trendspy related_queries",
        group=group,
        geo=geo or "worldwide",
        term=anchor,
    )
    logger.info("related  %-16s %-9s -> %s", group, label, relative(target))


def collect_region(client, terms: list[str], timeframe: str, geo: str, group: str) -> None:
    """Pulling the regional breakdown, which feeds the geography page of my dashboard."""
    label = geo_label(geo)
    try:
        frame = client.interest_by_region(terms, timeframe=timeframe, geo=geo)
    except Exception as exc:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{group}.{label}.region",
            f"interest_by_region failed: {type(exc).__name__}: {exc}",
            "regional breakdown skipped; the dashboard geography page loses this group",
        )
        return

    if frame is None or getattr(frame, "empty", True):
        return

    frame = frame.reset_index()
    target = save_raw(
        SOURCE,
        f"region__{group}__{label}.csv",
        frame.to_csv(index=False),
        source_url="google trends via trendspy interest_by_region",
        group=group,
        geo=geo or "worldwide",
        rows=len(frame),
    )
    logger.info("region   %-16s %-9s %4d rows -> %s", group, label, len(frame), relative(target))


def weekly_windows(timeframe: str, window_years: int, step_years: int) -> list[tuple[str, str]]:
    """Splitting the full range into overlapping windows that are short enough to return weeks.

    I return a list of (timeframe string, window tag) pairs. Each window is
    `window_years` long and starts `step_years` after the one before, so two
    windows in a row share `window_years - step_years` of history. My cleaning
    step uses that shared part to put every window on one scale.
    """
    start_text, end_text = timeframe.split()
    start = pd.Timestamp(start_text)
    end = pd.Timestamp(end_text)

    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + pd.DateOffset(years=window_years), end)
        tag = f"{cursor:%Y%m}_{window_end:%Y%m}"
        windows.append((f"{cursor:%Y-%m-%d} {window_end:%Y-%m-%d}", tag))
        if window_end >= end:
            break
        cursor = cursor + pd.DateOffset(years=step_years)
    return windows


def main() -> None:
    try:
        from trendspy import Trends
    except ImportError:
        log_data_issue(
            SCRIPT,
            SOURCE,
            "trendspy is not installed",
            "search interest skipped entirely; pageviews becomes the primary attention series",
            severity="error",
        )
        logger.error("trendspy not installed, nothing to do")
        return

    timeframe = get("sources.trends.timeframe")
    geos = get("sources.trends.geos")
    groups: dict[str, list[str]] = get("sources.trends.keyword_groups")
    delay = float(get("sources.trends.request_delay_seconds"))
    max_terms = int(get("sources.trends.max_terms_per_group"))
    anchor = get("sources.trends.anchor_term")

    client = Trends(request_delay=delay)

    weekly_groups = get("sources.trends.weekly_groups")
    window_years = int(get("sources.trends.weekly_window_years"))
    step_years = int(get("sources.trends.weekly_window_step_years"))

    with RunTimer(SCRIPT, logger) as run:
        total_rows = 0
        successes = 0
        attempts = 0

        # Running pass one: the full range, for the long history. This comes back monthly.
        for group, terms in groups.items():
            if len(terms) > max_terms:
                log_data_issue(
                    SCRIPT,
                    f"{SOURCE}.{group}",
                    f"group has {len(terms)} terms, the comparison limit is {max_terms}",
                    f"truncated to the first {max_terms} terms",
                )
                terms = terms[:max_terms]
            if anchor not in terms:
                log_data_issue(
                    SCRIPT,
                    f"{SOURCE}.{group}",
                    f"anchor term '{anchor}' missing from the group",
                    "group pulled anyway, but it is not comparable with the others",
                )

            for geo in geos:
                attempts += 1
                rows = collect_interest(client, terms, timeframe, geo, group)
                if rows:
                    successes += 1
                    total_rows += rows
                    collect_related(client, terms, timeframe, geo, group)
                    collect_region(client, terms, timeframe, geo, group)
                # Waiting between groups, on top of the delay the library already adds.
                # This endpoint punishes bursts, and I prefer a slow complete pull to a
                # fast partial one.
                time.sleep(delay)

        # Running pass two: overlapping short windows, for weekly granularity. I only
        # do this for the groups my timing argument needs, because it multiplies the
        # request count by the number of windows.
        windows = weekly_windows(timeframe, window_years, step_years)
        logger.info("weekly pass: %d windows per group and geography", len(windows))

        for group in weekly_groups:
            terms = groups.get(group)
            if not terms:
                log_data_issue(
                    SCRIPT, f"{SOURCE}.{group}",
                    f"'{group}' is listed in weekly_groups but is not a keyword group",
                    "weekly pass skipped for that name",
                )
                continue
            terms = terms[:max_terms]

            for geo in geos:
                for window_timeframe, tag in windows:
                    attempts += 1
                    rows = collect_interest(client, terms, window_timeframe, geo, group, tag)
                    if rows:
                        successes += 1
                        total_rows += rows
                    time.sleep(delay)

        run.rows_out = total_rows
        run.note = f"{successes}/{attempts} group and geography combinations returned data"

        if successes == 0:
            log_data_issue(
                SCRIPT,
                SOURCE,
                "every search interest pull failed",
                "pageviews becomes the primary attention series and the analysis "
                "start date moves from 2004 to 2015, which is the fallback I planned",
                severity="error",
            )

    logger.info("trends complete: %d of %d combinations, %d weekly rows", successes, attempts, total_rows)


if __name__ == "__main__":
    main()
