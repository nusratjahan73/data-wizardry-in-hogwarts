"""Module 2. Build the star schema the Power BI dashboard imports.

Reads  : data/processed/*.csv
Writes : dashboard/model/dim_*.csv and dashboard/model/fact_*.csv
         dashboard/model/relationships.csv
Runtime: about ten seconds.

Section 8 asks for a star schema rather than a pile of flat tables, and for the
schema to be written down so a reader can rebuild it. This script builds it, so
the model is generated from the processed tables rather than assembled by hand
inside a file nobody can diff.

Why the tables live in dashboard/model rather than data/processed. They are not
analysis inputs; no script in src reads them. They exist only to be imported by
Power BI, and they are shaped for that: surrogate keys, conformed dimensions, no
free text where a lookup will do. Putting them beside the dashboard keeps the
deliverable together and keeps data/processed as the single source the analysis
reads. That is a departure from the folder drawing in section 4 and is recorded
in docs/word/open_questions.docx.

The grain of each fact table is stated in its docstring below and repeated in
dashboard/model_notes.md. Getting the grain wrong is the usual way a star schema
double counts, so it is written down twice on purpose.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import get, path, repo_root
from src.utils.io import read_processed, relative, write_metadata
from src.utils.logging_setup import RunTimer, get_logger

SCRIPT = "23_star_schema"
logger = get_logger(SCRIPT)

MODEL_DIR = repo_root() / "dashboard" / "model"


def save_model_table(name: str, frame: pd.DataFrame, grain: str) -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / f"{name}.csv"
    frame.to_csv(target, index=False, encoding="utf-8")
    write_metadata(target, table=name, grain=grain, rows=len(frame), columns=list(frame.columns))
    logger.info("%-26s %6d rows, %2d cols  grain: %s", name, len(frame), len(frame.columns), grain)
    return target


# --------------------------------------------------------------------------- #
# dimensions
# --------------------------------------------------------------------------- #

def dim_date() -> pd.DataFrame:
    """One row per month from 1991 to 2028. Grain: month.

    Monthly rather than daily because every fact table in this model is monthly
    or coarser. A daily date dimension would be 13,000 rows supporting nothing.
    """
    months = pd.date_range("1991-01-01", "2028-12-01", freq="MS")
    premiere = pd.Timestamp(str(get("dates.premiere")))
    eras = get("eras")

    def era_of(year: int) -> str:
        for name, (start, end) in eras.items():
            if start <= year <= end:
                return name
        return "before the films"

    frame = pd.DataFrame({"date_key": months.strftime("%Y%m").astype(int), "month_start": months})
    frame["year"] = months.year
    frame["month_number"] = months.month
    frame["month_name"] = months.strftime("%b")
    frame["quarter"] = "Q" + months.quarter.astype(str)
    frame["year_month"] = months.strftime("%Y-%m")
    frame["era"] = [era_of(y) for y in months.year]
    frame["is_gift_season"] = frame["month_number"].isin([11, 12])
    frame["is_after_premiere"] = frame["month_start"] >= premiere.replace(day=1)
    frame["months_from_premiere"] = (
        (frame["month_start"].dt.year - premiere.year) * 12
        + (frame["month_start"].dt.month - premiere.month)
    )
    frame["is_pandemic"] = frame["year"].isin([2020, 2021])
    return frame


def dim_film() -> pd.DataFrame:
    """One row per film. Grain: film."""
    films = read_processed("films.csv")
    eras = get("eras")

    def era_of(year: int) -> str:
        for name, (start, end) in eras.items():
            if start <= year <= end:
                return name
        return "unknown"

    frame = films[[
        "film_id", "title", "series", "release_date", "release_date_na",
        "rt_critic_score", "rt_audience_score", "metacritic_score", "cinemascore",
    ]].copy()
    frame["release_year"] = pd.to_datetime(films["release_date"]).dt.year
    frame["era"] = [era_of(y) for y in frame["release_year"]]
    frame["date_key"] = pd.to_datetime(films["release_date_na"]).dt.strftime("%Y%m").astype(int)
    return frame.rename(columns={"film_id": "film_key"})


def dim_character() -> pd.DataFrame:
    """One row per main-cast character with measured attention. Grain: character.

    Restricted to the sixteen mapped characters. The full 5,410-row catalogue is
    not a useful dashboard dimension: 80 per cent of it has no house, no
    attention data and no commercial relevance.
    """
    characters = read_processed("characters.csv")
    mapped = characters[characters["total_weekly_views"].notna()].copy()

    frame = pd.DataFrame({
        "character_key": mapped["slug"],
        "character_name": mapped["name"],
        "house": mapped.get("house_combined", pd.Series(dtype=object)),
        "house_source": mapped.get("house_source", pd.Series(dtype=object)),
        "species": mapped.get("species", pd.Series(dtype=object)),
        "gender": mapped.get("gender", pd.Series(dtype=object)),
        "article": mapped["article"],
    })

    centrality_file = path("outputs_tables", "character_centrality.csv")
    if centrality_file.exists():
        centrality = pd.read_csv(centrality_file)
        frame = frame.merge(
            centrality[["article", "mean_correlation", "eigenvector_centrality",
                        "attention_rank", "coupling_rank"]],
            on="article", how="left",
        )
    return frame.reset_index(drop=True)


def dim_product_theme() -> pd.DataFrame:
    """One row per construction toy theme. Grain: theme."""
    products = read_processed("products.csv")
    themes = products.groupby("theme_id", as_index=False).agg(
        theme_name=("theme_name", "first"),
        sets=("set_num", "count"),
        first_year=("year", "min"),
        last_year=("year", "max"),
    )
    return themes.rename(columns={"theme_id": "theme_key"})


def dim_country() -> pd.DataFrame:
    """One row per country appearing in the regional search interest data."""
    # The franchise group only, not every keyword group. Trends scales each
    # request to its own maximum, so taking the highest value a country reaches
    # across four independently-normalised groups is not a ranking of anything:
    # it put 30 countries on a tied 100 and moved Canada from 9th to 45th. The
    # franchise group is the one the geography claim is made from.
    trends_dir = path("data_raw", "trends")
    source_file = trends_dir / "region__a_franchise__worldwide.csv"
    if not source_file.exists():
        logger.warning("%s not found; country dimension left empty", source_file.name)
        return pd.DataFrame(
            columns=["country_key", "country_code", "country_name", "is_canada",
                     "search_interest", "interest_rank"]
        )
    frames = [pd.read_csv(source_file)]

    combined = pd.concat(frames, ignore_index=True)

    # The saved file carries a reset index in its first column, so the country
    # name is looked up by name rather than by position. Reading column zero
    # returned the row number and produced a dimension of integers.
    if "geoName" not in combined.columns:
        logger.warning("region files have no geoName column; country dimension left empty")
        return pd.DataFrame(columns=["country_key", "country_code", "country_name", "is_canada"])

    # The dimension needs a metric on it, or the Geography page has nothing to
    # show. This table is unrelated to the rest of the model by design (the
    # regional data is a snapshot, not a series, so it has no date key), which
    # means no measure can reach it and the value has to live here.
    anchor = get("sources.trends.anchor_term")
    value_column = anchor if anchor in combined.columns else None
    if value_column is None:
        logger.warning("anchor term %r not found in the region files; interest left blank", anchor)

    lookup = (
        combined[["geoName", "geoCode"] + ([value_column] if value_column else [])]
        .dropna(subset=["geoName"])
        .drop_duplicates(subset=["geoName"])
        .sort_values(value_column or "geoName", ascending=False)
        .reset_index(drop=True)
    )

    frame = pd.DataFrame({
        "country_key": range(1, len(lookup) + 1),
        "country_code": lookup["geoCode"],
        "country_name": lookup["geoName"],
        "is_canada": lookup["geoName"].str.strip().str.lower() == "canada",
    })
    frame["search_interest"] = (
        pd.to_numeric(lookup[value_column], errors="coerce") if value_column else pd.NA
    )
    frame["interest_rank"] = frame["search_interest"].rank(ascending=False, method="min")
    return frame


# --------------------------------------------------------------------------- #
# facts
# --------------------------------------------------------------------------- #

def fact_film_performance() -> pd.DataFrame:
    """Grain: one row per film. Additive on the money columns."""
    films = read_processed("films.csv")
    columns = [
        "film_id", "budget_usd", "domestic_gross_usd", "international_gross_usd",
        "worldwide_gross_usd", "opening_weekend_domestic_usd", "gross_profit_usd",
        "gross_profit_margin", "return_on_budget", "opening_share_of_domestic",
        "critic_audience_gap",
    ]
    real_columns = [c for c in films.columns if c.endswith("_cad_real")]
    frame = films[[c for c in columns if c in films.columns] + real_columns].copy()
    frame["date_key"] = pd.to_datetime(films["release_date_na"]).dt.strftime("%Y%m").astype(int)
    return frame.rename(columns={"film_id": "film_key"})


def fact_attention_monthly() -> pd.DataFrame:
    """Grain: one row per series per month.

    Rolled from weekly to monthly so it joins the date dimension, which is
    monthly. Weekly and monthly facts in one model with one date table is the
    classic way to double count, so only one grain is published.
    """
    attention = read_processed("attention_weekly.csv")
    attention["week"] = pd.to_datetime(attention["week"])
    attention["month_start"] = attention["week"].values.astype("datetime64[M]")

    monthly = attention.groupby(
        ["source", "group", "series", "month_start"], as_index=False
    ).agg(mean_weekly_value=("value", "mean"), weeks=("value", "count"))

    monthly["date_key"] = monthly["month_start"].dt.strftime("%Y%m").astype(int)
    return monthly.drop(columns=["month_start"])


def fact_retail_monthly() -> pd.DataFrame:
    """Grain: one row per NAICS category per month."""
    retail = read_processed("retail_monthly.csv")
    frame = retail[[
        "naics_code", "naics_name", "sales_thousands_cad", "sales_thousands_cad_real",
        "is_focus_category", "is_total_retail",
    ]].copy()
    frame["date_key"] = pd.to_datetime(retail["month"]).dt.strftime("%Y%m").astype(int)
    return frame


def fact_product_release() -> pd.DataFrame:
    """Grain: one row per construction set."""
    products = read_processed("products.csv")
    columns = [
        "set_num", "set_name", "theme_id", "year", "num_parts", "minifig_count",
        "is_promotional", "retail_price_cad", "price_per_piece_cad",
    ]
    frame = products[[c for c in columns if c in products.columns]].copy()
    # Sets are released in a year, not a month; January is used as the anchor so
    # the join to a monthly date dimension is well defined and documented.
    frame["date_key"] = (pd.to_numeric(frame["year"], errors="coerce") * 100 + 1).astype("Int64")
    return frame.rename(columns={"set_num": "set_key", "theme_id": "theme_key"})


def fact_park_attendance() -> pd.DataFrame:
    """Grain: one row per park per year."""
    parks = pd.read_csv(path("data_cleaned", "parks", "parks.csv"))
    frame = parks[[
        "park", "country", "year", "attendance", "wizarding_land_open_this_year",
        "years_since_opening", "attendance_index_vs_year_before_opening", "is_pandemic_year",
    ]].copy()
    frame["date_key"] = (frame["year"] * 100 + 1).astype("Int64")
    return frame


def relationships() -> pd.DataFrame:
    """The relationships a reader has to recreate in Power BI."""
    rows = [
        ("dim_date", "date_key", "fact_film_performance", "date_key", "one-to-many", "single"),
        ("dim_date", "date_key", "fact_attention_monthly", "date_key", "one-to-many", "single"),
        ("dim_date", "date_key", "fact_retail_monthly", "date_key", "one-to-many", "single"),
        ("dim_date", "date_key", "fact_product_release", "date_key", "one-to-many", "single"),
        ("dim_date", "date_key", "fact_park_attendance", "date_key", "one-to-many", "single"),
        ("dim_film", "film_key", "fact_film_performance", "film_key", "one-to-one", "both"),
        ("dim_product_theme", "theme_key", "fact_product_release", "theme_key", "one-to-many", "single"),
        ("dim_character", "article", "fact_attention_monthly", "series", "one-to-many", "single"),
    ]
    return pd.DataFrame(rows, columns=[
        "from_table", "from_column", "to_table", "to_column", "cardinality", "cross_filter",
    ])


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        total = 0

        for name, builder, grain in [
            ("dim_date", dim_date, "month"),
            ("dim_film", dim_film, "film"),
            ("dim_character", dim_character, "character"),
            ("dim_product_theme", dim_product_theme, "theme"),
            ("dim_country", dim_country, "country"),
            ("fact_film_performance", fact_film_performance, "film"),
            ("fact_attention_monthly", fact_attention_monthly, "source + group + series + month"),
            ("fact_retail_monthly", fact_retail_monthly, "naics_code + month"),
            ("fact_product_release", fact_product_release, "set"),
            ("fact_park_attendance", fact_park_attendance, "park + year"),
        ]:
            frame = builder()
            save_model_table(name, frame, grain)
            total += len(frame)

        save_model_table("relationships", relationships(), "relationship")

        run.rows_out = total
        run.note = f"star schema written to {relative(MODEL_DIR)}"

    logger.info("star schema complete, %d fact and dimension rows", total)


if __name__ == "__main__":
    main()
