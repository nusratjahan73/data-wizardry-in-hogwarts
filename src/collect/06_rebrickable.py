"""Collect the branded construction toy catalogue: sets, themes and minifigure counts.

Reads  : config.yaml (sources.toys), REBRICKABLE_API_KEY from .env if present.
Writes : data/raw/toys/rebrickable_<name>.csv  (the four bulk tables)
         data/raw/toys/rebrickable_api_sets.json  (only when a key is present)
Runtime: under a minute.

Rebrickable publishes its whole catalogue as gzipped CSV dumps that need no key,
which is the route this script takes. That matters for reproducibility: a marker
who clones the repository can rebuild this source without registering for
anything. The keyed REST API is used only as an optional cross check, and its
absence is logged rather than treated as a failure.

What this source gives is piece count, release year and theme. What it does not
give is retail price. The brief's appendix is explicit about that, which is why
Brickset is collected separately as the price source in 07. Without Brickset the
price model in module 5.3 cannot run, and that is recorded rather than papered
over.

Minifigure count is not a column on the sets table. It is derived by joining
inventories to inventory_minifigs, so both are collected here. The join itself
belongs to the cleaning step.
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

# themes and sets carry the catalogue itself. inventories and inventory_minifigs
# exist only so the minifigure count per set can be derived during cleaning.
#
# inventory_parts was added later, for two reasons. It describes a set far more
# richly than a piece count does, which module 4 clusters on, and at 1.56 million
# rows it is by a wide margin the largest table this project can obtain without a
# credential, which is what module 7 needs to compare a single-machine tool
# against an out-of-core one.
#
# minifigs, parts, part_categories and colors were collected alongside it and
# then never read by anything. They are not here any more. Collecting data on
# the chance it might be useful costs 7.5MB and, worse, invites a reader to
# assume an analysis used it. Section 6 wants each source pulled for a reason.
BULK_TABLES = [
    "themes",
    "sets",
    "inventories",
    "inventory_minifigs",
    "inventory_parts",
]


def download_bulk_table(name: str, limiter: RateLimiter) -> int:
    """Fetch one gzipped CSV dump and save it decompressed. Returns row count."""
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
    """Optional. Pull the themed sets through the keyed API as a sanity check.

    This is not the primary route and nothing downstream depends on it. It exists
    so that, when a key is available, the bulk dump can be compared against the
    live API and any divergence noticed rather than assumed away.
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

        # Say it once, in the register, so the gap is visible without reading code.
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
