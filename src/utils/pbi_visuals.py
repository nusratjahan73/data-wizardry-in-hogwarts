"""Builders for Power BI report visuals.

Separated from the project generator because they answer a different question:
the generator decides what the model contains, this decides what the pages look
like. Keeping them apart means a layout change cannot alter the semantic model.

A Power BI visual is a "visualContainer" whose `config` is a JSON *string*
holding two things that must agree with each other:

  projections     which field fills which visual role (Category, Y, Values, ...)
  prototypeQuery  the semantic query behind the visual

The link between them is the `Name` of each Select entry, which `projections`
refers to as `queryRef`. If those fall out of step the visual renders blank with
no error at all, which is the failure mode to watch for when a page looks empty.
"""

from __future__ import annotations

import json
import uuid

# Must match MEASURES_TABLE in the generator. Not "Measures": Power BI reserves
# that name and refuses to open the file.
MEASURES_TABLE = "Key Measures"

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720


def _alias(entity: str) -> str:
    """A short, stable query alias for a table."""
    initials = "".join(word[0] for word in entity.replace("_", " ").split())
    return (initials[:3] or "t").lower()


def column_select(entity: str, column: str) -> dict:
    return {
        "Column": {"Expression": {"SourceRef": {"Source": _alias(entity)}}, "Property": column},
        "Name": f"{entity}.{column}",
        "NativeReferenceName": column,
    }


def measure_select(measure: str) -> dict:
    return {
        "Measure": {
            "Expression": {"SourceRef": {"Source": _alias(MEASURES_TABLE)}},
            "Property": measure,
        },
        "Name": f"{MEASURES_TABLE}.{measure}",
        "NativeReferenceName": measure,
    }


def aggregate_select(entity: str, column: str, function: int = 0, label: str | None = None) -> dict:
    """An aggregation over a column. 0 Sum, 1 Average, 2 Count, 3 Min, 4 Max."""
    names = {0: "Sum", 1: "Avg", 2: "Count", 3: "Min", 4: "Max"}
    return {
        "Aggregation": {
            "Expression": {
                "Column": {
                    "Expression": {"SourceRef": {"Source": _alias(entity)}},
                    "Property": column,
                }
            },
            "Function": function,
        },
        "Name": f"{names[function]}({entity}.{column})",
        "NativeReferenceName": label or column,
    }


def _entity_of(select_name: str) -> str:
    """Recover the table a Select entry belongs to, for the From clause."""
    if select_name.startswith(f"{MEASURES_TABLE}."):
        return MEASURES_TABLE
    if "(" in select_name:
        return select_name.split("(", 1)[1].split(".", 1)[0]
    return select_name.split(".", 1)[0]


def visual(
    visual_type: str,
    position: tuple[float, float, float, float],
    roles: dict[str, list[dict]],
    title: str,
    z: int = 0,
) -> dict:
    """One visual container.

    Entities for the From clause are collected from the fields actually used, so
    the query never lists a table it does not read, which Power BI rejects.
    """
    x, y, width, height = position

    selects: list[dict] = []
    projections: dict[str, list[dict]] = {}
    entities: list[str] = []

    for role, items in roles.items():
        projections[role] = []
        for item in items:
            selects.append(item)
            projections[role].append({"queryRef": item["Name"]})
            entity = _entity_of(item["Name"])
            if entity not in entities:
                entities.append(entity)

    config = {
        "name": str(uuid.uuid4()),
        "layouts": [{
            "id": 0,
            "position": {
                "x": x, "y": y, "z": z,
                "width": width, "height": height, "tabOrder": z,
            },
        }],
        "singleVisual": {
            "visualType": visual_type,
            "projections": projections,
            "prototypeQuery": {
                "Version": 2,
                "From": [{"Name": _alias(e), "Entity": e, "Type": 0} for e in entities],
                "Select": selects,
            },
            "columnProperties": {},
            "drillFilterOtherVisuals": True,
            "objects": {},
            "vcObjects": {
                "title": [{
                    "properties": {
                        "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
                        "show": {"expr": {"Literal": {"Value": "true"}}},
                        "fontSize": {"expr": {"Literal": {"Value": "11D"}}},
                    }
                }]
            },
        },
    }

    return {
        "x": x, "y": y, "z": z, "width": width, "height": height,
        "config": json.dumps(config),
        "filters": "[]",
    }


