"""Collecting the branded construction toy catalogue: sets, themes and minifigure counts.

Reading: config.yaml (sources.toys), REBRICKABLE_API_KEY from .env if present.
Writing: data/raw/toys/rebrickable_<name>.csv  (the bulk tables)
         data/raw/toys/rebrickable_api_sets.json  (only when a key is present)
Runtime: under a minute.

Rebrickable publishes its whole catalogue as gzipped CSV dumps that need no key,
and that is the route I take. It means anyone who clones my repository can
rebuild this source without registering for anything. I use the keyed REST API
only as an optional cross check. If the key is missing I log it and carry on.

This source gives me piece count, release year and theme. It does not give me
retail price, so I collect Brickset separately as the price source in 07.
Without Brickset the price model in my module 5.3 cannot run, and I record that
openly.

Minifigure count is not a column in the sets table. I get it by joining
inventories to inventory_minifigs, so I collect both here. The join itself
happens in my cleaning step.
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests

from src.utils.config import get, secret, user_agent
from src.utils.http import ApiError, RateLimiter, get_json
from src.utils.io import relative, save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "06_rebrickable"
SOURCE = "toys"
logger = get_logger(SCRIPT)

BULK_BASE = "https://cdn.rebrickable.com/media/downloads"

# Listing the bulk tables I download. themes and sets hold the catalogue itself.
# inventories and inventory_minifigs are only here so I can work out the minifigure
# count per set during cleaning.
# I added inventory_parts later, for two reasons. It describes a set in much more
# detail than a piece count does, and my module 4 clusters on it. It also has 1.56
# million rows, so it is by far the largest table I can get without a key. My module 7
# needs that size to compare a tool that works on one machine in memory against one
# that works out of core.
# I used to collect minifigs, parts, part_categories and colors too, but nothing ever
# read them, so I removed them. Collecting data that might be useful costs 7.5MB and,
# worse, lets a reader think an analysis used it. I want a reason for every table.
BULK_TABLES = [
    "themes",
    "sets",
    "inventories",
    "inventory_minifigs",
    "inventory_parts",
]


def download_bulk_table(name: str, limiter: RateLimiter) -> int:
    """Fetching one gzipped CSV dump, saving it decompressed and returning the row count."""
    url = f"{BULK_BASE}/{name}.csv.gz"
    limiter.wait()
    try:
        response = requests.get(url, headers={"User-Agent": user_agent()}, timeout=300)
        response.raise_for_status()
        body = gzip.decompress(response.content).decode("utf-8")
    except (requests.RequestException, OSError, UnicodeDecodeError) as exc:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.rebrickable.{name}",
            f"bulk download failed: {type(exc).__name__}: {exc}",
            "table skipped; any analysis needing it is blocked and says so",
            severity="error",
        )
        logger.error("bulk table %s failed: %s", name, exc)
        return 0

    rows = max(body.count("\n") - 1, 0)
    target = save_raw(
        SOURCE,
        f"rebrickable_{name}.csv",
        body,
        source_url=url,
        provider="rebrickable",
        table=name,
        rows=rows,
        key_required=False,
        note="public catalogue dump, no API key needed",
    )
    logger.info("saved rebrickable %-20s %7d rows -> %s", name, rows, relative(target))
    return rows


def cross_check_with_api(limiter: RateLimiter) -> None:
    """Pulling the themed sets through the keyed API as an optional sanity check.

    This is not my main route and nothing later depends on it. When I have a key,
    it lets me compare the bulk dump against the live API and notice any
    difference between them.
    """
    api_key = secret("REBRICKABLE_API_KEY")
    if not api_key:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.rebrickable.api",
            "REBRICKABLE_API_KEY is not set in .env",
            "keyed cross check skipped; the keyless bulk dump is the primary route "
            "and is unaffected",
            severity="note",
        )
        logger.info("REBRICKABLE_API_KEY not set, skipping the optional API cross check")
        return

    base_url = get("sources.toys.rebrickable_base_url")
    keyword = get("sources.toys.theme_keyword")
    url = f"{base_url}/sets/"
    collected: list[dict] = []
    page = 1

    while True:
        try:
            payload = get_json(
                url,
                params={"search": keyword, "page_size": 100, "page": page},
                headers={"Authorization": f"key {api_key}"},
                limiter=limiter,
                logger=logger,
            )
        except ApiError as exc:
            log_data_issue(
                SCRIPT,
                f"{SOURCE}.rebrickable.api",
                f"keyed API request failed: {exc}",
                "cross check abandoned; the bulk dump remains the source of record",
            )
            return

        collected.extend(payload.get("results", []))
        if not payload.get("next"):
            break
        page += 1

    target = save_raw(
        SOURCE,
        "rebrickable_api_sets.json",
        collected,
        source_url=url,
        provider="rebrickable",
        records=len(collected),
        search_keyword=keyword,
        note="optional cross check against the keyless bulk dump",
    )
    logger.info("API cross check saved %d sets -> %s", len(collected), relative(target))


def main() -> None:
    limiter = RateLimiter(1.0)

    with RunTimer(SCRIPT, logger) as run:
        total = 0
        for name in BULK_TABLES:
            total += download_bulk_table(name, limiter)

        cross_check_with_api(limiter)

        run.rows_out = total
        run.note = "keyless bulk catalogue dump; retail price is not in this source"

        # Logging this once in my data issues log, so the gap is clear without reading the code.
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.rebrickable",
            "Rebrickable carries piece count, year and theme but no retail price",
            "price is collected separately from Brickset in 07_brickset.py",
            severity="note",
        )

    logger.info("Rebrickable collection complete, %d rows across %d tables", total, len(BULK_TABLES))


if __name__ == "__main__":
    main()
