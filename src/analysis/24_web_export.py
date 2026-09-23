"""Export the numbers the web data story needs, as a JavaScript data file.

Reads  : outputs/tables/*.csv
Writes : web/js/data.js
Runtime: instant.

Why a .js file rather than .json. The web deliverable has to open by
double-clicking index.html, with no server. A `fetch` of a local JSON file from a
`file://` page is blocked by the browser's same-origin policy, so the page would
load and then silently show nothing. Declaring the data as a `const` in a script
file that index.html links works from the filesystem, and it still keeps the data
out of the markup, which is what section 4 actually asks for. It is a script
file, not an inline script block.

Every number on the page therefore traces to a table in outputs/tables, and
regenerating those tables and rerunning this script updates the page. Nothing on
the page is typed by hand, which is the same rule the infographic has to follow.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.config import as_date, get, path, repo_root
from src.utils.io import relative
from src.utils.logging_setup import RunTimer, get_logger

SCRIPT = "24_web_export"
logger = get_logger(SCRIPT)

TARGET = repo_root() / "web" / "js" / "data.js"


def table(name: str) -> pd.DataFrame:
    return pd.read_csv(path("outputs_tables", name))


def build_payload() -> dict:
    seasonality = table("seasonality_monthly_index.csv")
    timing = table("seasonality_peak_timing.csv")
    demand = table("demand_scenarios.csv")
    metrics = table("forecast_model_metrics.csv")
    profile = table("retail_demand_profile.csv")
    tradeoff = table("retail_january_reserve_tradeoff.csv")
    sensitivity = table("retail_sensitivity.csv")
    recommendation = table("retail_recommendation.csv").iloc[0]
    schedule = table("retail_order_schedule.csv")
    events = table("event_study_responses.csv")
    centrality = table("character_centrality.csv")

    def series_index(label_fragment: str) -> list[float]:
        rows = seasonality[seasonality["series"].str.contains(label_fragment, na=False)]
        return [
            round(float(rows[rows["month_number"] == m]["seasonal_index"].iloc[0]), 1)
            for m in range(1, 13)
        ]

    central_profile = profile[profile["scenario"] == "central"]
    best = tradeoff.loc[tradeoff["expected_profit_cad"].idxmax()]
    safest = tradeoff.loc[tradeoff["worst_case_profit_cad"].idxmax()]
    best_model = metrics.iloc[0]
    baseline = metrics[metrics["model"] == "seasonal naive"].iloc[0]

    return {
        "generated": datetime.now(UTC).strftime("%d %B %Y"),
        "premiere": str(as_date("dates.premiere")),
        "headline": {
            "buy": int(recommendation["recommended_buy_cad_retail"]),
            "units": int(recommendation["recommended_units"]),
            "januaryShareLow": float(safest["january_reserve_proportion"]),
            "januaryShareHigh": float(best["january_reserve_proportion"]),
            "orderBy": str(recommendation["january_order_by_imported"]),
            "rangeLow": int(recommendation["low_season_demand_cad"]),
            "rangeHigh": int(recommendation["high_season_demand_cad"]),
        },
        "seasonality": {
            "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "category": series_index("459A"),
            "attention": series_index("Franchise attention"),
            "allRetail": series_index("44-45"),
            "categoryPeak": float(timing[timing["series"].str.contains("459A")]["peak_index"].iloc[0]),
            "categoryJanuary": float(timing[timing["series"].str.contains("459A")]["january_index"].iloc[0]),
            "attentionSwing": round(
                float(timing[timing["series"].str.contains("Franchise")]["peak_index"].iloc[0])
                - float(timing[timing["series"].str.contains("Franchise")]["trough_index"].iloc[0]), 1
            ),
        },
        "demandProfile": {
            "months": central_profile["month_name"].tolist(),
            "baseline": [round(v) for v in central_profile["baseline_sales_cad"]],
            "low": [round(v) for v in profile[profile["scenario"] == "low"]["forecast_sales_cad"]],
            "central": [round(v) for v in central_profile["forecast_sales_cad"]],
            "high": [round(v) for v in profile[profile["scenario"] == "high"]["forecast_sales_cad"]],
        },
        "scenarios": demand[[
            "scenario", "premiere_peak_weekly_attention", "peak_multiple_vs_last_year_mean",
            "january_vs_gift_window_ratio", "assumed_peak_multiple",
        ]].to_dict(orient="records"),
        "forecast": {
            "bestModel": str(best_model["model"]),
            "bestMape": round(float(best_model["mape"]), 1),
            "baselineMape": round(float(baseline["mape"]), 1),
            "models": metrics[["model", "mape", "mae"]].round(1).to_dict(orient="records"),
        },
        "tradeoff": tradeoff[[
            "january_reserve_proportion", "expected_profit_cad", "worst_case_profit_cad",
        ]].to_dict(orient="records"),
        "sensitivity": sensitivity[[
            "attention_pass_through", "season_sales_central_cad",
        ]].to_dict(orient="records"),
        "orderSchedule": schedule[[
            "position", "product_type", "lead_time_days", "order_by", "already_late",
        ]].to_dict(orient="records"),
        "events": events[[
            "event", "peak_multiple", "days_to_settle", "step_multiple",
        ]].round(2).to_dict(orient="records"),
        "characters": centrality[[
            "character", "total_views", "mean_correlation", "attention_rank", "coupling_rank",
        ]].round(3).to_dict(orient="records"),
        "assumptions": {
            "passThrough": float(get("retail.attention_pass_through")),
            "categoryBaseline": int(get("retail.category_baseline_sales_cad")),
            "serviceLevel": float(recommendation["service_level_used"]),
        },
    }


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        payload = build_payload()
        TARGET.parent.mkdir(parents=True, exist_ok=True)

        body = json.dumps(payload, indent=2, default=str)
        TARGET.write_text(
            "// Generated by src/analysis/24_web_export.py. Do not edit by hand.\n"
            "// Every number here traces to a file in outputs/tables. Regenerate the\n"
            "// tables and rerun that script to update the page.\n"
            f"const STORY_DATA = {body};\n",
            encoding="utf-8",
        )

        run.rows_out = len(body)
        logger.info("wrote %d bytes to %s", len(body), relative(TARGET))

    logger.info("web data export complete")


if __name__ == "__main__":
    main()