def textbox(position: tuple[float, float, float, float], text: str, z: int = 0) -> dict:
    """A text box, used to put each page's finding on the page itself.

    Section 8 asks every page to carry a one line title written as a finding
    rather than a label, and a text box is how that gets onto the canvas.
    """
    x, y, width, height = position
    config = {
        "name": str(uuid.uuid4()),
        "layouts": [{
            "id": 0,
            "position": {
                "x": x, "y": y, "z": z,
                "width": width, "height": height, "tabOrder": z,
            },
        }],
        "singleVisual": {
            "visualType": "textbox",
            "drillFilterOtherVisuals": True,
            "objects": {
                "general": [{
                    "properties": {
                        "paragraphs": [{
                            "textRuns": [{
                                "value": text,
                                "textStyle": {
                                    "fontSize": "14pt",
                                    "fontWeight": "bold",
                                    "color": "#1B1B22",
                                },
                            }]
                        }]
                    }
                }]
            },
            "vcObjects": {
                "title": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}]
            },
        },
    }
    return {
        "x": x, "y": y, "z": z, "width": width, "height": height,
        "config": json.dumps(config),
        "filters": "[]",
    }


def era_slicer(position: tuple[float, float, float, float] = (16, 74, 232, 150)) -> dict:
    """The era slicer section 8 requires. Sync it across pages in Power BI."""
    return visual(
        "slicer", position,
        {"Values": [column_select("dim_date", "era")]},
        "Era", z=50,
    )


# --------------------------------------------------------------------------- #
# the six pages
# --------------------------------------------------------------------------- #

def overview() -> list[dict]:
    return [
        textbox((16, 12, 1248, 50),
                "Franchise attention has fallen since 2023, while the new series' own article rose sharply"),
        era_slicer(),
        visual("card", (264, 74, 236, 110),
               {"Values": [measure_select("Film Count")]}, "Films"),
        visual("card", (516, 74, 236, 110),
               {"Values": [measure_select("Total Worldwide Gross")]}, "Franchise box office"),
        visual("card", (768, 74, 236, 110),
               {"Values": [measure_select("Set Count")]}, "Construction sets"),
        visual("card", (1020, 74, 244, 110),
               {"Values": [measure_select("Mean Weekly Attention")]}, "Mean weekly attention"),
        visual("lineChart", (264, 200, 1000, 250),
               {"Category": [column_select("dim_date", "year_month")],
                "Y": [measure_select("Mean Weekly Attention")]},
               "Attention over time"),
        visual("clusteredColumnChart", (16, 466, 616, 238),
               {"Category": [column_select("dim_date", "year")],
                "Y": [measure_select("Total Worldwide Gross")]},
               "Box office by year"),
        visual("clusteredColumnChart", (648, 466, 616, 238),
               {"Category": [column_select("dim_date", "year")],
                "Y": [measure_select("Set Count")]},
               "Sets released by year"),
    ]


def return_on_investment() -> list[dict]:
    return [
        textbox((16, 12, 1248, 50),
                "Deathly Hallows Part 2 returned 10.5x its assigned budget; Secrets of Dumbledore returned 2.0"),
        era_slicer(),
        visual("scatterChart", (264, 74, 1000, 376),
               {"Category": [column_select("dim_film", "title")],
                "X": [measure_select("Total Budget")],
                "Y": [measure_select("Total Worldwide Gross")],
                "Size": [measure_select("Profit")]},
               "Budget against worldwide gross, bubble size is gross profit"),
        visual("tableEx", (16, 466, 1248, 238),
               {"Values": [column_select("dim_film", "title"),
                           column_select("dim_film", "era"),
                           measure_select("Total Budget"),
                           measure_select("Total Worldwide Gross"),
                           measure_select("Return on Budget"),
                           measure_select("Profit Margin")]},
               "Film performance"),
    ]


def reception() -> list[dict]:
    return [
        textbox((16, 12, 1248, 50),
                "Audiences rated Secrets of Dumbledore 37 points above critics"),
        visual("scatterChart", (16, 74, 760, 376),
               {"Category": [column_select("dim_film", "title")],
                "X": [aggregate_select("dim_film", "rt_critic_score", 1, "Critic score")],
                "Y": [aggregate_select("dim_film", "rt_audience_score", 1, "Audience score")]},
               "Critic score against audience score"),
        visual("clusteredBarChart", (792, 74, 472, 376),
               {"Category": [column_select("dim_film", "title")],
                "Y": [measure_select("Critic Audience Gap")]},
               "Critic minus audience; negative means audiences liked it more"),
        visual("tableEx", (16, 466, 1248, 238),
               {"Values": [column_select("dim_film", "title"),
                           aggregate_select("dim_film", "rt_critic_score", 1, "Critic"),
                           aggregate_select("dim_film", "rt_audience_score", 1, "Audience"),
                           aggregate_select("dim_film", "metacritic_score", 1, "Metacritic")]},
               "Reception scores"),
    ]


