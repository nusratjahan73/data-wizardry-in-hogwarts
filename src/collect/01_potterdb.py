"""Collect the PotterDB catalogue: books, characters, movies, spells, potions, chapters.

Reads  : config.yaml (sources.potterdb).
Writes : data/raw/potterdb/<endpoint>.json plus a .meta.json for each.
Runtime: about four minutes, held down by the 900 requests per hour rate limit.

PotterDB serves JSON:API, so every response carries `data` (a list of records
with `id`, `type` and `attributes`) and `meta.pagination`. This script saves the
records exactly as they arrive, with no flattening or type coercion, because
section 4 forbids converting anything during collection.

One shape difference from the brief is handled here. Chapters are not a top
level endpoint: they hang off each book at /v1/books/<slug>/chapters. The brief's
appendix already warns that chapter records carry only order, slug, title and
summary, with no character list, which is why module 3 builds its network from
attention data instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import get
from src.utils.http import ApiError, RateLimiter, get_json
from src.utils.io import relative, save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "01_potterdb"
SOURCE = "potterdb"
logger = get_logger(SCRIPT)


def fetch_paginated(
    url: str, limiter: RateLimiter, page_size: int, label: str
) -> tuple[list[dict], dict]:
    """Walk every page of a JSON:API collection and return all records.

    Returns the records and the pagination block from the first response, which
    carries the record count the log line reports against.
    """
    records: list[dict] = []
    page = 1
    first_pagination: dict = {}

    while True:
        payload = get_json(
            url,
            params={"page[size]": page_size, "page[number]": page},
            limiter=limiter,
            logger=logger,
        )
        batch = payload.get("data", [])
        pagination = payload.get("meta", {}).get("pagination", {})
        if page == 1:
            first_pagination = pagination
            logger.info(
                "%s: %s records across %s pages",
                label,
                pagination.get("records", "unknown"),
                pagination.get("last", "unknown"),
            )

        records.extend(batch)
        next_page = pagination.get("next")
        if not batch or not next_page:
            break
        page = next_page

    return records, first_pagination


def collect_endpoint(endpoint: str, limiter: RateLimiter, base_url: str, page_size: int) -> int:
    """Pull one top level endpoint and save it. Returns the record count."""
    url = f"{base_url}/{endpoint}"
    try:
        records, pagination = fetch_paginated(url, limiter, page_size, endpoint)
    except ApiError as exc:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{endpoint}",
            f"request failed: {exc}",
            "endpoint skipped, other endpoints continued",
            severity="error",
        )
        logger.error("skipping %s: %s", endpoint, exc)
        return 0

    expected = pagination.get("records")
    if expected is not None and len(records) != expected:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{endpoint}",
            f"expected {expected} records, collected {len(records)}",
            "kept what was returned and recorded the shortfall",
        )

    target = save_raw(
        SOURCE,
        f"{endpoint}.json",
        records,
        source_url=url,
        records=len(records),
        expected_records=expected,
        api_copyright="PotterDB, community maintained, no key required",
    )
    logger.info("saved %d %s to %s", len(records), endpoint, relative(target))
    return len(records)


def collect_chapters(limiter: RateLimiter, base_url: str, page_size: int) -> int:
    """Pull chapters for every book and save them as one file with a book key.

    Chapters carry no character list, only order, slug, title and summary. That
    limitation is recorded here as well as in the methods note, because the
    person reading the collection script is the one most likely to wonder why
    the network analysis does not use it.
    """
    try:
        books, _ = fetch_paginated(f"{base_url}/books", limiter, page_size, "books")
    except ApiError as exc:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.chapters",
            f"could not list books, so chapters could not be reached: {exc}",
            "chapters skipped",
            severity="error",
        )
        return 0

    all_chapters: list[dict] = []
    for book in books:
        slug = book.get("attributes", {}).get("slug")
        if not slug:
            continue
        url = f"{base_url}/books/{slug}/chapters"
        try:
            chapters, _ = fetch_paginated(url, limiter, page_size, f"chapters/{slug}")
        except ApiError as exc:
            log_data_issue(
                SCRIPT,
                f"{SOURCE}.chapters",
                f"chapters for book {slug} failed: {exc}",
                "that book's chapters skipped, remaining books continued",
            )
            continue
        # Stamp the parent book onto each chapter so the flat file stays joinable.
        for chapter in chapters:
            chapter["book_slug"] = slug
            chapter["book_title"] = book.get("attributes", {}).get("title")
        all_chapters.extend(chapters)

    target = save_raw(
        SOURCE,
        "chapters.json",
        all_chapters,
        source_url=f"{base_url}/books/<slug>/chapters",
        records=len(all_chapters),
        note=(
            "Chapters carry order, slug, title and summary only. No character "
            "list is available, which is why module 3 builds its co-occurrence "
            "network from attention data rather than from chapter membership."
        ),
    )
    logger.info("saved %d chapters to %s", len(all_chapters), relative(target))
    return len(all_chapters)


def main() -> None:
    base_url = get("sources.potterdb.base_url")
    endpoints = get("sources.potterdb.endpoints")
    page_size = int(get("sources.potterdb.page_size"))
    limiter = RateLimiter(get("sources.potterdb.min_seconds_between_calls"))

    with RunTimer(SCRIPT, logger) as run:
        total = 0
        for endpoint in endpoints:
            total += collect_endpoint(endpoint, limiter, base_url, page_size)
        total += collect_chapters(limiter, base_url, page_size)
        run.rows_out = total
        run.note = f"endpoints: {', '.join(endpoints)}, chapters"

    logger.info("PotterDB collection complete, %d records in total", total)


if __name__ == "__main__":
    main()
