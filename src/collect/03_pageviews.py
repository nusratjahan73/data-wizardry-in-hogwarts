"""Collect daily Wikipedia pageviews per article, the project's backbone series.

Reads  : config.yaml (sources.pageviews, dates).
Writes : data/raw/pageviews/<group>__<article>.json, one file per article.
Runtime: about two minutes for forty odd articles.

This is the attention series everything downstream rests on. Section 6 of the
brief promotes it from a backup to a co-primary source precisely because it is an
official endpoint with no key, no meaningful rate limit and daily granularity
from 1 July 2015, where the search interest source is fragile.

One file per article, named group__article, so a single bad article can be
deleted and pulled again without touching the rest. The group prefix is what
lets the cleaning script keep franchise, film, character and control series
apart without a second lookup table.

The API caps a single request at a wide date range comfortably, so each article
is one call covering the whole window.
"""

from __future__ import annotations

import sys
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import as_date, get
from src.utils.http import ApiError, RateLimiter, get_json
from src.utils.io import relative, save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "03_pageviews"
SOURCE = "pageviews"
logger = get_logger(SCRIPT)


def safe_filename(group: str, article: str) -> str:
    """Turn an article title into a lower case, underscore only filename.

    Article titles contain apostrophes, colons, brackets and en dashes, none of
    which belong in a filename on Windows. The original title is preserved in
    the metadata sidecar, so nothing is lost by flattening it here.
    """
    cleaned = []
    for char in article:
        if char.isalnum():
            cleaned.append(char.lower())
        elif char in {"_", "-"}:
            cleaned.append("_")
        # every other character, including : ' ( ) and the en dash, is dropped
    slug = "".join(cleaned)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"{group}__{slug.strip('_')}.json"


def collect_article(
    group: str,
    article: str,
    limiter: RateLimiter,
    base_url: str,
    project: str,
    access: str,
    agent: str,
    granularity: str,
    start: date,
    end: date,
) -> int:
    """Pull one article's daily view series. Returns the number of days returned."""
    encoded = urllib.parse.quote(article, safe="")
    url = (
        f"{base_url}/{project}/{access}/{agent}/{encoded}/{granularity}/"
        f"{start:%Y%m%d}/{end:%Y%m%d}"
    )

    try:
        payload = get_json(url, limiter=limiter, logger=logger)
    except ApiError as exc:
        # A 404 here almost always means the title is a redirect rather than a
        # real article. That is a data problem worth naming, not a crash.
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{article}",
            f"no view data returned: {exc}",
            "article dropped from the attention series, not treated as zero views",
            severity="error" if exc.status != 404 else "warning",
        )
        logger.error("skipping %s: %s", article, exc)
        return 0

    items = payload.get("items", [])
    if not items:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{article}",
            "endpoint returned an empty item list",
            "article dropped from the attention series",
        )
        return 0

    target = save_raw(
        SOURCE,
        safe_filename(group, article),
        payload,
        source_url=url,
        article=article,
        group=group,
        days=len(items),
        first_day=items[0].get("timestamp"),
        last_day=items[-1].get("timestamp"),
    )
    logger.info("%-10s %-46s %5d days -> %s", group, article, len(items), relative(target))
    return len(items)


def main() -> None:
    base_url = get("sources.pageviews.base_url")
    project = get("sources.pageviews.project")
    access = get("sources.pageviews.access")
    agent = get("sources.pageviews.agent")
    granularity = get("sources.pageviews.granularity")
    limiter = RateLimiter(get("sources.pageviews.min_seconds_between_calls"))
    groups: dict[str, list[str]] = get("sources.pageviews.articles")

    start = as_date("dates.pageviews_start")
    end = as_date("dates.pageviews_end")

    with RunTimer(SCRIPT, logger) as run:
        total_days = 0
        collected = 0
        attempted = 0

        for group, articles in groups.items():
            for article in articles:
                attempted += 1
                days = collect_article(
                    group, article, limiter, base_url, project, access, agent,
                    granularity, start, end,
                )
                if days:
                    collected += 1
                    total_days += days

        run.rows_out = total_days
        run.note = f"{collected}/{attempted} articles returned data"

        if collected == 0:
            log_data_issue(
                SCRIPT,
                SOURCE,
                "no article returned any view data",
                "stage 1 gate fails; see the stop conditions in section 16",
                severity="critical",
            )

    logger.info(
        "pageviews complete: %d of %d articles, %d article-days in total",
        collected, attempted, total_days,
    )


if __name__ == "__main__":
    main()
