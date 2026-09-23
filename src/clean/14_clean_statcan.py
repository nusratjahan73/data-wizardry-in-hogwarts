"""Clean Canadian retail sales and CPI, chaining the archived and active retail tables.

Reads  : data/raw/statcan/csv/{20100056,20100008,18100004}.csv
Writes : data/cleaned/statcan/retail_sales_monthly.csv
         data/cleaned/statcan/cpi_monthly.csv
         data/cleaned/statcan/retail_chain_check.csv
Runtime: about a minute; the CPI table is 1.15 million rows before filtering.

The chaining is the part worth reading.

Table 20-10-0056 is active but begins in January 2017. Nine years is not enough
history to separate a seasonal pattern from a trend with any confidence. Table
20-10-0008 reaches back to 1991 but was archived in December 2022. Neither alone
is adequate; together they cover 1991 to 2026 with a six year overlap.

There is a second problem underneath the first, and it is the one that would
have done real damage. The archived table is coded to NAICS 2017 and the active
one to NAICS 2022. The revision renumbered the category this project is about:
"Sporting goods, hobby, book and music stores [451]" became "Sporting goods,
hobby, musical instrument, book retailers and news dealers [459A]". Concatenating
the two tables on the code alone therefore leaves the focus category with no
history before 2017 at all, silently, while total retail trade looks fine
because its code never changed. The crosswalk in config.yaml maps the old codes
to the new ones, and the overlap check below then measures how well each mapped
pair actually agrees, so an approximate mapping is reported as approximate.

The two are chained on that overlap rather than simply concatenated. For each
series, the ratio between the two tables is measured across every month they
share, and the historical table is multiplied by the median of those ratios
before the pre 2017 part of it is used. If the two tables agreed exactly the
factor would be 1.0 and the chain would be a plain join; measuring it instead of
assuming it is what turns a hopeful join into a checked one. The measured
factors and the overlap disagreement are written to retail_chain_check.csv so a
reader can see how well the two sources actually line up.

Only unadjusted data is kept. Seasonally adjusted figures have had the very
pattern this project is trying to measure removed from them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from src.utils.config import get, path
from src.utils.io import relative, save_cleaned
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "14_clean_statcan"
SOURCE = "statcan"
logger = get_logger(SCRIPT)

# The StatCan bulk CSV uses these column names. Kept in one place so a rename at
# source is a one line fix rather than a hunt.
COL_DATE = "REF_DATE"
COL_GEO = "GEO"
COL_VALUE = "VALUE"
COL_NAICS = "North American Industry Classification System (NAICS)"
COL_ADJUST = "Adjustments"
COL_SALES = "Sales"
COL_PRODUCTS = "Products and product groups"


def load_table(product_id: int) -> pd.DataFrame | None:
    source_file = path("data_raw", SOURCE, "csv", f"{product_id}.csv")
    if not source_file.exists():
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}",
            f"{relative(source_file)} does not exist",
            "table skipped; run 05_statcan.py to collect it",
            severity="error",
        )
        return None
    return pd.read_csv(source_file, low_memory=False)


def extract_naics_code(text: object) -> str | None:
    """Pull the bracketed NAICS code out of a member name.

    The CSV writes the classification as 'Sporting goods ... [459A]'. The code is
    the stable identifier; the wording of the label has changed between vintages
    of the classification, so matching on the code rather than the name is what
    lets the archived and active tables be compared at all.
    """
    if not isinstance(text, str) or "[" not in text:
        return None
    return text.rsplit("[", 1)[1].rstrip("]").strip()


def tidy_retail(
    frame: pd.DataFrame,
    table_label: str,
    geography: str,
    adjustment: str,
    crosswalk: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Filter one retail table to Canada, unadjusted, and tidy it.

    When a crosswalk is supplied, the NAICS 2017 codes in the archived table are
    translated to their NAICS 2022 equivalents so the two tables can be compared
    at all. The original code is kept in `naics_code_original` so the translation
    is auditable rather than invisible.
    """
    working = frame.copy()
    working["naics_code"] = working[COL_NAICS].map(extract_naics_code)
    working["naics_code_original"] = working["naics_code"]
    if crosswalk:
        working["naics_code"] = working["naics_code"].map(
            lambda code: crosswalk.get(str(code), code)
        )
    working = working[working[COL_GEO] == geography]

    if COL_ADJUST in working.columns:
        working = working[working[COL_ADJUST] == adjustment]

    # The active table adds a Sales dimension splitting total from e-commerce.
    # Only the total is comparable with the archived table.
    if COL_SALES in working.columns:
        working = working[working[COL_SALES] == "Total retail sales"]

    working["month"] = pd.to_datetime(working[COL_DATE], format="%Y-%m", errors="coerce")
    working["sales_thousands_cad"] = pd.to_numeric(working[COL_VALUE], errors="coerce")

    tidy = (
        working.loc[:, ["month", "naics_code", "naics_code_original", COL_NAICS, "sales_thousands_cad"]]
        .rename(columns={COL_NAICS: "naics_name"})
        .dropna(subset=["month", "naics_code"])
    )
    tidy["source_table"] = table_label
    return tidy.sort_values(["naics_code", "month"]).reset_index(drop=True)


