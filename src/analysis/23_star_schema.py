"""Building the star schema that my Power BI dashboard imports (module 2).

Reading: data/processed/*.csv
Writing: dashboard/model/dim_*.csv and dashboard/model/fact_*.csv
         dashboard/model/relationships.csv
Runtime: about ten seconds.

I want a star schema and not a pile of flat tables, and I want it written down so
a reader can rebuild it. This script builds the model from my processed tables, so
it is not put together by hand inside a file nobody can diff.

I keep these tables in dashboard/model and not in data/processed. They are not
analysis inputs, and no script in src reads them. They exist only for Power BI to
import, and I shaped them for that: surrogate keys, conformed dimensions, no free
text where a lookup will do. Keeping them beside the dashboard keeps that work
together, and data/processed stays the single source my analysis reads. This is
different from my planned folder layout, and I noted it in
docs/word/open_questions.docx.

I state the grain of each fact table in its docstring below and again in
dashboard/model_notes.md. Getting the grain wrong is the usual way a star schema
double counts, so I write it down twice on purpose.
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


# Building the dimension tables.

def dim_date() -> pd.DataFrame:
    """Building one row per month from 1991 to 2028. Grain: month.

    I use months and not days because every fact table in my model is monthly
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
    """Building one row per film. Grain: film."""
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
    """Building one row per main cast character with measured attention. Grain: character.

    I keep only the sixteen mapped characters. The full catalogue of 5,410 rows is
    not a useful dashboard dimension, because 80 per cent of it has no house, no
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
    """Building one row per construction toy theme. Grain: theme."""
    products = read_processed("products.csv")
    themes = products.groupby("theme_id", as_index=False).agg(
        theme_name=("theme_name", "first"),
        sets=("set_num", "count"),
        first_year=("year", "min"),
        last_year=("year", "max"),
    )
    return themes.rename(columns={"theme_id": "theme_key"})


def dim_country() -> pd.DataFrame:
    """Building one row per country that appears in my regional search interest data."""
    # Using the franchise group only, not every keyword group. Trends scales each
    # request to its own maximum, so the highest value a country reaches across
    # four groups that were each scaled on their own is not a ranking of anything.
    # It put 30 countries on a tied 100 and moved Canada from 9th to 45th. I make
    # my geography claim from the franchise group.
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

    # Looking up the country column by name and not by position, because the saved
    # file has a reset index in its first column. Reading column zero gave me the
    # row number and a dimension full of integers.
    if "geoName" not in combined.columns:
        logger.warning("region files have no geoName column; country dimension left empty")
        return pd.DataFrame(columns=["country_key", "country_code", "country_name", "is_canada"])

    # Putting a metric on this dimension, or my Geography page has nothing to
    # show. I left this table unrelated to the rest of the model on purpose. The
    # regional data is a snapshot, not a series, so it has no date key. That
    # means no measure can reach it, and the value has to live here.
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


# Building the fact tables.

def fact_film_performance() -> pd.DataFrame:
    """Building the film fact table. Grain: one row per film. Additive on the money columns."""
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
    """Building the attention fact table. Grain: one row per series per month.

    I roll weekly up to monthly so it joins my date dimension, which is monthly.
    Mixing weekly and monthly facts in one model with one date table is the
    classic way to double count, so I publish only one grain.
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
    """Building the retail fact table. Grain: one row per NAICS category per month."""
    retail = read_processed("retail_monthly.csv")
    frame = retail[[
        "naics_code", "naics_name", "sales_thousands_cad", "sales_thousands_cad_real",
        "is_focus_category", "is_total_retail",
    ]].copy()
    frame["date_key"] = pd.to_datetime(retail["month"]).dt.strftime("%Y%m").astype(int)
    return frame


def fact_product_release() -> pd.DataFrame:
    """Building the product fact table. Grain: one row per construction set."""
    products = read_processed("products.csv")
    columns = [
        "set_num", "set_name", "theme_id", "year", "num_parts", "minifig_count",
        "is_promotional", "retail_price_cad", "price_per_piece_cad",
    ]
    frame = products[[c for c in columns if c in products.columns]].copy()
    # Using January as the anchor month, because sets are released in a year, not
    # a month. This way the join to my monthly date dimension is clear and written down.
    frame["date_key"] = (pd.to_numeric(frame["year"], errors="coerce") * 100 + 1).astype("Int64")
    return frame.rename(columns={"set_num": "set_key", "theme_id": "theme_key"})


def fact_park_attendance() -> pd.DataFrame:
    """Building the park fact table. Grain: one row per park per year."""
    parks = pd.read_csv(path("data_cleaned", "parks", "parks.csv"))
    frame = parks[[
        "park", "country", "year", "attendance", "wizarding_land_open_this_year",
        "years_since_opening", "attendance_index_vs_year_before_opening", "is_pandemic_year",
    ]].copy()
    frame["date_key"] = (frame["year"] * 100 + 1).astype("Int64")
    return frame


def relationships() -> pd.DataFrame:
    """Listing the relationships a reader has to recreate in Power BI."""
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