def geography() -> list[dict]:
    return [
        textbox((16, 12, 1248, 50),
                "Search interest is near-saturated across Western markets: Canada is 9th of 61 at 97"),
        # A bar chart rather than the map section 8 asks for. Power BI disables
        # map and filled map visuals by default under Options > Global >
        # Security, so a map renders as a "visuals are disabled" placeholder on
        # a fresh install and the page looks broken. A bar chart works
        # everywhere, needs no setting changed and no Bing Maps call, and for
        # 61 countries it is the more readable of the two anyway. The map is
        # kept as a commented alternative below for anyone who wants it.
        visual("clusteredBarChart", (16, 74, 760, 630),
               {"Category": [column_select("dim_country", "country_name")],
                "Y": [aggregate_select("dim_country", "search_interest", 1, "Interest")]},
               "Franchise search interest by country"),
        visual("tableEx", (792, 74, 472, 630),
               {"Values": [column_select("dim_country", "country_name"),
                           aggregate_select("dim_country", "interest_rank", 3, "Rank"),
                           aggregate_select("dim_country", "search_interest", 1, "Interest")]},
               "Interest by country, ranked"),
        # To use a map instead, enable map visuals in Power BI under
        # File > Options and settings > Options > Global > Security, then swap
        # the bar chart above for:
        #     visual("map", (16, 74, 760, 630),
        #            {"Category": [column_select("dim_country", "country_name")],
        #             "Size": [aggregate_select("dim_country", "search_interest", 1, "Interest")]},
        #            "Franchise search interest by country"),
    ]


def product_line() -> list[dict]:
    return [
        textbox((16, 12, 1248, 50),
                "No retail price source was available, so the licensing premium is untested; size and count are not"),
        # No price card. "Average Price Per Piece" is a real measure and stays in
        # the model, but with no price source it renders "(Blank)", and a blank
        # tile on a dashboard reads as something broken rather than as something
        # honestly absent. The absence is stated in the page heading instead,
        # where it can be read as a sentence.
        visual("card", (16, 74, 400, 110),
               {"Values": [measure_select("Set Count")]}, "Sets in the line"),
        visual("card", (432, 74, 400, 110),
               {"Values": [measure_select("Total Pieces")]}, "Total pieces"),
        visual("card", (848, 74, 416, 110),
               {"Values": [measure_select("Film Count")]}, "Films released"),
        visual("clusteredColumnChart", (16, 200, 616, 504),
               {"Category": [column_select("fact_product_release", "year")],
                "Y": [measure_select("Set Count")]},
               "Sets released per year"),
        visual("lineChart", (648, 200, 616, 504),
               {"Category": [column_select("fact_product_release", "year")],
                "Y": [aggregate_select("fact_product_release", "num_parts", 1, "Average pieces")]},
               "Average pieces per set by year"),
    ]


def timing() -> list[dict]:
    return [
        textbox((16, 12, 1248, 50),
                "The category peaks at 172 in December and collapses to 86 in January; attention barely moves"),
        visual("lineChart", (16, 74, 1248, 330),
               {"Category": [column_select("dim_date", "month_name")],
                "Y": [measure_select("Seasonality Index")]},
               "Category seasonality index, 100 is an average month"),
        visual("clusteredColumnChart", (16, 420, 616, 284),
               {"Category": [column_select("dim_date", "month_name")],
                "Y": [measure_select("Category Sales Real")]},
               "Category sales by month"),
        visual("lineChart", (648, 420, 616, 284),
               {"Category": [column_select("dim_date", "month_name")],
                "Y": [measure_select("Mean Weekly Attention")]},
               "Franchise attention by month"),
    ]


PAGE_BUILDERS = {
    "Overview": overview,
    "Return on investment": return_on_investment,
    "Reception": reception,
    "Geography": geography,
    "Product line": product_line,
    "Timing": timing,
}


def visuals_for(page: str) -> list[dict]:
    builder = PAGE_BUILDERS.get(page)
    return builder() if builder else []
