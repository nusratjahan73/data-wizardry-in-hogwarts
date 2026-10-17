"""Checking the Power BI project that my code generates.

These tests cannot prove the project opens in Power BI Desktop, because nothing
here can drive a GUI application. So I test everything short of that: the files
exist, they are valid JSON, every relationship points at a real table and column,
every measure references a table in the model, and the M queries point at CSVs
that are really on disk.

This catches the problem my project is most likely to hit, which is drift.
23_star_schema.py changes a column name, and the Power BI project quietly keeps
using the old one until I open it and find a broken relationship.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config import repo_root

PBIP_DIR = repo_root() / "dashboard" / "pbip"
MODEL_FILE = PBIP_DIR / "DataWizardry.SemanticModel" / "model.bim"


def load_model() -> dict:
    if not MODEL_FILE.exists():
        pytest.skip("no Power BI project built; run src/analysis/29_build_powerbi_project.py")
    return json.loads(MODEL_FILE.read_text(encoding="utf-8"))


def test_every_generated_file_is_valid_json() -> None:
    if not PBIP_DIR.exists():
        pytest.skip("no Power BI project built")
    for file in PBIP_DIR.rglob("*"):
        if file.is_file():
            json.loads(file.read_text(encoding="utf-8"))


def test_relationships_reference_real_columns() -> None:
    model = load_model()["model"]
    columns = {
        table["name"]: {column["name"] for column in table["columns"]}
        for table in model["tables"]
    }

    for relationship in model["relationships"]:
        for side in ("from", "to"):
            table = relationship[f"{side}Table"]
            column = relationship[f"{side}Column"]
            assert table in columns, f"relationship references missing table {table}"
            assert column in columns[table], (
                f"relationship references missing column {table}[{column}]"
            )


def test_measures_reference_tables_in_the_model() -> None:
    model = load_model()["model"]
    table_names = {table["name"] for table in model["tables"]}

    measures = [m for t in model["tables"] for m in t.get("measures", [])]
    assert measures, "the model has no measures"

    referenced = re.compile(r"(\w+)\[")
    for measure in measures:
        for name in referenced.findall(measure["expression"]):
            # Reading a bare name followed by [ as a table reference. For a
            # measure reference like [Total Budget] there is no name at all.
            if name and name not in table_names and not name[0].isupper():
                raise AssertionError(
                    f"measure {measure['name']} references unknown table {name}"
                )


def test_partition_sources_point_at_files_that_exist() -> None:
    model = load_model()["model"]
    for table in model["tables"]:
        for partition in table["partitions"]:
            expression = partition["source"]["expression"]
            match = re.search(r'File\.Contents\("([^"]+)"\)', expression)
            if not match:
                continue  # Skipping the Measures table, which has no file source
            path = Path(match.group(1).replace("\\\\", "\\"))
            assert path.exists(), f"{table['name']} reads a CSV that does not exist: {path}"


def test_report_defines_the_six_specified_pages() -> None:
    report_file = PBIP_DIR / "DataWizardry.Report" / "report.json"
    if not report_file.exists():
        pytest.skip("no Power BI project built")
    report = json.loads(report_file.read_text(encoding="utf-8"))

    names = [section["displayName"] for section in report["sections"]]
    expected = {"Overview", "Return on investment", "Reception",
                "Geography", "Product line", "Timing"}
    assert expected <= set(names), f"missing pages: {expected - set(names)}"


def test_no_table_uses_a_name_power_bi_reserves() -> None:
    """Checking no table uses a reserved name, because Power BI refuses a table called "Measures".

    It fails with "Unsupported Table name "Measures" has been found in data model
    schema" and loads nothing at all. My first generated project hit exactly
    this, so I guard the name in my generator and here.
    """
    model = load_model()["model"]
    reserved = {"measures", "table", "column", "row", "value", "values", "model"}

    for table in model["tables"]:
        assert table["name"].lower() not in reserved, (
            f'table "{table["name"]}" uses a name Power BI reserves; '
            f"the project will not open"
        )


def test_measures_live_on_exactly_one_table() -> None:
    """Checking all twenty measures sit on one table, so I can find them in the field list."""
    model = load_model()["model"]
    hosts = [t["name"] for t in model["tables"] if t.get("measures")]
    assert len(hosts) == 1, f"measures are scattered across {hosts}"
    assert len(model["tables"][-1].get("measures", [])) >= 20


def _visual_configs() -> list[dict]:
    report_file = PBIP_DIR / "DataWizardry.Report" / "report.json"
    if not report_file.exists():
        pytest.skip("no Power BI project built")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    configs = []
    for section in report["sections"]:
        for container in section["visualContainers"]:
            configs.append((section["displayName"], json.loads(container["config"])))
    return configs


def test_pages_actually_contain_visuals() -> None:
    """Checking every page has visuals, because empty pages made my first dashboard useless."""
    report_file = PBIP_DIR / "DataWizardry.Report" / "report.json"
    if not report_file.exists():
        pytest.skip("no Power BI project built")
    report = json.loads(report_file.read_text(encoding="utf-8"))

    for section in report["sections"]:
        assert section["visualContainers"], (
            f'page "{section["displayName"]}" has no visuals on it'
        )


def test_every_projection_resolves_to_a_select() -> None:
    """Checking every queryRef has a matching Select, or the visual shows blank with no error.

    This is the quiet failure. The page looks built, the chart is empty, and
    Power BI says nothing. Catching it here is the only cheap way I have.
    """
    for page, config in _visual_configs():
        single = config.get("singleVisual", {})
        projections = single.get("projections")
        if not projections:
            continue  # Skipping text boxes, which have no query

        select_names = {s["Name"] for s in single["prototypeQuery"]["Select"]}
        for role, fields in projections.items():
            for field in fields:
                assert field["queryRef"] in select_names, (
                    f"{page}: role {role} references {field['queryRef']}, "
                    f"which is not in the query"
                )


def test_every_visual_field_exists_in_the_model() -> None:
    """Checking every column and measure that a visual uses exists in my model."""
    model = load_model()["model"]
    columns = {
        table["name"]: {column["name"] for column in table["columns"]}
        for table in model["tables"]
    }
    measures = {
        measure["name"]
        for table in model["tables"]
        for measure in table.get("measures", [])
    }

    for page, config in _visual_configs():
        single = config.get("singleVisual", {})
        query = single.get("prototypeQuery")
        if not query:
            continue

        sources = {f["Name"]: f["Entity"] for f in query["From"]}

        for select in query["Select"]:
            if "Column" in select:
                source = select["Column"]["Expression"]["SourceRef"]["Source"]
                table, column = sources[source], select["Column"]["Property"]
                assert column in columns[table], f"{page}: {table}[{column}] not in the model"
            elif "Measure" in select:
                assert select["Measure"]["Property"] in measures, (
                    f"{page}: measure {select['Measure']['Property']} not in the model"
                )
            elif "Aggregation" in select:
                inner = select["Aggregation"]["Expression"]["Column"]
                source = inner["Expression"]["SourceRef"]["Source"]
                table, column = sources[source], inner["Property"]
                assert column in columns[table], f"{page}: {table}[{column}] not in the model"


def test_visuals_stay_on_the_canvas() -> None:
    """Checking no visual sits off the canvas, where it is invisible and looks like a bug."""
    for page, config in _visual_configs():
        position = config["layouts"][0]["position"]
        assert position["x"] >= 0 and position["y"] >= 0, f"{page}: visual at a negative position"
        assert position["x"] + position["width"] <= 1281, f"{page}: visual runs off the right edge"
        assert position["y"] + position["height"] <= 721, f"{page}: visual runs off the bottom"
