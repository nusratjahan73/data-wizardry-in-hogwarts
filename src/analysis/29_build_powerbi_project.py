"""Building a Power BI project (.pbip) that Power BI Desktop can open directly.

Reading: dashboard/model/*.csv (written by 23_star_schema.py)
Writing: dashboard/pbip/DataWizardry.pbip
         dashboard/pbip/DataWizardry.SemanticModel/  (model, relationships, measures)
         dashboard/pbip/DataWizardry.Report/         (six named pages)
Runtime: instant.

A `.pbix` file is a closed binary format that only Power BI Desktop can make,
so no script can write one. Microsoft's `.pbip` project format, supported since
May 2023, is plain text: JSON and TMSL. Power BI Desktop opens a `.pbip` folder
and can then save it as `.pbix` from the File menu.

This fills most of what I was missing in module 2. I build the parts that are
slow and easy to get wrong by hand: ten tables with typed columns, eight
relationships with the right cardinality and filter direction, and twenty DAX
measures. I also lay out the six pages with cards, line and column charts,
scatter plots, tables, a map and the era slicer. Each page has its finding in a
text box across the top.

I cannot drive a desktop app from a script, so I only check that the JSON is
well formed, that relationships point at real columns, and that the M queries
point at files that exist. My first version failed to open because I named the
measures table "Measures", which Power BI reserves, so I fixed that and added a
guard. Any other failure has to be found the same way, by opening the project.

The M queries use absolute paths to the CSVs, written when this script runs. If
I move the project folder, I have to run this script again.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import repo_root
from src.utils.io import relative
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue
from src.utils.pbi_visuals import visuals_for

SCRIPT = "29_build_powerbi_project"
logger = get_logger(SCRIPT)

MODEL_DIR = repo_root() / "dashboard" / "model"
PBIP_DIR = repo_root() / "dashboard" / "pbip"
PROJECT = "DataWizardry"

# Naming the table that holds the measures. It must NOT be "Measures": Power BI
# rejects that name with "Unsupported Table name "Measures" has been found in data
# model schema" and will not open the file. I found this by opening my first
# generated project in Power BI Desktop, which is the one check this script cannot
# run for itself.
MEASURES_TABLE = "Key Measures"

# Listing the names Power BI reserves and will not accept as a table name. I guard
# this in code and in tests/test_powerbi_project.py, so it cannot quietly break again.
RESERVED_TABLE_NAMES = {"measures", "table", "column", "row", "value", "values", "model"}

# Mapping column types from pandas to the tabular model.
TYPE_MAP = {
    "int64": ("int64", "Int64.Type"),
    "Int64": ("int64", "Int64.Type"),
    "float64": ("double", "type number"),
    "bool": ("boolean", "type logical"),
    "object": ("string", "type text"),
}

DATE_COLUMNS = {"month_start", "release_date", "release_date_na", "month", "week"}

# Listing the eight relationships from model_notes.md. from = many side, to = one side.
RELATIONSHIPS = [
    ("fact_film_performance", "date_key", "dim_date", "date_key"),
    ("fact_attention_monthly", "date_key", "dim_date", "date_key"),
    ("fact_retail_monthly", "date_key", "dim_date", "date_key"),
    ("fact_product_release", "date_key", "dim_date", "date_key"),
    ("fact_park_attendance", "date_key", "dim_date", "date_key"),
    ("fact_film_performance", "film_key", "dim_film", "film_key"),
    ("fact_product_release", "theme_key", "dim_product_theme", "theme_key"),
    ("fact_attention_monthly", "series", "dim_character", "article"),
]

# Listing the measures from model_notes.md. I keep them in step with that document.
MEASURES = [
    ("Total Budget", "SUM ( fact_film_performance[budget_usd] )", "\\$#,0"),
    ("Total Worldwide Gross", "SUM ( fact_film_performance[worldwide_gross_usd] )", "\\$#,0"),
    ("Profit", "[Total Worldwide Gross] - [Total Budget]", "\\$#,0"),
    ("Profit Margin", "DIVIDE ( [Profit], [Total Worldwide Gross] )", "0.0%"),
    ("Return on Budget", "DIVIDE ( [Total Worldwide Gross], [Total Budget] )", "0.00"),
    (
        "Cumulative Franchise Revenue",
        "CALCULATE ( [Total Worldwide Gross], FILTER ( ALLSELECTED ( dim_date[date_key] ), "
        "dim_date[date_key] <= MAX ( dim_date[date_key] ) ) )",
        "\\$#,0",
    ),
    ("Mean Weekly Attention", "AVERAGE ( fact_attention_monthly[mean_weekly_value] )", "#,0"),
    (
        "Attention YoY Change",
        "VAR CurrentValue = [Mean Weekly Attention] "
        "VAR PriorValue = CALCULATE ( [Mean Weekly Attention], "
        "DATEADD ( dim_date[month_start], -12, MONTH ) ) "
        "RETURN DIVIDE ( CurrentValue - PriorValue, PriorValue )",
        "0.0%",
    ),
    (
        "Franchise Attention",
        "CALCULATE ( [Mean Weekly Attention], "
        "fact_attention_monthly[source] = \"wikipedia_pageviews\", "
        "fact_attention_monthly[group] = \"franchise\" )",
        "#,0",
    ),
    (
        "Category Sales Real",
        "CALCULATE ( SUM ( fact_retail_monthly[sales_thousands_cad_real] ), "
        "fact_retail_monthly[is_focus_category] = TRUE () )",
        "#,0",
    ),
    (
        "Total Retail Sales Real",
        "CALCULATE ( SUM ( fact_retail_monthly[sales_thousands_cad_real] ), "
        "fact_retail_monthly[is_total_retail] = TRUE () )",
        "#,0",
    ),
    (
        "Seasonality Index",
        "VAR MonthlyValue = [Category Sales Real] "
        "VAR AnnualAverage = CALCULATE ( AVERAGEX ( VALUES ( dim_date[date_key] ), "
        "[Category Sales Real] ), ALLEXCEPT ( dim_date, dim_date[year] ) ) "
        "RETURN DIVIDE ( MonthlyValue, AnnualAverage ) * 100",
        "0.0",
    ),
    (
        "Category Share of Total Retail",
        "DIVIDE ( [Category Sales Real], [Total Retail Sales Real] )",
        "0.0%",
    ),
    ("Total Pieces", "SUM ( fact_product_release[num_parts] )", "#,0"),
    ("Average Price Per Piece", "AVERAGE ( fact_product_release[price_per_piece_cad] )", "\\$#,0.00"),
    ("Total Attendance", "SUM ( fact_park_attendance[attendance] )", "#,0"),
    (
        "Attendance Index vs Pre-Opening",
        "AVERAGE ( fact_park_attendance[attendance_index_vs_year_before_opening] )",
        "0.0",
    ),
    ("Set Count", "COUNTROWS ( fact_product_release )", "#,0"),
    ("Film Count", "COUNTROWS ( fact_film_performance )", "#,0"),
    (
        "Critic Audience Gap",
        "AVERAGE ( fact_film_performance[critic_audience_gap] )",
        "0.0",
    ),
]

PAGES = [
    ("Overview", "Franchise attention has fallen 57% since 2023, while the new series' article rose a hundredfold"),
    ("Return on investment", "Deathly Hallows Part 2 returned 10.5x its assigned budget; Secrets of Dumbledore returned 2.0"),
    ("Reception", "Audiences rated Secrets of Dumbledore 37 points above critics"),
    ("Geography", "Canada ranks 9th of 61 countries at 97, within two points of the leaders"),
    ("Product line", "Blocked: no retail price source, so price per piece is empty"),
    ("Timing", "The category peaks at 172 in December and collapses to 86 in January; attention barely moves"),
]


def m_query(csv_path: Path, columns: list[tuple[str, str]]) -> str:
    """Writing a Power Query M expression that reads one CSV with explicit types."""
    transforms = ", ".join(f'{{"{name}", {m_type}}}' for name, m_type in columns)
    windows_path = str(csv_path).replace("\\", "\\\\")
    return (
        "let\n"
        f'    Source = Csv.Document(File.Contents("{windows_path}"),'
        "[Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
        f"    Typed = Table.TransformColumnTypes(Promoted,{{{transforms}}})\n"
        "in\n"
        "    Typed"
    )


def build_table(name: str, csv_path: Path) -> dict:
    frame = pd.read_csv(csv_path, nrows=500)

    columns = []
    m_columns = []
    for column in frame.columns:
        dtype = str(frame[column].dtype)
        data_type, m_type = TYPE_MAP.get(dtype, ("string", "type text"))

        if column in DATE_COLUMNS:
            data_type, m_type = "dateTime", "type date"

        columns.append({
            "name": column,
            "dataType": data_type,
            "sourceColumn": column,
            "summarizeBy": "none",
        })
        m_columns.append((column, m_type))

    return {
        "name": name,
        "columns": columns,
        "partitions": [{
            "name": f"{name}-partition",
            "mode": "import",
            "source": {"type": "m", "expression": m_query(csv_path, m_columns)},
        }],
    }


def build_model() -> dict:
    tables = []
    available = {}

    for csv_path in sorted(MODEL_DIR.glob("*.csv")):
        name = csv_path.stem
        if name == "relationships":
            continue  # Skipping this file, because it is documentation and not a model table
        tables.append(build_table(name, csv_path))
        available[name] = {c["name"] for c in tables[-1]["columns"]}
        logger.info("table %-24s %2d columns", name, len(tables[-1]["columns"]))

    # Putting the measures on their own table. This is the usual way to keep them
    # easy to find, and not scattered across whichever fact table they were made on.
    tables.append({
        "name": MEASURES_TABLE,
        "columns": [{
            "name": "placeholder", "dataType": "string", "isHidden": True,
            "sourceColumn": "placeholder", "summarizeBy": "none",
        }],
        "partitions": [{
            "name": f"{MEASURES_TABLE}-partition",
            "mode": "import",
            "source": {
                "type": "m",
                "expression": 'let Source = #table({"placeholder"}, {{""}}) in Source',
            },
        }],
        "measures": [
            {"name": measure, "expression": expression, "formatString": fmt}
            for measure, expression, fmt in MEASURES
        ],
    })

    relationships = []
    for from_table, from_column, to_table, to_column in RELATIONSHIPS:
        if from_table not in available or to_table not in available:
            log_data_issue(
                SCRIPT, "powerbi",
                f"relationship {from_table} -> {to_table} skipped, a table is missing",
                "rerun 23_star_schema.py to regenerate the model tables",
            )
            continue
        if from_column not in available[from_table] or to_column not in available[to_table]:
            log_data_issue(
                SCRIPT, "powerbi",
                f"relationship {from_table}[{from_column}] -> {to_table}[{to_column}] "
                f"skipped, a column is missing",
                "check that 23_star_schema.py still emits that column",
            )
            continue
        relationships.append({
            "name": str(uuid.uuid4()),
            "fromTable": from_table,
            "fromColumn": from_column,
            "toTable": to_table,
            "toColumn": to_column,
            "crossFilteringBehavior": "oneDirection",
        })

    illegal = [t["name"] for t in tables if t["name"].lower() in RESERVED_TABLE_NAMES]
    if illegal:
        raise ValueError(
            f"these table names are reserved by Power BI and would stop the project "
            f"opening: {illegal}. Rename them in 23_star_schema.py or in MEASURES_TABLE."
        )

    logger.info("%d tables, %d relationships, %d measures",
                len(tables), len(relationships), len(MEASURES))

    return {
        "name": PROJECT,
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-CA",
            "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-CA",
            "tables": tables,
            "relationships": relationships,
            "annotations": [{"name": "PBI_QueryOrder", "value": json.dumps(
                [t["name"] for t in tables])}],
        },
    }


def platform_file(display_name: str, kind: str) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                   "platformProperties/2.0.0/schema.json",
        "metadata": {"type": kind, "displayName": display_name},
        "config": {"version": "2.0", "logicalId": str(uuid.uuid4())},
    }


def build_report() -> dict:
    """Building the six pages with their visuals, laid out on a 1280 x 720 canvas.

    The visuals come from src/utils/pbi_visuals.py. A visual whose projections
    and prototypeQuery disagree draws blank with no error. So a chart that looks
    empty in Power BI means a queryRef mismatch, not missing data.
    """
    sections = []
    for index, (name, finding) in enumerate(PAGES):
        containers = visuals_for(name)
        logger.info("page %-22s %2d visuals", name, len(containers))
        sections.append({
            "name": f"page{index}",
            "displayName": name,
            "filters": "[]",
            "ordinal": index,
            "visualContainers": containers,
            "config": json.dumps({
                "visibility": 0,
                "displayName": name,
                "description": finding,
            }),
            "displayOption": 1,
            "height": 720.0,
            "width": 1280.0,
        })

    return {
        "id": 0,
        "resourcePackages": [],
        "sections": sections,
        "config": json.dumps({
            "version": "5.43",
            "themeCollection": {"baseTheme": {"name": "CY24SU06"}},
            "activeSectionIndex": 0,
            "settings": {"useStylableVisualContainerHeader": True},
        }),
        "layoutOptimization": 0,
    }


def write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        if not MODEL_DIR.exists() or not any(MODEL_DIR.glob("*.csv")):
            logger.error("no model tables found; run src/analysis/23_star_schema.py first")
            run.rows_out = 0
            return

        semantic_dir = PBIP_DIR / f"{PROJECT}.SemanticModel"
        report_dir = PBIP_DIR / f"{PROJECT}.Report"

        # Writing the project pointer file.
        write_json(PBIP_DIR / f"{PROJECT}.pbip", {
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{PROJECT}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        })

        # Writing the semantic model.
        model = build_model()
        write_json(semantic_dir / "model.bim", model)
        write_json(semantic_dir / "definition.pbism", {"version": "4.0", "settings": {}})
        write_json(semantic_dir / ".platform", platform_file(PROJECT, "SemanticModel"))
        write_json(semantic_dir / "diagramLayout.json", {"version": "1.1.0", "diagrams": []})

        # Writing the report.
        write_json(report_dir / "report.json", build_report())
        write_json(report_dir / "definition.pbir", {
            "version": "1.0",
            "datasetReference": {"byPath": {"path": f"../{PROJECT}.SemanticModel"}},
        })
        write_json(report_dir / ".platform", platform_file(PROJECT, "Report"))

        # Checking what I can check from here.
        problems = []
        for file in PBIP_DIR.rglob("*"):
            if file.is_file() and file.suffix in {".json", ".bim", ".pbip", ".pbism", ".pbir", ".platform"}:
                try:
                    json.loads(file.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    problems.append(f"{relative(file)}: {exc}")
            elif file.is_file() and file.name == ".platform":
                json.loads(file.read_text(encoding="utf-8"))

        if problems:
            for problem in problems:
                logger.error("invalid JSON: %s", problem)
            log_data_issue(
                SCRIPT, "powerbi", f"{len(problems)} generated files are not valid JSON",
                "the project will not open; fix the generator", severity="error",
            )
        else:
            logger.info("all generated files parse as valid JSON")

        log_data_issue(
            SCRIPT, "powerbi",
            "the generated .pbip has not been opened in Power BI Desktop",
            "nothing here can drive a GUI application, so it is validated for JSON "
            "well formedness and internal consistency only. If it fails to open, the star "
            "schema CSVs and the DAX in dashboard/model_notes.md remain the fallback.",
            severity="note",
        )

        run.rows_out = len(model["model"]["tables"])
        run.note = f"{len(model['model']['tables'])} tables, {len(MEASURES)} measures, untested"
        logger.info("Power BI project written to %s", relative(PBIP_DIR))
        logger.info("open %s in Power BI Desktop, then File > Save As to produce a .pbix",
                    relative(PBIP_DIR / f"{PROJECT}.pbip"))

    logger.info("Power BI project build complete")


if __name__ == "__main__":
    main()
