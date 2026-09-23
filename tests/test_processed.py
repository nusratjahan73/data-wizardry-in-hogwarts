"""Acceptance tests for the processed tables. Module 1's definition of done.

Run with:  python -m pytest tests/ -v

Section 7 of the brief names four checks: no processed table is empty, no date is
after the run date, no monetary column is negative, and primary keys are unique.
Those are all here, plus a few that the specific tables in this project need.

The tests read only from data/processed. If they fail, the fix belongs in the
cleaning scripts, never in a test.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config import path

# table name -> primary key columns
TABLES = {
    "films.csv": ["film_id"],
    "characters.csv": ["id"],
    "attention_weekly.csv": ["source", "group", "series", "week"],
    "retail_monthly.csv": ["naics_code", "month"],
    "products.csv": ["set_num"],
}

# Columns that hold money and must never be negative. A negative here means a
# parse went wrong, not that a film lost money: profit columns are excluded on
# purpose, because a film genuinely can fail to earn back its budget.
MONEY_COLUMNS = [
    "budget_usd", "domestic_gross_usd", "international_gross_usd",
    "worldwide_gross_usd", "opening_weekend_domestic_usd",
    "budget_cad_real", "domestic_gross_cad_real", "worldwide_gross_cad_real",
    "sales_thousands_cad", "sales_thousands_cad_real",
    "retail_price_cad", "retail_price_usd", "retail_price_gbp",
    "price_per_piece_cad", "price_per_piece_cad_real",
]

DATE_COLUMNS = [
    "release_date", "release_date_na", "week", "month", "created_date",
]


def load(name: str) -> pd.DataFrame:
    target = path("data_processed", name)
    if not target.exists():
        pytest.skip(f"{name} has not been built yet; run src/clean/19_build_processed.py")
    return pd.read_csv(target, low_memory=False)


@pytest.mark.parametrize("name", list(TABLES))
def test_table_is_not_empty(name: str) -> None:
    frame = load(name)
    assert len(frame) > 0, f"{name} is empty"
    assert len(frame.columns) > 1, f"{name} has only one column"


@pytest.mark.parametrize("name,key", list(TABLES.items()))
def test_primary_key_is_unique(name: str, key: list[str]) -> None:
    frame = load(name)
    missing = [column for column in key if column not in frame.columns]
    assert not missing, f"{name} is missing key column(s) {missing}"

    duplicates = frame.duplicated(subset=key).sum()
    assert duplicates == 0, f"{name} has {duplicates} duplicate rows on {key}"


@pytest.mark.parametrize("name", list(TABLES))
def test_no_date_is_after_today(name: str) -> None:
    """A date beyond the run date means a parse error or a fabricated row.

    The premiere date is in the future by design, but it lives in config, not in
    a processed table, so nothing here should carry a future date.
    """
    frame = load(name)
    today = date.today()

    for column in DATE_COLUMNS:
        if column not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce")
        future = parsed[parsed.dt.date > today]
        assert future.empty, (
            f"{name}.{column} has {len(future)} dates after {today}, "
            f"latest is {future.max()}"
        )


@pytest.mark.parametrize("name", list(TABLES))
def test_no_money_column_is_negative(name: str) -> None:
    frame = load(name)
    for column in MONEY_COLUMNS:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        negative = values[values < 0]
        assert negative.empty, (
            f"{name}.{column} has {len(negative)} negative values, "
            f"smallest is {negative.min()}"
        )


def test_attention_series_reaches_weekly_granularity() -> None:
    """Stage 1's gate: an attention series at weekly or better granularity."""
    attention = load("attention_weekly.csv")
    weeks = pd.to_datetime(attention["week"], errors="coerce")
    gaps = weeks.sort_values().diff().dt.days.dropna()
    assert not gaps.empty, "attention_weekly has no usable dates"
    assert gaps.median() <= 7, (
        f"the attention series is coarser than weekly: median gap {gaps.median()} days"
    )


def test_retail_series_covers_fifteen_years() -> None:
    """Stage 2's gate: a monthly series covering at least fifteen years."""
    retail = load("retail_monthly.csv")
    months = pd.to_datetime(retail["month"], errors="coerce").dropna()
    span_years = (months.max() - months.min()).days / 365.25
    assert span_years >= 15, f"the retail series covers only {span_years:.1f} years"


def test_focus_category_has_history() -> None:
    """The category the retail argument runs on must reach back before 2017.

    This is the check that catches the NAICS renumbering problem. Without the
    crosswalk in the cleaning step, this category silently begins in 2017 while
    every other test still passes.
    """
    retail = load("retail_monthly.csv")
    assert "is_focus_category" in retail.columns, "retail_monthly has no is_focus_category flag"

    focus = retail[retail["is_focus_category"]]
    assert not focus.empty, "no rows are flagged as the focus category"

    months = pd.to_datetime(focus["month"], errors="coerce").dropna()
    span_years = (months.max() - months.min()).days / 365.25
    assert span_years >= 15, (
        f"the focus category covers only {span_years:.1f} years. Check the NAICS "
        f"2017 to 2022 crosswalk in config.yaml."
    )


def test_film_table_is_internally_consistent() -> None:
    films = load("films.csv")

    assert (films["worldwide_gross_usd"] >= films["domestic_gross_usd"]).all(), (
        "a film has a worldwide gross below its domestic gross"
    )
    assert (films["opening_weekend_domestic_usd"] <= films["domestic_gross_usd"]).all(), (
        "a film has an opening weekend above its total domestic gross"
    )
    for column in ["rt_critic_score", "rt_audience_score"]:
        values = pd.to_numeric(films[column], errors="coerce")
        assert values.between(0, 100).all(), f"{column} has a value outside 0 to 100"


def test_every_processed_table_has_metadata() -> None:
    """Section 4: every saved file carries its collection date in a sidecar."""
    for name in TABLES:
        target = path("data_processed", name)
        if not target.exists():
            continue
        sidecar = target.with_suffix(target.suffix + ".meta.json")
        assert sidecar.exists(), f"{name} has no .meta.json sidecar recording when it was built"


def test_no_personal_identifier_reaches_processed_tables() -> None:
    """Module 8: no username or email may appear in a processed table."""
    forbidden = {"author", "author_name", "username", "email", "user", "screen_name"}
    for name in TABLES:
        target = path("data_processed", name)
        if not target.exists():
            continue
        columns = set(pd.read_csv(target, nrows=0).columns)
        leaked = forbidden & columns
        assert not leaked, f"{name} contains identifying column(s) {sorted(leaked)}"
