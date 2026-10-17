"""Collecting retail prices for the branded construction toy line from Brickset.

Reading: config.yaml (sources.toys), BRICKSET_API_KEY from .env.
Writing: data/raw/toys/brickset_sets.json
Runtime: about a minute once a key is present.

This is my only price source. Rebrickable, which I collect in 06, has piece
counts but no retail price. So the price model in my module 5.3 and the
licensing premium test in my module 3.4 both need this script to work.

Brickset needs a free API key. Without one I log the missing key by name, write
an entry to logs/data_issues.md and exit cleanly. I do not crash and I do not
scrape the website. Brickset publishes an API so that people do not scrape it,
and in my module 8 I want to say truthfully that I collected every source the
way its owner asked.

Getting a key: register a free Brickset account, then request an API key from
the profile page. Put it in .env as BRICKSET_API_KEY. Nothing else changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import get, secret
from src.utils.http import ApiError, RateLimiter, get_json
from src.utils.io import relative, save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "07_brickset"
SOURCE = "toys"
logger = get_logger(SCRIPT)

PAGE_SIZE = 500  # Using the documented Brickset maximum per request


def fetch_page(base_url: str, api_key: str, theme: str, page: int, limiter: RateLimiter) -> dict:
    """Requesting one page of sets for a theme.

    Brickset takes its query as a JSON string in a `params` field. That is why I
    turn the parameters into JSON and do not pass them as normal query keys.
    """
    params = {
        "apiKey": api_key,
        "userHash": "",  # Leaving this empty, since only a user's own collection needs it
        "params": json.dumps({"theme": theme, "pageSize": PAGE_SIZE, "pageNumber": page}),
    }
    return get_json(f"{base_url}/getSets", params=params, limiter=limiter, logger=logger)


def collect_theme(base_url: str, api_key: str, theme: str, limiter: RateLimiter) -> list[dict]:
    """Walking through every page for one theme and returning the set records."""
    collected: list[dict] = []
    page = 1

    while True:
        try:
            payload = fetch_page(base_url, api_key, theme, page, limiter)
        except ApiError as exc:
            log_data_issue(
                SCRIPT,
                f"{SOURCE}.brickset.{theme}",
                f"request failed on page {page}: {exc}",
                "theme abandoned; whatever was already collected is kept",
                severity="error",
            )
            break

        if payload.get("status") != "success":
            log_data_issue(
                SCRIPT,
                f"{SOURCE}.brickset.{theme}",
                f"API returned status '{payload.get('status')}': {payload.get('message', '')}",
                "theme skipped; check that the key is valid and not over its daily quota",
                severity="error",
            )
            break

        sets = payload.get("sets", [])
        collected.extend(sets)
        matches = payload.get("matches", 0)
        logger.info("theme '%s' page %d: %d sets (%d matched)", theme, page, len(sets), matches)

        if len(collected) >= matches or not sets:
            break
        page += 1

    return collected


def main() -> None:
    api_key = secret("BRICKSET_API_KEY")

    with RunTimer(SCRIPT, logger) as run:
        if not api_key:
            log_data_issue(
                SCRIPT,
                f"{SOURCE}.brickset",
                "BRICKSET_API_KEY is not set in .env, so no retail price could be collected",
                "module 3.4 (licensing premium) and module 5.3 (price model) are blocked. "
                "Register a free Brickset key, add it to .env, rerun this script alone, "
                "then rerun the cleaning and modelling steps. Nothing else is affected.",
                severity="error",
            )
            logger.error(
                "BRICKSET_API_KEY not set. This is the only retail price source, so the "
                "price analyses cannot run until a key is provided. Skipping cleanly."
            )
            run.rows_out = 0
            run.note = "skipped, no API key"
            return

        base_url = get("sources.toys.brickset_base_url")
        # Requesting both themes and combining them, because Brickset lists the two
        # separately and does not put one under the other.
        themes = ["Harry Potter", "Fantastic Beasts"]
        limiter = RateLimiter(2.0)

        everything: list[dict] = []
        for theme in themes:
            everything.extend(collect_theme(base_url, api_key, theme, limiter))

        if not everything:
            log_data_issue(
                SCRIPT,
                f"{SOURCE}.brickset",
                "a key was present but no sets were returned for either theme",
                "price analyses blocked; verify the key and the theme names",
                severity="error",
            )
            run.rows_out = 0
            return

        with_price = sum(
            1 for s in everything if (s.get("LEGOCom") or {}).get("CA", {}).get("retailPrice")
        )
        target = save_raw(
            SOURCE,
            "brickset_sets.json",
            everything,
            source_url=f"{base_url}/getSets",
            provider="brickset",
            records=len(everything),
            records_with_ca_price=with_price,
            themes=themes,
            note="this is the retail price source; Rebrickable carries no price",
        )

        if with_price < len(everything) / 2:
            log_data_issue(
                SCRIPT,
                f"{SOURCE}.brickset",
                f"only {with_price} of {len(everything)} sets carry a Canadian retail price",
                "price analyses fall back to the US price converted at a stated rate, "
                "or drop the sets with no price and say how many were dropped",
            )

        run.rows_out = len(everything)
        run.note = f"{with_price} of {len(everything)} sets carry a Canadian price"
        logger.info("saved %d sets -> %s", len(everything), relative(target))


if __name__ == "__main__":
    main()
