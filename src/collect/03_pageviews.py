"""Collecting daily Wikipedia pageviews per article, the main series of my project.

Reading: config.yaml (sources.pageviews, dates).
Writing: data/raw/pageviews/<group>__<article>.json, one file per article.
Runtime: about two minutes for forty odd articles.

This is the attention series that everything later in my project rests on. I
treat it as a main source next to search interest, not as a backup. It is an
official endpoint with no key, no real rate limit and daily data from
1 July 2015, while the search interest source is fragile.

I save one file per article, named group__article, so I can delete one bad
article and pull it again without touching the rest. The group prefix lets my
cleaning script keep franchise, film, character and control series apart
without a second lookup table.

One request can cover a wide date range, so each article is one call for the
whole window.
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
    """Turning an article title into a lower case filename that uses only underscores.

    Article titles contain apostrophes, colons, brackets and en dashes, and none
    of these belong in a filename on Windows. I keep the original title in the
    .meta.json file, so nothing is lost here.
    """
    cleaned = []
    for char in article:
        if char.isalnum():
            cleaned.append(char.lower())
        elif char in {"_", "-"}:
            cleaned.append("_")
        # Dropping every other character, including : ' ( ) and the en dash.
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
    """Pulling the daily view series for one article and returning the number of days I got."""
    encoded = urllib.parse.quote(article, safe="")
    url = (
        f"{base_url}/{project}/{access}/{agent}/{encoded}/{granularity}/"
        f"{start:%Y%m%d}/{end:%Y%m%d}"
    )

    try:
        payload = get_json(url, limiter=limiter, logger=logger)
    except ApiError as exc:
        # Treating a 404 as a data problem and not a crash. It almost always means
        # the title is a redirect and not a real article, so I log it by name.
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
                "stage 1 gate fails; this is one of my stop conditions",
                severity="critical",
            )

    logger.info(
        "pageviews complete: %d of %d articles, %d article days in total",
        collected, attempted, total_days,
    )


if __name__ == "__main__":
    main()
