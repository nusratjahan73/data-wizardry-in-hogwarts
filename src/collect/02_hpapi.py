"""Collecting character attributes from the HP API.

Reading: config.yaml (sources.hpapi).
Writing: data/raw/hpapi/characters.json, data/raw/hpapi/spells.json.
Runtime: a few seconds.

PotterDB already has characters, but its house field is often empty across its
five thousand minor records. The HP API returns a much smaller set, with house,
species, wand and patronus filled in reliably. So I use both: PotterDB gives me
coverage, and the HP API gives me complete attributes for the well known
characters. My module 1 joins them on a normalised name.

Each resource is one call with no pagination and no key, so I only wait a
second between calls to be polite.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import get
from src.utils.http import ApiError, RateLimiter, get_json
from src.utils.io import relative, save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "02_hpapi"
SOURCE = "hpapi"
logger = get_logger(SCRIPT)


def main() -> None:
    base_url = get("sources.hpapi.base_url")
    endpoints = get("sources.hpapi.endpoints")
    limiter = RateLimiter(1.0)

    with RunTimer(SCRIPT, logger) as run:
        total = 0
        for endpoint in endpoints:
            url = f"{base_url}/{endpoint}"
            try:
                records = get_json(url, limiter=limiter, logger=logger)
            except ApiError as exc:
                log_data_issue(
                    SCRIPT,
                    f"{SOURCE}.{endpoint}",
                    f"request failed: {exc}",
                    "endpoint skipped; PotterDB remains the primary character source",
                    severity="error",
                )
                logger.error("skipping %s: %s", endpoint, exc)
                continue

            if not isinstance(records, list):
                log_data_issue(
                    SCRIPT,
                    f"{SOURCE}.{endpoint}",
                    f"expected a JSON list, received {type(records).__name__}",
                    "saved the response unchanged for inspection",
                )

            target = save_raw(
                SOURCE,
                f"{endpoint}.json",
                records,
                source_url=url,
                records=len(records) if isinstance(records, list) else None,
            )
            count = len(records) if isinstance(records, list) else 0
            total += count
            logger.info("saved %d %s to %s", count, endpoint, relative(target))

        run.rows_out = total

    logger.info("HP API collection complete, %d records in total", total)


if __name__ == "__main__":
    main()
