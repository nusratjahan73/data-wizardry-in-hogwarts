"""Cleaning the construction toy catalogue and adding the retail price where I have it.

Reading: data/raw/toys/rebrickable_*.csv, data/raw/toys/brickset_sets.json
Writing: data/cleaned/toys/sets.csv
         data/cleaned/toys/price_coverage.csv
Running time: about ten seconds.

I build the product table for module 5.3 here. It has one row per branded set with
its release year, piece count, minifigure count, theme and, when I have collected
Brickset, its retail price.

I work out the minifigure count myself. Rebrickable keeps it in a separate
inventory table, so I join sets to inventories and then to inventory minifigs, and
add up the quantities. I only use version 1 inventories. Later versions are
corrections and repeat releases, and counting them all would double some sets.

Price is optional, and I make it loud when it is missing. Rebrickable has no price
field at all, so without Brickset this table has a piece count and no money in it,
and the price model in module 5.3 cannot run. The coverage table I write next to
it says exactly how many sets have a price, so a reader can see the size of the
gap and does not have to guess it from a missing chart.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import get, path
from src.utils.io import load_raw_json, relative, save_cleaned
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "15_clean_toys"
SOURCE = "toys"
logger = get_logger(SCRIPT)


def read_bulk(name: str) -> pd.DataFrame | None:
    target = path("data_raw", SOURCE, f"rebrickable_{name}.csv")
    if not target.exists():
        log_data_issue(
            SCRIPT, f"{SOURCE}.rebrickable.{name}",
            f"{relative(target)} does not exist",
            "run 06_rebrickable.py first",
            severity="error",
        )
        return None
    return pd.read_csv(target)


def select_branded_themes(themes: pd.DataFrame) -> tuple[set[int], pd.DataFrame]:
    """Finding every theme that belongs to the franchise, including child themes.

    Rebrickable nests themes, so a set can sit under 'Fantastic Beasts' whose
    parent is 'Harry Potter'. Matching on the name alone would miss the child, so
    I follow the parent links to catch it.
    """
    keywords = ["harry potter", "fantastic beasts", "wizarding"]
    matched = themes[
        themes["name"].str.lower().str.contains("|".join(keywords), na=False)
    ]
    theme_ids = set(matched["id"].tolist())

    # Walking down the tree until no new children appear.
    while True:
        children = themes[themes["parent_id"].isin(theme_ids)]
        new_ids = set(children["id"].tolist()) - theme_ids
        if not new_ids:
            break
        theme_ids |= new_ids

    selected = themes[themes["id"].isin(theme_ids)]
    return theme_ids, selected


def minifig_counts(inventories: pd.DataFrame, inventory_minifigs: pd.DataFrame) -> pd.DataFrame:
    """Adding up the minifigures per set from the first version inventory only."""
    first_version = inventories[inventories["version"] == 1]
    joined = inventory_minifigs.merge(
        first_version[["id", "set_num"]], left_on="inventory_id", right_on="id", how="inner"
    )
    return (
        joined.groupby("set_num", as_index=False)["quantity"]
        .sum()
        .rename(columns={"quantity": "minifig_count"})
    )


def attach_brickset_prices(sets: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Joining Canadian, US and UK retail prices from Brickset if I collected it."""
    brickset_file = path("data_raw", SOURCE, "brickset_sets.json")
    if not brickset_file.exists():
        log_data_issue(
            SCRIPT, f"{SOURCE}.brickset",
            "brickset_sets.json does not exist, so no set has a retail price",
            "module 3.4 (licensing premium) and module 5.3 (price model) cannot run. "
            "Add BRICKSET_API_KEY to .env, run 07_brickset.py, then rerun this script.",
            severity="error",
        )
        logger.warning("no Brickset data; the product table will have no price column populated")
        for column in ["retail_price_cad", "retail_price_usd", "retail_price_gbp"]:
            sets[column] = pd.NA
        return sets, False

    records = load_raw_json(brickset_file)
    rows = []
    for record in records:
        prices = record.get("LEGOCom") or {}
        rows.append({
            "set_num": f"{record.get('number')}-{record.get('numberVariant', 1)}",
            "brickset_name": record.get("name"),
            "brickset_year": record.get("year"),
            "brickset_pieces": record.get("pieces"),
            "brickset_minifigs": record.get("minifigs"),
            "retail_price_cad": (prices.get("CA") or {}).get("retailPrice"),
            "retail_price_usd": (prices.get("US") or {}).get("retailPrice"),
            "retail_price_gbp": (prices.get("UK") or {}).get("retailPrice"),
        })

    prices_frame = pd.DataFrame(rows)
    merged = sets.merge(prices_frame, on="set_num", how="left")
    return merged, True


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        themes = read_bulk("themes")
        sets_raw = read_bulk("sets")
        inventories = read_bulk("inventories")
        inventory_minifigs = read_bulk("inventory_minifigs")

        if themes is None or sets_raw is None:
            logger.error("cannot build the product table without themes and sets")
            run.rows_out = 0
            return

        theme_ids, selected_themes = select_branded_themes(themes)
        logger.info(
            "matched %d themes: %s",
            len(selected_themes),
            ", ".join(f"{row.name} [{row.id}]" for row in selected_themes.itertuples()),
        )

        sets = sets_raw[sets_raw["theme_id"].isin(theme_ids)].copy()
        run.rows_in = len(sets)

        sets = sets.merge(
            themes[["id", "name"]].rename(columns={"id": "theme_id", "name": "theme_name"}),
            on="theme_id",
            how="left",
        )

        if inventories is not None and inventory_minifigs is not None:
            sets = sets.merge(minifig_counts(inventories, inventory_minifigs), on="set_num", how="left")
            sets["minifig_count"] = sets["minifig_count"].fillna(0).astype(int)
        else:
            sets["minifig_count"] = pd.NA
            log_data_issue(
                SCRIPT, f"{SOURCE}.rebrickable",
                "inventory tables missing, so minifigure count could not be derived",
                "the price model loses one predictor; the rest of the table is unaffected",
            )

        sets["num_parts"] = pd.to_numeric(sets["num_parts"], errors="coerce")
        sets["year"] = pd.to_numeric(sets["year"], errors="coerce").astype("Int64")

        year_from = int(get("sources.toys.year_from"))
        year_to = int(get("sources.toys.year_to"))
        before = len(sets)
        sets = sets[(sets["year"] >= year_from) & (sets["year"] <= year_to)]
        if before != len(sets):
            logger.info("dropped %d sets outside %d to %d", before - len(sets), year_from, year_to)

        # Flagging the sets with no pieces. Such a set is a promotional item, a poster
        # or a gift card. It is not a construction set and would spoil any price per
        # piece measure.
        promotional = int((sets["num_parts"].fillna(0) == 0).sum())
        if promotional:
            logger.info("flagged %d sets with zero pieces as promotional items", promotional)
        sets["is_promotional"] = sets["num_parts"].fillna(0) == 0

        sets, has_prices = attach_brickset_prices(sets)

        sets = sets.rename(columns={"name": "set_name"}).sort_values(["year", "set_num"])
        target = save_cleaned(
            SOURCE, "sets.csv", sets,
            themes=[str(t) for t in selected_themes["name"].tolist()],
            year_from=year_from, year_to=year_to,
            has_price_data=has_prices,
        )
        logger.info("sets: %d rows -> %s", len(sets), relative(target))

        # Writing a coverage table, so the size of the price gap is a number in a file
        # and not something a reader has to work out.
        buildable = sets[~sets["is_promotional"]]
        coverage = pd.DataFrame([{
            "sets_total": len(sets),
            "sets_buildable": len(buildable),
            "sets_promotional": int(sets["is_promotional"].sum()),
            "with_piece_count": int(buildable["num_parts"].notna().sum()),
            "with_minifig_count": int(buildable["minifig_count"].notna().sum()) if "minifig_count" in buildable else 0,
            "with_price_cad": int(buildable["retail_price_cad"].notna().sum()),
            "with_price_usd": int(buildable["retail_price_usd"].notna().sum()),
            "year_min": int(sets["year"].min()) if len(sets) else None,
            "year_max": int(sets["year"].max()) if len(sets) else None,
            "price_source_available": has_prices,
        }])
        save_cleaned(SOURCE, "price_coverage.csv", coverage)

        logger.info(
            "%d sets, %d buildable, %d with a Canadian price, years %s to %s",
            len(sets), len(buildable),
            int(buildable["retail_price_cad"].notna().sum()),
            sets["year"].min(), sets["year"].max(),
        )

        # Expecting about 213 sets. A different number is not an error, but I record
        # it so nobody quietly reports the wrong count.
        expected = 213
        if abs(len(sets) - expected) > 20:
            log_data_issue(
                SCRIPT, f"{SOURCE}.rebrickable",
                f"the catalogue holds {len(sets)} branded sets, where I expected about {expected}",
                "the difference is the collectible minifigure series and promotional items, "
                "which are flagged with is_promotional rather than deleted; report the "
                "buildable count in the write up",
                severity="note",
            )

        run.rows_out = len(sets)
        run.note = f"{len(sets)} sets, price data {'present' if has_prices else 'absent'}"


if __name__ == "__main__":
    main()
