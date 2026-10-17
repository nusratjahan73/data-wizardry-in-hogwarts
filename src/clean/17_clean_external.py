"""Cleaning my hand entered film and park tables, and adding inflation adjusted money.

Reading: data/external/films.csv, data/external/parks.csv,
         data/cleaned/statcan/cpi_monthly.csv
Writing: data/cleaned/parks/parks.csv
         films go to data/cleaned/films/, and I do NOT write data/cleaned/statcan/films.csv
Runtime: instant.

I adjust old money to current dollars with the consumer price index. I keep both
the nominal column and the real column, so nobody has to trust only one of them.

There is one caveat. The box office figures are in US dollars, but my price index
is Canadian. So my adjusted figure shows what those takings are worth to a Canadian
buyer today. That is the right question for a Canadian retailer deciding what to
stock, but it is not the US real box office. I name the columns so the difference
is clear: `_usd` is nominal and `_cad_real_2026` is the adjusted figure. My
exchange rate is one stated assumption, not a historic series.

I also give each park an index against the year before its wizarding land opened.
This lets me compare four parks of very different sizes on one chart.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import path
from src.utils.io import read_external, relative, save_cleaned
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "17_clean_external"
logger = get_logger(SCRIPT)

# Using one stated rate, not a historic series. One rate keeps my conversion easy
# to follow. A historic series would mix two effects, inflation and currency
# movement, in one column.
USD_TO_CAD = 1.37


def annual_cpi() -> pd.DataFrame | None:
    """Averaging the monthly CPI into one figure per year, so I can adjust yearly money."""
    cpi_file = path("data_cleaned", "statcan", "cpi_monthly.csv")
    if not cpi_file.exists():
        log_data_issue(
            SCRIPT, "external",
            "cpi_monthly.csv is missing, so money could not be inflation adjusted",
            "nominal columns only; the report must say every figure is in dollars of its own year",
            severity="error",
        )
        return None

    cpi = pd.read_csv(cpi_file)
    cpi["month"] = pd.to_datetime(cpi["month"], errors="coerce")
    cpi["year"] = cpi["month"].dt.year
    return cpi.groupby("year", as_index=False)["cpi"].mean().rename(columns={"cpi": "cpi_annual"})


def clean_films(cpi: pd.DataFrame | None) -> int:
    films = read_external("films.csv")

    for column in ["release_date", "release_date_na"]:
        films[column] = pd.to_datetime(films[column], errors="coerce").dt.date

    money_columns = [
        "budget_usd", "domestic_gross_usd", "international_gross_usd",
        "worldwide_gross_usd", "opening_weekend_domestic_usd",
    ]
    for column in money_columns:
        films[column] = pd.to_numeric(films[column], errors="coerce")

    films["release_year"] = pd.to_datetime(films["release_date"]).dt.year

    # Adding the descriptive measures my dashboard needs. My profit is gross minus
    # budget. It leaves out marketing spend and the exhibitor's share, so it is
    # higher than true profit. I label it as a gross measure everywhere.
    films["gross_profit_usd"] = films["worldwide_gross_usd"] - films["budget_usd"]
    films["gross_profit_margin"] = films["gross_profit_usd"] / films["worldwide_gross_usd"]
    films["return_on_budget"] = films["worldwide_gross_usd"] / films["budget_usd"]
    films["opening_share_of_domestic"] = (
        films["opening_weekend_domestic_usd"] / films["domestic_gross_usd"]
    )
    films["critic_audience_gap"] = films["rt_critic_score"] - films["rt_audience_score"]

    if cpi is not None:
        latest_year = int(cpi["year"].max())
        base = float(cpi.loc[cpi["year"] == latest_year, "cpi_annual"].iloc[0])
        films = films.merge(
            cpi.rename(columns={"year": "release_year"}), on="release_year", how="left"
        )
        missing = int(films["cpi_annual"].isna().sum())
        if missing:
            log_data_issue(
                SCRIPT, "external.films",
                f"{missing} films have no CPI value for their release year",
                "their real columns are left empty rather than filled with the nominal figure",
            )
        for column in money_columns:
            real_name = column.replace("_usd", "_cad_real")
            films[real_name] = films[column] * USD_TO_CAD * (base / films["cpi_annual"])

        films["cpi_base_year"] = latest_year
        films["usd_to_cad_rate_assumed"] = USD_TO_CAD
        logger.info("money adjusted to %d Canadian dollars at a rate of %.2f", latest_year, USD_TO_CAD)

    target = save_cleaned(
        "films", "films.csv", films,
        note="nominal columns end _usd; inflation adjusted columns end _cad_real",
    )
    logger.info("films: %d rows, %d columns -> %s", len(films), len(films.columns), relative(target))
    return len(films)


def clean_parks() -> int:
    parks = read_external("parks.csv")
    parks["year"] = pd.to_numeric(parks["year"], errors="coerce").astype("Int64")
    parks["attendance"] = pd.to_numeric(parks["attendance"], errors="coerce")
    parks["wizarding_land_opened"] = pd.to_datetime(
        parks["wizarding_land_opened"], errors="coerce"
    ).dt.date
    parks["opening_year"] = pd.to_datetime(parks["wizarding_land_opened"]).dt.year

    # Counting years from the opening, so I can lay four parks with different
    # timelines over one another. Year 0 is the opening year.
    parks["years_since_opening"] = parks["year"] - parks["opening_year"]

    # Indexing each park to the year before its land opened. That is the last full
    # year without the land, so it is the only honest baseline for a step change.
    baselines = (
        parks[parks["years_since_opening"] == -1]
        .loc[:, ["park", "attendance"]]
        .rename(columns={"attendance": "baseline_attendance"})
    )
    parks = parks.merge(baselines, on="park", how="left")
    parks["attendance_index_vs_year_before_opening"] = (
        parks["attendance"] / parks["baseline_attendance"] * 100
    )

    missing_baseline = parks[parks["baseline_attendance"].isna()]["park"].unique()
    if len(missing_baseline):
        log_data_issue(
            SCRIPT, "external.parks",
            f"no pre opening baseline year for: {', '.join(missing_baseline)}",
            "those parks are excluded from the indexed comparison but kept in the raw series",
        )

    # Flagging 2020 and 2021 as pandemic years. Leaving them in an average would make
    # any step change look like a collapse. I flag them and do not delete them, so
    # each of my analyses can decide for itself.
    parks["is_pandemic_year"] = parks["year"].isin([2020, 2021])

    target = save_cleaned(
        "parks", "parks.csv", parks,
        parks=sorted(parks["park"].unique().tolist()),
        note="is_pandemic_year flags 2020 and 2021; exclude them from any trend measure",
    )
    logger.info("parks: %d rows, %d parks -> %s", len(parks), parks["park"].nunique(), relative(target))
    return len(parks)


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        cpi = annual_cpi()
        film_rows = clean_films(cpi)
        park_rows = clean_parks()
        run.rows_out = film_rows + park_rows

    logger.info("external cleaning complete")


if __name__ == "__main__":
    main()
