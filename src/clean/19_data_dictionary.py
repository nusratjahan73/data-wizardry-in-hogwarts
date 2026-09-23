"""Generate docs/data_dictionary.md from the processed tables themselves.

Reads  : data/processed/*.csv and their .meta.json sidecars.
Writes : docs/data_dictionary.md
Runtime: a few seconds.

The dictionary is generated rather than written by hand, for one reason: a hand
written dictionary drifts from the data the first time a column is added, and
module 1's acceptance test requires that it cover every column with no blank
entries. Generating it means it cannot drift and cannot be partially filled.

Type, null count and range are measured from the data. Units, source and known
gaps cannot be measured, so they come from the curated map below. Any column
without an entry in that map is written into the dictionary with a loud TO
DOCUMENT marker and reported at the end of the run, so a missing description is
visible rather than absent.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import path
from src.utils.io import relative
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "19_data_dictionary"
logger = get_logger(SCRIPT)

TABLE_PURPOSE = {
    "films.csv": (
        "One row per theatrical film. Performance and reception from three sourced "
        "external tables, with PotterDB's own figures alongside for comparison. "
        "Eleven rows: descriptive use only, never a modelling sample."
    ),
    "characters.csv": (
        "One row per PotterDB character, widened with HP API attributes and with "
        "measured Wikipedia attention for the sixteen main characters."
    ),
    "attention_weekly.csv": (
        "Long form weekly attention. Two sources stacked, not joined, because "
        "pageviews and search interest are on different scales and measure "
        "different behaviour."
    ),
    "retail_monthly.csv": (
        "Canadian monthly retail sales by NAICS category, 1991 to 2026, chained "
        "across the archived and active StatCan tables and deflated by CPI."
    ),
    "products.csv": (
        "One row per branded construction set: year, piece count, minifigure "
        "count, theme and retail price where a price source was available."
    ),
}

# column name -> (units, source, known gaps or cautions)
COLUMNS: dict[str, tuple[str, str, str]] = {
    # --- shared ---
    "id": ("identifier", "PotterDB", "UUID assigned by PotterDB, stable across pulls"),
    "type": ("category", "PotterDB", "JSON:API record type, constant within a table"),
    "slug": ("identifier", "PotterDB", "URL safe name, ASCII and stable; preferred join key"),
    "name": ("text", "PotterDB", "canonical full name, often including middle names"),
    "name_key": ("text", "derived", "lower cased, punctuation stripped; join helper only"),
    "wiki": ("url", "PotterDB", "link to the fan wiki page"),

    # --- films ---
    "film_id": ("identifier", "hand entered", "1 to 11 in release order"),
    "title": ("text", "hand entered", "as released in the United Kingdom"),
    "series": ("category", "hand entered", "Harry Potter or Fantastic Beasts"),
    "release_date": ("date", "The Numbers", "first theatrical release anywhere"),
    "release_date_na": ("date", "Box Office Mojo", "North American release; the date the opening weekend belongs to"),
    "release_year": ("year", "derived", "from release_date"),
    "budget_usd": ("US dollars, nominal", "The Numbers", "production budget only, excludes marketing; the two Deathly Hallows budgets are a convention, not a measurement"),
    "domestic_gross_usd": ("US dollars, nominal", "The Numbers", "North America, includes re-releases"),
    "international_gross_usd": ("US dollars, nominal", "The Numbers", "all territories outside North America"),
    "worldwide_gross_usd": ("US dollars, nominal", "The Numbers", "domestic plus international"),
    "opening_weekend_domestic_usd": ("US dollars, nominal", "Box Office Mojo", "three day North American opening"),
    "rt_critic_score": ("percent", "Rotten Tomatoes", "Tomatometer, read 2 September 2026"),
    "rt_audience_score": ("percent", "Rotten Tomatoes", "Popcornmeter; gathered over decades, so not a release-time measure"),
    "metacritic_score": ("score 0 to 100", "Wikipedia", "critic aggregate"),
    "cinemascore": ("letter grade", "Wikipedia", "blank for three films where none was published"),
    "gross_profit_usd": ("US dollars, nominal", "derived", "worldwide gross minus budget; ignores marketing and the exhibitor's share, so it overstates profit"),
    "gross_profit_margin": ("ratio", "derived", "gross profit over worldwide gross"),
    "return_on_budget": ("ratio", "derived", "worldwide gross over budget"),
    "opening_share_of_domestic": ("ratio", "derived", "how front loaded the domestic run was"),
    "critic_audience_gap": ("percentage points", "derived", "critic score minus audience score"),
    "cpi_annual": ("index", "Statistics Canada 18-10-0004-01", "annual mean of monthly CPI"),
    "cpi_base_year": ("year", "derived", "the year money was adjusted to"),
    "usd_to_cad_rate_assumed": ("rate", "assumption", "a single stated rate, not a historic series"),
    "potterdb_budget_usd": ("US dollars, nominal", "PotterDB", "parsed from free text; known to contain ranges and errors"),
    "potterdb_box_office_usd": ("US dollars, nominal", "PotterDB", "parsed from free text; contains unit errors of 1000x on at least two films"),
    "potterdb_box_office_error_ratio": ("ratio", "derived", "PotterDB figure over the sourced figure; 1.0 means agreement"),

    # --- characters ---
    "house": ("category", "PotterDB", "populated on about 20 percent of characters"),
    "house_combined": ("category", "derived", "HP API house where known, otherwise PotterDB"),
    "house_source": ("category", "derived", "which source supplied house_combined"),
    "species": ("category", "PotterDB", "sparse on minor characters"),
    "gender": ("category", "PotterDB", "sparse on minor characters"),
    "blood_status": ("category", "PotterDB", "free text, not a controlled vocabulary"),
    "patronus": ("category", "PotterDB", "known for very few characters"),
    "alias_names": ("text, pipe separated", "PotterDB", "nicknames and disguises; rarely the common name, which is why the article map is explicit"),
    "animagus": ("text", "PotterDB", "the animal form, for the handful of characters who have one"),
    "boggart": ("text", "PotterDB", "known for a small number of characters"),
    "born": ("text", "PotterDB", "free text, often a range or a qualified date; not parseable to a date"),
    "died": ("text", "PotterDB", "free text, often includes the place and circumstances"),
    "eye_color": ("category", "PotterDB", "free text, not a controlled vocabulary"),
    "hair_color": ("category", "PotterDB", "free text, not a controlled vocabulary"),
    "skin_color": ("category", "PotterDB", "free text, sparse"),
    "height": ("text", "PotterDB", "free text with mixed units; not converted, and not used"),
    "weight": ("text", "PotterDB", "free text with mixed units; not converted, and not used"),
    "family_members": ("text, pipe separated", "PotterDB", "relationship labels, not links to other rows"),
    "jobs": ("text, pipe separated", "PotterDB", ""),
    "marital_status": ("category", "PotterDB", "sparse"),
    "nationality": ("category", "PotterDB", "free text, sparse"),
    "romances": ("text, pipe separated", "PotterDB", ""),
    "titles": ("text, pipe separated", "PotterDB", ""),
    "wands": ("text, pipe separated", "PotterDB", "wand descriptions as free text"),
    "retrieved_date": ("date", "hand entered", "when the figure was read from its source"),
    "total_weekly_views": ("page views", "Wikipedia", "sum over all complete weeks; only the sixteen mapped characters"),
    "mean_weekly_views": ("page views per week", "Wikipedia", "as above"),
    "peak_weekly_views": ("page views", "Wikipedia", "highest single week"),
    "weeks_observed": ("count", "Wikipedia", "complete weeks contributing"),
    "article": ("text", "Wikipedia", "exact article title"),

    # --- attention ---
    "week": ("date", "derived", "Monday that starts the week"),
    "group": ("category", "derived", "what the series measures; Trends groups carry their geography"),
    "source": ("category", "derived", "wikipedia_pageviews or google_trends"),
    "unit": ("category", "derived", "views, or index_0_100"),
    "value": ("views or index", "Wikipedia or Google Trends", "not comparable across sources; see unit"),

    # --- retail ---
    "month": ("date", "Statistics Canada", "first day of the month"),
    "naics_code": ("code", "Statistics Canada", "NAICS 2022; historical rows were crosswalked from NAICS 2017"),
    "naics_code_original": ("code", "Statistics Canada", "the code as published, before the crosswalk"),
    "naics_name": ("text", "Statistics Canada", "label as published in that vintage of the classification"),
    "sales_thousands_cad": ("thousands of Canadian dollars, nominal", "Statistics Canada", "unadjusted; pre 2017 values were rescaled onto the active table"),
    "sales_thousands_cad_real": ("thousands of Canadian dollars, constant", "derived", "deflated by all-items CPI to the latest available month"),
    "cpi": ("index", "Statistics Canada 18-10-0004-01", "all-items, Canada, not seasonally adjusted"),
    "cpi_base_month": ("date", "derived", "the month money was adjusted to"),
    "source_table": ("text", "derived", "which StatCan table the row came from, and whether it was rescaled"),
    "is_focus_category": ("boolean", "derived", "NAICS 459A, the closest published match to a book and lifestyle retailer"),
    "is_total_retail": ("boolean", "derived", "NAICS 44-45, the control for general seasonality"),
    "year": ("year", "derived", "calendar year"),
    "month_number": ("1 to 12", "derived", "calendar month"),

    # --- products ---
    "set_num": ("identifier", "Rebrickable", "set number with variant suffix"),
    "set_name": ("text", "Rebrickable", ""),
    "theme_id": ("identifier", "Rebrickable", ""),
    "theme_name": ("text", "Rebrickable", "includes the two collectible minifigure series"),
    "num_parts": ("count", "Rebrickable", "zero for promotional items, which are flagged"),
    "minifig_count": ("count", "derived", "summed from the version 1 inventory only"),
    "img_url": ("url", "Rebrickable", "not downloaded; images belong under images/"),
    "is_promotional": ("boolean", "derived", "true where the set has no pieces"),
    "retail_price_cad": ("Canadian dollars, nominal", "Brickset", "empty unless BRICKSET_API_KEY was set at collection time"),
    "retail_price_usd": ("US dollars, nominal", "Brickset", "as above"),
    "retail_price_gbp": ("pounds sterling, nominal", "Brickset", "as above"),
    "retail_price_cad_real": ("Canadian dollars, constant", "derived", "deflated by annual CPI"),
    "price_per_piece_cad": ("Canadian dollars per piece", "derived", "price over piece count, buildable sets only"),
    "price_per_piece_cad_real": ("Canadian dollars per piece, constant", "derived", "as above, inflation adjusted"),
    "brickset_name": ("text", "Brickset", ""),
    "brickset_year": ("year", "Brickset", "cross check against the Rebrickable year"),
    "brickset_pieces": ("count", "Brickset", "cross check against num_parts"),
    "brickset_minifigs": ("count", "Brickset", "cross check against the derived minifig_count"),
}

# Prefixes handled in bulk, so adding one HP API field does not need a new line.
PREFIX_RULES = [
    ("hpapi_", ("varies", "HP API", "curated set of 437 characters; blank for the other five thousand")),
    ("source_", ("text", "hand entered", "origin of the figure in the matching column")),
]

# Suffixes handled in bulk, for the families of derived columns.
SUFFIX_RULES = [
    (
        "_cad_real",
        (
            "Canadian dollars, constant",
            "derived",
            "US dollars converted at one stated rate then deflated by Canadian CPI; "
            "measures worth to a Canadian buyer today, not the US real figure",
        ),
    ),
    (
        "_count",
        ("count", "derived", "length of the matching pipe separated list column"),
    ),
]


def describe_column(column: str) -> tuple[str, str, str] | None:
    if column in COLUMNS:
        return COLUMNS[column]
    for prefix, description in PREFIX_RULES:
        if column.startswith(prefix):
            return description
    for suffix, description in SUFFIX_RULES:
        if column.endswith(suffix):
            return description
    return None


def summarise(series: pd.Series) -> tuple[str, str]:
    """Return the measured type and a range or example, from the data itself."""
    non_null = series.dropna()
    if non_null.empty:
        return str(series.dtype), "all values missing"

    if pd.api.types.is_numeric_dtype(series):
        return str(series.dtype), f"{non_null.min():,.4g} to {non_null.max():,.4g}"

    parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
    if parsed.notna().mean() > 0.9:
        return "date", f"{parsed.min().date()} to {parsed.max().date()}"

    unique = non_null.nunique()
    if unique <= 8:
        return "category", ", ".join(str(v) for v in sorted(non_null.unique())[:8])
    example = str(non_null.iloc[0])
    return "text", f"{unique:,} distinct, e.g. {example[:40]}"


def document_table(name: str, undocumented: list[str]) -> str:
    target = path("data_processed", name)
    frame = pd.read_csv(target, low_memory=False)

    sidecar = target.with_suffix(target.suffix + ".meta.json")
    built_at = "unknown"
    if sidecar.exists():
        built_at = json.loads(sidecar.read_text(encoding="utf-8")).get("collected_at_utc", "unknown")

    lines = [
        f"## `{name}`",
        "",
        TABLE_PURPOSE.get(name, ""),
        "",
        f"- **Rows:** {len(frame):,}",
        f"- **Columns:** {len(frame.columns)}",
        f"- **Built:** {built_at}",
        "",
        "| Column | Type | Units | Source | Missing | Range or values | Known gaps |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for column in frame.columns:
        measured_type, range_text = summarise(frame[column])
        missing = frame[column].isna().sum()
        missing_text = f"{missing:,} ({missing / len(frame):.0%})" if missing else "none"

        described = describe_column(column)
        if described is None:
            undocumented.append(f"{name}:{column}")
            units, source, gaps = ("TO DOCUMENT", "TO DOCUMENT", "TO DOCUMENT")
        else:
            units, source, gaps = described

        def clean(text: str) -> str:
            return str(text).replace("|", "/").replace("\n", " ")

        lines.append(
            f"| `{column}` | {measured_type} | {clean(units)} | {clean(source)} | "
            f"{missing_text} | {clean(range_text)} | {clean(gaps) or '-'} |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        tables = [name for name in TABLE_PURPOSE if path("data_processed", name).exists()]
        if not tables:
            logger.error("no processed tables found; run 18_build_processed.py first")
            run.rows_out = 0
            return

        undocumented: list[str] = []
        sections = [document_table(name, undocumented) for name in tables]

        header = [
            "# Data dictionary",
            "",
            "Every column in every processed table, with its measured type, its units, "
            "where it came from and what is known to be missing from it.",
            "",
            "This file is generated by `src/clean/19_data_dictionary.py` and must not be "
            "edited by hand. Type, missing count and range are measured from the data; "
            "units, source and known gaps come from the curated map inside that script. "
            "Regenerate it after any change to the processed tables.",
            "",
            f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} "
            f"covering {len(tables)} tables.",
            "",
            "Analysis scripts read only from `data/processed`. Nothing here is raw, and "
            "nothing here belongs to a single source: every table is a join.",
            "",
        ]

        output = path("docs", "data_dictionary.md", create=True)
        output.write_text("\n".join(header) + "\n".join(sections), encoding="utf-8")

        total_columns = sum(
            len(pd.read_csv(path("data_processed", name), nrows=0).columns) for name in tables
        )
        logger.info("documented %d columns across %d tables -> %s", total_columns, len(tables), relative(output))

        if undocumented:
            logger.error("%d columns have no curated description: %s", len(undocumented), ", ".join(undocumented))
            log_data_issue(
                SCRIPT, "data_dictionary",
                f"{len(undocumented)} columns are marked TO DOCUMENT: {', '.join(undocumented)}",
                "add them to the COLUMNS map in 19_data_dictionary.py; module 1's "
                "acceptance test requires no blank entries",
                severity="error",
            )
        else:
            logger.info("every column has a curated description")

        run.rows_out = total_columns
        run.note = f"{len(undocumented)} undocumented columns"


if __name__ == "__main__":
    main()
