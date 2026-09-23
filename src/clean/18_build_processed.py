"""Build the joined, analysis ready tables in data/processed.

Reads  : every table under data/cleaned.
Writes : data/processed/{films,characters,attention_weekly,retail_monthly,products}.csv
Runtime: about thirty seconds.

This is the only place in the project where sources are joined, and the only
folder the analysis scripts may read. Section 4 is strict about that for a
reason: if joins happen inside analysis scripts, two analyses that ought to agree
quietly diverge because one of them joined slightly differently.

The five tables the brief asks for:

  films             one row per film, performance and reception together
  characters        one row per character, PotterDB coverage plus HP API detail,
                    plus measured attention from Wikipedia
  attention_weekly  one row per week per series, the forecast's input
  retail_monthly    Canadian category and total retail sales, inflation adjusted
  products          one row per branded construction set

Each is given a primary key that is checked for uniqueness before it is written,
because a silently duplicated key is the failure mode that produces a plausible
looking but wrong answer three modules later.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import get, path
from src.utils.io import relative, save_processed
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "19_build_processed"
logger = get_logger(SCRIPT)


def read_cleaned_if_present(source: str, filename: str) -> pd.DataFrame | None:
    target = path("data_cleaned", source, filename)
    if not target.exists():
        logger.warning("%s is missing", relative(target))
        return None
    return pd.read_csv(target, low_memory=False)


def check_key(frame: pd.DataFrame, key: list[str], table_name: str) -> None:
    """Refuse to write a table whose primary key is not unique."""
    duplicates = int(frame.duplicated(subset=key).sum())
    if duplicates:
        log_data_issue(
            SCRIPT, table_name,
            f"primary key {key} is not unique: {duplicates} duplicate rows",
            "duplicates dropped, keeping the first of each; investigate the join",
            severity="error",
        )
        raise ValueError(
            f"{table_name} has {duplicates} duplicate rows on {key}. "
            f"Fix the join rather than writing a table that cannot be trusted."
        )


def name_key(name: object) -> str:
    """Same normalisation the HP API cleaner uses, so the join keys match."""
    if not isinstance(name, str):
        return ""
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def build_films() -> int:
    """One row per film. The cleaned film table is already the join of three sources."""
    films = read_cleaned_if_present("films", "films.csv")
    if films is None:
        log_data_issue(SCRIPT, "films", "cleaned film table missing", "run 17_clean_external.py", severity="error")
        return 0

    # Attach PotterDB's own figures beside the sourced ones, so the dashboard can
    # show the discrepancy rather than the report merely asserting it.
    potterdb = read_cleaned_if_present("potterdb", "movies.csv")
    if potterdb is not None:
        potterdb = potterdb.assign(title_key=potterdb["title"].map(name_key))
        films = films.assign(title_key=films["title"].map(name_key))
        films = films.merge(
            potterdb[["title_key", "potterdb_budget_usd", "potterdb_box_office_usd"]],
            on="title_key", how="left",
        )
        matched = int(films["potterdb_box_office_usd"].notna().sum())
        logger.info("matched %d of %d films to PotterDB for the source comparison", matched, len(films))

        # Quantify the disagreement, since the methods note claims it exists.
        films["potterdb_box_office_error_ratio"] = (
            films["potterdb_box_office_usd"] / films["worldwide_gross_usd"]
        )
        films = films.drop(columns=["title_key"])

    check_key(films, ["film_id"], "films")
    target = save_processed("films.csv", films, primary_key="film_id", source_count=4)
    logger.info("films: %d rows, %d columns -> %s", len(films), len(films.columns), relative(target))
    return len(films)


def build_characters() -> int:
    """One row per character: PotterDB breadth, HP API detail, measured attention."""
    potterdb = read_cleaned_if_present("potterdb", "characters.csv")
    if potterdb is None:
        log_data_issue(SCRIPT, "characters", "cleaned PotterDB characters missing", "run 10_clean_potterdb.py", severity="error")
        return 0

    characters = potterdb.copy()
    characters["name_key"] = characters["name"].map(name_key)

    # PotterDB has 5410 rows and many are duplicates by name (variants, unnamed
    # background characters). The key is the PotterDB id, not the name.
    hpapi = read_cleaned_if_present("hpapi", "characters.csv")
    if hpapi is not None:
        # Keep one HP API row per name so the join cannot multiply rows.
        hpapi_unique = hpapi.sort_values("name").drop_duplicates(subset=["name_key"], keep="first")
        overlap_columns = [
            c for c in ["house", "species", "patronus", "wand_wood", "wand_core", "actor", "hogwarts_student", "hogwarts_staff"]
            if c in hpapi_unique.columns
        ]
        characters = characters.merge(
            hpapi_unique[["name_key", *overlap_columns]].add_prefix("hpapi_").rename(
                columns={"hpapi_name_key": "name_key"}
            ),
            on="name_key", how="left",
        )
        matched = int(characters["hpapi_house"].notna().sum()) if "hpapi_house" in characters else 0
        logger.info("matched %d characters to the HP API", matched)

        # House from either source, preferring the curated one. Recorded so a
        # reader can see which source supplied each value.
        if "hpapi_house" in characters.columns:
            characters["house_combined"] = characters["hpapi_house"].fillna(characters.get("house"))
            characters["house_source"] = characters["hpapi_house"].notna().map(
                {True: "hp_api", False: "potterdb"}
            )
            characters.loc[characters["house_combined"].isna(), "house_source"] = "unknown"

    # Measured attention per character, which is what the product recommendation
    # actually needs: not who is important in the books, but who people look up.
    weekly = read_cleaned_if_present("pageviews", "pageviews_weekly.csv")
    if weekly is not None:
        character_views = weekly[weekly["group"] == "characters"]
        if not character_views.empty:
            summary = (
                character_views.groupby("article", as_index=False)
                .agg(
                    total_weekly_views=("views", "sum"),
                    mean_weekly_views=("views", "mean"),
                    peak_weekly_views=("views", "max"),
                    weeks_observed=("views", "count"),
                )
            )
            # Joined on the explicit article to slug map in config, not on a
            # normalised name. See the comment beside that map: name matching
            # silently drops most of the main cast and mispairs Sirius Black
            # with his grandfather.
            article_to_slug = get("sources.pageviews.character_article_to_potterdb_slug")
            summary["slug"] = summary["article"].map(article_to_slug)

            unmapped = summary[summary["slug"].isna()]["article"].tolist()
            if unmapped:
                log_data_issue(
                    SCRIPT, "characters",
                    f"{len(unmapped)} character articles have no entry in the article to slug map: "
                    f"{', '.join(unmapped)}",
                    "their attention is not attached to any character; add them to "
                    "sources.pageviews.character_article_to_potterdb_slug in config.yaml",
                )

            summary = summary.dropna(subset=["slug"]).drop_duplicates(subset=["slug"], keep="first")
            characters = characters.merge(summary, on="slug", how="left")

            measured = int(characters["total_weekly_views"].notna().sum())
            expected = int(summary["slug"].nunique())
            logger.info("attached measured attention to %d of %d mapped characters", measured, expected)
            if measured < expected:
                missing = sorted(set(summary["slug"]) - set(characters.loc[characters["total_weekly_views"].notna(), "slug"]))
                log_data_issue(
                    SCRIPT, "characters",
                    f"{expected - measured} mapped slugs matched no PotterDB character: {', '.join(missing)}",
                    "check the slug spelling in config against data/cleaned/potterdb/characters.csv",
                    severity="error",
                )

    check_key(characters, ["id"], "characters")
    target = save_processed("characters.csv", characters, primary_key="id")
    logger.info("characters: %d rows, %d columns -> %s", len(characters), len(characters.columns), relative(target))
    return len(characters)


def build_attention_weekly() -> int:
    """One row per week per series, from both attention sources.

    Pageviews and search interest measure different things and are on different
    scales, so they are stacked in long form with a `source` column rather than
    joined side by side. Anything that needs them together must decide explicitly
    how to combine them, which is the point.
    """
    parts: list[pd.DataFrame] = []

    weekly_views = read_cleaned_if_present("pageviews", "pageviews_weekly.csv")
    if weekly_views is not None:
        views = weekly_views.rename(columns={"week_start": "week", "article": "series"})
        views["source"] = "wikipedia_pageviews"
        views["unit"] = "views"
        views = views.rename(columns={"views": "value"})
        parts.append(views[["week", "series", "group", "source", "unit", "value"]])

    weekly_interest = read_cleaned_if_present("trends", "interest_weekly.csv")
    if weekly_interest is not None:
        interest = weekly_interest.rename(columns={"date": "week", "term": "series"})
        interest["source"] = "google_trends"
        interest["unit"] = "index_0_100"
        interest["group"] = interest["group"] + "_" + interest["geo"]
        interest = interest.rename(columns={"interest_index": "value"})
        parts.append(interest[["week", "series", "group", "source", "unit", "value"]])

    if not parts:
        log_data_issue(
            SCRIPT, "attention_weekly",
            "neither attention source produced a weekly series",
            "the forecast has no input; stage 1 of section 16 has failed",
            severity="critical",
        )
        return 0

    attention = pd.concat(parts, ignore_index=True)
    attention["week"] = pd.to_datetime(attention["week"], errors="coerce").dt.date
    attention = attention.dropna(subset=["week", "value"]).sort_values(["source", "series", "week"])

    # The group belongs in the key. The anchor term appears in every Trends
    # keyword group by design, and each geography is a separate pull, so
    # source + series + week alone is not unique and never was.
    check_key(attention, ["source", "group", "series", "week"], "attention_weekly")
    target = save_processed(
        "attention_weekly.csv", attention,
        primary_key="source + group + series + week",
        sources=sorted(attention["source"].unique().tolist()),
        note="long form on purpose: the two sources are not on a common scale",
    )
    logger.info(
        "attention_weekly: %d rows, %d series, %s to %s -> %s",
        len(attention), attention["series"].nunique(),
        attention["week"].min(), attention["week"].max(), relative(target),
    )
    return len(attention)


def build_retail_monthly() -> int:
    """Canadian monthly retail sales, inflation adjusted, with the category flagged."""
    retail = read_cleaned_if_present("statcan", "retail_sales_monthly.csv")
    if retail is None:
        log_data_issue(SCRIPT, "retail_monthly", "cleaned retail series missing", "run 14_clean_statcan.py", severity="error")
        return 0

    retail["month"] = pd.to_datetime(retail["month"], errors="coerce")

    cpi = read_cleaned_if_present("statcan", "cpi_monthly.csv")
    if cpi is not None:
        cpi["month"] = pd.to_datetime(cpi["month"], errors="coerce")
        base_month = cpi["month"].max()
        base_value = float(cpi.loc[cpi["month"] == base_month, "cpi"].iloc[0])
        retail = retail.merge(cpi[["month", "cpi"]], on="month", how="left")
        retail["sales_thousands_cad_real"] = (
            retail["sales_thousands_cad"] * base_value / retail["cpi"]
        )
        retail["cpi_base_month"] = base_month.date()
        logger.info("retail deflated to %s dollars", base_month.date())
    else:
        retail["sales_thousands_cad_real"] = pd.NA
        log_data_issue(
            SCRIPT, "retail_monthly", "no CPI series, so sales could not be deflated",
            "nominal only; say so wherever a long run comparison is made", severity="error",
        )

    focus = get("sources.statcan.naics_focus")
    control = get("sources.statcan.naics_control")
    retail["is_focus_category"] = retail["naics_code"] == focus
    retail["is_total_retail"] = retail["naics_code"] == control

    retail["year"] = retail["month"].dt.year
    retail["month_number"] = retail["month"].dt.month
    retail["month"] = retail["month"].dt.date

    check_key(retail, ["naics_code", "month"], "retail_monthly")
    target = save_processed(
        "retail_monthly.csv", retail,
        primary_key="naics_code + month",
        focus_category=focus, control_category=control,
    )
    logger.info(
        "retail_monthly: %d rows, %s to %s -> %s",
        len(retail), retail["month"].min(), retail["month"].max(), relative(target),
    )
    return len(retail)


def build_products() -> int:
    """One row per branded construction set, with price per piece where possible."""
    sets = read_cleaned_if_present("toys", "sets.csv")
    if sets is None:
        log_data_issue(SCRIPT, "products", "cleaned toy table missing", "run 15_clean_toys.py", severity="error")
        return 0

    products = sets.copy()

    if "retail_price_cad" in products.columns:
        price = pd.to_numeric(products["retail_price_cad"], errors="coerce")
        pieces = pd.to_numeric(products["num_parts"], errors="coerce")
        products["price_per_piece_cad"] = price / pieces.where(pieces > 0)

        # Real price needs an annual CPI, joined on release year.
        cpi = read_cleaned_if_present("statcan", "cpi_monthly.csv")
        if cpi is not None:
            cpi["month"] = pd.to_datetime(cpi["month"], errors="coerce")
            annual = cpi.assign(year=cpi["month"].dt.year).groupby("year", as_index=False)["cpi"].mean()
            base_year = int(annual["year"].max())
            base_value = float(annual.loc[annual["year"] == base_year, "cpi"].iloc[0])
            products = products.merge(annual, on="year", how="left")
            products["retail_price_cad_real"] = price * base_value / products["cpi"]
            products["price_per_piece_cad_real"] = (
                products["retail_price_cad_real"] / pieces.where(pieces > 0)
            )
            products["cpi_base_year"] = base_year

        with_price = int(price.notna().sum())
        if with_price == 0:
            log_data_issue(
                SCRIPT, "products",
                "no set has a retail price, so price per piece is empty throughout",
                "module 3.4 and module 5.3 are blocked until BRICKSET_API_KEY is set "
                "and 07_brickset.py has run",
                severity="error",
            )

    check_key(products, ["set_num"], "products")
    target = save_processed("products.csv", products, primary_key="set_num")
    logger.info("products: %d rows, %d columns -> %s", len(products), len(products.columns), relative(target))
    return len(products)


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        total = 0
        total += build_films()
        total += build_characters()
        total += build_attention_weekly()
        total += build_retail_monthly()
        total += build_products()
        run.rows_out = total

    logger.info("processed tables built, %d rows in total", total)


if __name__ == "__main__":
    main()