def chain_tables(historical: pd.DataFrame, current: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splice the archived table onto the active one using their overlap.

    Returns the chained series and a per series check table.
    """
    overlap_start = current["month"].min()
    overlap_end = historical["month"].max()

    checks: list[dict] = []
    chained_parts: list[pd.DataFrame] = []

    for code, current_series in current.groupby("naics_code"):
        historical_series = historical[historical["naics_code"] == code]
        if historical_series.empty:
            # A code present only in the active table simply starts in 2017.
            chained_parts.append(current_series)
            checks.append({
                "naics_code": code,
                "naics_code_historical": "",
                "overlap_months": 0,
                "scale_factor": np.nan,
                "median_absolute_percent_difference": np.nan,
                "note": "no history available for this code; series starts with the active table",
            })
            continue

        merged = historical_series.merge(
            current_series, on="month", suffixes=("_hist", "_curr")
        )
        merged = merged[
            merged["sales_thousands_cad_hist"].notna()
            & merged["sales_thousands_cad_curr"].notna()
            & (merged["sales_thousands_cad_hist"] != 0)
        ]

        if merged.empty:
            factor = 1.0
            disagreement = np.nan
            note = "no usable overlap; tables joined without rescaling, treat the join with caution"
        else:
            ratios = merged["sales_thousands_cad_curr"] / merged["sales_thousands_cad_hist"]
            factor = float(ratios.median())
            rescaled = merged["sales_thousands_cad_hist"] * factor
            disagreement = float(
                (
                    (rescaled - merged["sales_thousands_cad_curr"]).abs()
                    / merged["sales_thousands_cad_curr"]
                ).median()
                * 100
            )
            note = "chained on the measured overlap"

        history_only = historical_series[historical_series["month"] < overlap_start].copy()
        history_only["sales_thousands_cad"] = history_only["sales_thousands_cad"] * factor
        history_only["source_table"] = f"{history_only['source_table'].iloc[0]} rescaled" if len(history_only) else "historical rescaled"

        chained_parts.append(pd.concat([history_only, current_series], ignore_index=True))
        historical_codes = sorted(historical_series["naics_code_original"].dropna().unique().tolist())
        checks.append({
            "naics_code": code,
            "naics_code_historical": " | ".join(str(c) for c in historical_codes),
            "overlap_months": len(merged),
            "scale_factor": factor,
            "median_absolute_percent_difference": disagreement,
            "note": note if str(code) in historical_codes else f"{note}, via the NAICS 2017 to 2022 crosswalk",
        })

    chained = pd.concat(chained_parts, ignore_index=True).sort_values(["naics_code", "month"])
    check_frame = pd.DataFrame(checks).sort_values("naics_code").reset_index(drop=True)

    logger.info(
        "chained on overlap %s to %s",
        overlap_start.date() if pd.notna(overlap_start) else "n/a",
        overlap_end.date() if pd.notna(overlap_end) else "n/a",
    )
    return chained.reset_index(drop=True), check_frame


def tidy_cpi(frame: pd.DataFrame, geography: str, products: list[str]) -> pd.DataFrame:
    working = frame[frame[COL_GEO] == geography]
    if COL_PRODUCTS in working.columns:
        working = working[working[COL_PRODUCTS].isin(products)]

    working = working.copy()
    working["month"] = pd.to_datetime(working[COL_DATE], format="%Y-%m", errors="coerce")
    working["cpi"] = pd.to_numeric(working[COL_VALUE], errors="coerce")

    tidy = (
        working.loc[:, ["month", COL_PRODUCTS, "cpi"]]
        .rename(columns={COL_PRODUCTS: "product_group"})
        .dropna(subset=["month", "cpi"])
        .sort_values("month")
        .reset_index(drop=True)
    )
    return tidy


def main() -> None:
    tables = get("sources.statcan.tables")
    geography = get("sources.statcan.geography")
    adjustment = get("sources.statcan.adjustment")
    cpi_products = get("sources.statcan.cpi_products")

    with RunTimer(SCRIPT, logger) as run:
        current_raw = load_table(int(tables["retail_current"]["product_id"]))
        historical_raw = load_table(int(tables["retail_historical"]["product_id"]))
        cpi_raw = load_table(int(tables["cpi"]["product_id"]))

        rows_out = 0

        if current_raw is None:
            log_data_issue(
                SCRIPT, SOURCE, "the active retail table is missing",
                "no retail series could be built; the timing argument loses its measured base",
                severity="critical",
            )
        else:
            current = tidy_retail(current_raw, tables["retail_current"]["table_number"], geography, adjustment)
            logger.info("active table: %d rows, %s to %s", len(current), current["month"].min().date(), current["month"].max().date())

            if historical_raw is None:
                chained = current
                check_frame = pd.DataFrame(
                    [{"naics_code": "all", "overlap_months": 0, "scale_factor": np.nan,
                      "median_absolute_percent_difference": np.nan,
                      "note": "historical table unavailable; series begins in 2017"}]
                )
                log_data_issue(
                    SCRIPT, SOURCE, "the archived retail table could not be read",
                    "the retail series starts in 2017, which is under the fifteen years "
                    "the stage 2 gate asks for; say so in the methods note",
                    severity="error",
                )
            else:
                crosswalk = {
                    str(k): str(v)
                    for k, v in get("sources.statcan.naics_crosswalk_2017_to_2022").items()
                }
                historical = tidy_retail(
                    historical_raw, tables["retail_historical"]["table_number"], geography,
                    adjustment, crosswalk=crosswalk,
                )
                logger.info(
                    "archived table: %d rows, %s to %s",
                    len(historical), historical["month"].min().date(), historical["month"].max().date(),
                )
                chained, check_frame = chain_tables(historical, current)

                worst = check_frame["median_absolute_percent_difference"].max()
                if pd.notna(worst) and worst > 5:
                    log_data_issue(
                        SCRIPT, SOURCE,
                        f"the two retail tables disagree by up to {worst:.1f}% across their overlap",
                        "the chain is kept but the disagreement is reported in the methods note "
                        "and carried as uncertainty on any pre 2017 seasonal estimate",
                    )

            chained["month"] = chained["month"].dt.date
            target = save_cleaned(
                SOURCE, "retail_sales_monthly.csv", chained,
                geography=geography, adjustment=adjustment,
                naics_codes=sorted(chained["naics_code"].dropna().unique().tolist()),
            )
            rows_out += len(chained)
            logger.info("retail: %d rows -> %s", len(chained), relative(target))

            check_target = save_cleaned(
                SOURCE, "retail_chain_check.csv", check_frame,
                note="how well the archived and active retail tables agree, per NAICS code",
            )
            logger.info("chain check -> %s", relative(check_target))

            # The focus category is the one the whole retail argument runs on, so
            # check its history specifically rather than trusting the overall span.
            focus = get("sources.statcan.naics_focus")
            focus_series = chained[chained["naics_code"] == focus]
            if focus_series.empty:
                log_data_issue(
                    SCRIPT, SOURCE,
                    f"the focus category {focus} has no rows at all after chaining",
                    "the category level seasonality cannot be measured; fall back to total "
                    "retail trade and say so prominently",
                    severity="critical",
                )
            else:
                focus_start = focus_series["month"].min()
                focus_end = focus_series["month"].max()
                focus_years = focus_end.year - focus_start.year
                logger.info(
                    "focus category %s covers %s to %s (%d years)",
                    focus, focus_start, focus_end, focus_years,
                )
                if focus_years < 15:
                    log_data_issue(
                        SCRIPT, SOURCE,
                        f"the focus category {focus} covers only {focus_years} years",
                        "seasonal estimates for the category carry more uncertainty than "
                        "those for total retail trade; report both",
                        severity="error",
                    )

            years = (chained["month"].max().year - chained["month"].min().year) if len(chained) else 0
            if years < 15:
                log_data_issue(
                    SCRIPT, SOURCE,
                    f"the chained retail series covers only {years} years",
                    "stage 2 of section 16 asks for at least fifteen; record the shortfall",
                    severity="error",
                )
            else:
                logger.info("chained retail series covers %d years, stage 2 gate satisfied", years)

        if cpi_raw is None:
            log_data_issue(
                SCRIPT, SOURCE, "the CPI table is missing",
                "money cannot be inflation adjusted; report nominal figures only and say so",
                severity="error",
            )
        else:
            cpi = tidy_cpi(cpi_raw, geography, cpi_products)
            cpi["month"] = cpi["month"].dt.date
            target = save_cleaned(
                SOURCE, "cpi_monthly.csv", cpi,
                geography=geography, product_groups=cpi_products,
            )
            rows_out += len(cpi)
            logger.info("cpi: %d rows, %s to %s -> %s", len(cpi), cpi["month"].min(), cpi["month"].max(), relative(target))

        run.rows_out = rows_out

    logger.info("StatCan cleaning complete")


if __name__ == "__main__":
    main()
