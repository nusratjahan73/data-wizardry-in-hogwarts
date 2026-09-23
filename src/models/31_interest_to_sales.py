"""Module 5.2. Does franchise attention move Canadian category sales, and with what lag?

Reads  : data/processed/attention_weekly.csv, data/processed/retail_monthly.csv
Writes : images/figures/interest_to_sales_lags.png
         outputs/tables/interest_to_sales_lags.csv
         outputs/tables/interest_to_sales_model.csv
         outputs/models/interest_to_sales.json
         docs/findings.md (one entry)
Runtime: about twenty seconds.

This is the bridge that turns attention into an order quantity, and section 11
is blunt about it: document its weakness honestly. So, before the method, the
three things that limit what this can ever show.

It is correlational. Nothing here identifies a causal effect. Attention and
sales both respond to the calendar, to the economy and to whatever else was
happening that month, and no instrument or experiment separates those.

It is category level, not product level. The published series is NAICS 459A,
"sporting goods, hobby, musical instrument, book retailers and news dealers",
which covers every hobby shop and bookshop in Canada. Wizarding merchandise is a
small fraction of one line inside that. Expecting franchise attention to explain
much of its month to month movement would be expecting a rowing boat to move the
tide, and the measured elasticity below should be read in that light.

It is eleven years of monthly data, which is about 134 points before any lag is
taken. That is a small sample for a regression with seasonal controls in it.

Method. Both series go to monthly. The model regresses log real category sales
on log franchise attention at lag L, controlling for log total Canadian retail
sales, which absorbs the general economy and the general Christmas, and on month
dummies, which absorb the category's own seasonal shape. What is left for
attention to explain is category movement that is not explained by the season or
by Canadian retail as a whole. Lags of zero to three months are each fitted and
compared on adjusted R squared and on the significance of the attention term.

Because the controls and the target are both logs, the attention coefficient
reads as an elasticity: a one per cent rise in attention is associated with a
coefficient per cent change in category sales.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.utils.config import get, path, random_seed
from src.utils.io import read_processed, relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import PALETTE, apply_style, save_figure, title_block

warnings.filterwarnings("ignore", category=FutureWarning)

SCRIPT = "31_interest_to_sales"
logger = get_logger(SCRIPT)

COMPOSITE_ARTICLES = [
    "Harry_Potter",
    "Wizarding_World",
    "Harry_Potter_(film_series)",
    "Fantastic_Beasts",
]

# Excluded, not adjusted. Canadian retail in April 2020 is not a data point
# about franchise attention; it is a data point about closed shops, and it would
# dominate any regression it appeared in.
PANDEMIC_START = "2020-03"
PANDEMIC_END = "2021-06"


def monthly_attention() -> pd.Series:
    """Composite franchise attention as a monthly mean of weekly views."""
    attention = read_processed("attention_weekly.csv")
    subset = attention[
        (attention["source"] == "wikipedia_pageviews")
        & (attention["series"].isin(COMPOSITE_ARTICLES))
    ].copy()
    subset["week"] = pd.to_datetime(subset["week"])
    wide = subset.pivot_table(index="week", columns="series", values="value", aggfunc="sum").dropna()
    weekly = wide.sum(axis=1).sort_index()
    return weekly.resample("MS").mean().rename("attention")


def monthly_sales(naics_code: str, name: str) -> pd.Series:
    retail = read_processed("retail_monthly.csv")
    series = retail[retail["naics_code"] == naics_code].copy()
    series["month"] = pd.to_datetime(series["month"])
    series = series.set_index("month").sort_index()

    column = "sales_thousands_cad_real"
    if column not in series.columns or series[column].isna().all():
        column = "sales_thousands_cad"
        log_data_issue(
            SCRIPT, "interest_to_sales",
            f"no real sales column for {naics_code}, using nominal",
            "inflation is then inside the trend; the elasticity is correspondingly less reliable",
        )
    return series[column].dropna().rename(name)


def build_panel() -> pd.DataFrame:
    """Join attention and both sales series onto one monthly frame."""
    focus_code = get("sources.statcan.naics_focus")
    control_code = get("sources.statcan.naics_control")

    panel = pd.concat(
        [
            monthly_attention(),
            monthly_sales(focus_code, "category_sales"),
            monthly_sales(control_code, "total_retail"),
        ],
        axis=1,
        sort=True,
    ).dropna()

    panel["month_number"] = panel.index.month

    pandemic = (panel.index >= PANDEMIC_START) & (panel.index <= PANDEMIC_END)
    excluded = int(pandemic.sum())
    if excluded:
        logger.info("excluded %d pandemic months (%s to %s)", excluded, PANDEMIC_START, PANDEMIC_END)
    return panel[~pandemic]


def fit_lag(panel: pd.DataFrame, lag: int):
    """Fit the lagged model and return its summary numbers and the fitted model.

    Attention is shifted forward by `lag` months, so the model asks whether
    attention this month is associated with sales `lag` months later.
    """
    frame = panel.copy()
    frame["attention_lagged"] = frame["attention"].shift(lag)
    frame = frame.dropna()

    if len(frame) < 36:
        logger.warning("lag %d has only %d usable months, skipping", lag, len(frame))
        return {"lag_months": lag, "observations": len(frame)}, None

    design = pd.DataFrame(
        {
            "log_attention": np.log(frame["attention_lagged"]),
            "log_total_retail": np.log(frame["total_retail"]),
        },
        index=frame.index,
    )

    # Month dummies, January dropped as the reference, so the category's own
    # seasonal shape is absorbed rather than attributed to attention.
    dummies = pd.get_dummies(frame["month_number"], prefix="m", drop_first=True).astype(float)
    design = sm.add_constant(pd.concat([design, dummies], axis=1))

    target = np.log(frame["category_sales"])

    # Newey-West standard errors: monthly retail is autocorrelated, and ordinary
    # errors would make the attention term look more precise than it is.
    model = sm.OLS(target, design).fit(cov_type="HAC", cov_kwds={"maxlags": 6})

    coefficient = float(model.params["log_attention"])
    lower, upper = model.conf_int().loc["log_attention"]

    return (
        {
            "lag_months": lag,
            "observations": len(frame),
            "elasticity": round(coefficient, 4),
            "ci_lower": round(float(lower), 4),
            "ci_upper": round(float(upper), 4),
            "p_value": round(float(model.pvalues["log_attention"]), 4),
            "significant_at_5pc": bool(model.pvalues["log_attention"] < 0.05),
            "adj_r_squared": round(float(model.rsquared_adj), 4),
            "total_retail_elasticity": round(float(model.params["log_total_retail"]), 4),
        },
        model,
    )


def fit_without_attention(panel: pd.DataFrame) -> float:
    """Adjusted R squared of the controls alone, the baseline this must beat.

    Section 11 requires a baseline beside every model. Here the meaningful
    baseline is not a naive forecast but the same regression with the attention
    term removed: if adding attention does not raise the adjusted R squared, then
    attention adds nothing once season and the wider economy are accounted for.
    """
    frame = panel.dropna()
    design = pd.DataFrame({"log_total_retail": np.log(frame["total_retail"])}, index=frame.index)
    dummies = pd.get_dummies(frame["month_number"], prefix="m", drop_first=True).astype(float)
    design = sm.add_constant(pd.concat([design, dummies], axis=1))
    model = sm.OLS(np.log(frame["category_sales"]), design).fit(
        cov_type="HAC", cov_kwds={"maxlags": 6}
    )
    return float(model.rsquared_adj)


def plot_lags(results: pd.DataFrame, baseline_r2: float, headline: str, subtitle: str) -> Path:
    apply_style()
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(12, 5.2))

    usable = results.dropna(subset=["elasticity"])

    ax_left.errorbar(
        usable["lag_months"], usable["elasticity"],
        yerr=[
            usable["elasticity"] - usable["ci_lower"],
            usable["ci_upper"] - usable["elasticity"],
        ],
        fmt="o", color=PALETTE["accent"], capsize=5, linewidth=1.8, markersize=7,
    )
    ax_left.axhline(0, color=PALETTE["ink"], linewidth=1.2, linestyle="--")
    ax_left.set_xlabel("lag, months between attention and sales")
    ax_left.set_ylabel("elasticity of category sales to attention")
    ax_left.set_xticks(usable["lag_months"])

    ax_right.bar(
        usable["lag_months"], usable["adj_r_squared"],
        color=PALETTE["support"], width=0.55,
    )
    ax_right.axhline(
        baseline_r2, color=PALETTE["accent"], linewidth=1.8, linestyle="--",
        label=f"controls only ({baseline_r2:.3f})",
    )
    ax_right.set_xlabel("lag, months")
    ax_right.set_ylabel("adjusted R squared")
    ax_right.set_xticks(usable["lag_months"])
    ax_right.set_ylim(
        min(baseline_r2 * 0.98, float(usable["adj_r_squared"].min()) * 0.98), 1.0
    )
    ax_right.legend(loc="lower right", fontsize=8.5)
    ax_right.set_title("Fit against the controls-only baseline", loc="left", fontsize=11)

    title_block(ax_left, headline, subtitle, subtitle_wrap=125)
    return save_figure(
        fig, "interest_to_sales_lags.png",
        "Wikipedia pageviews and Statistics Canada 20-10-0056/20-10-0008, retrieved 2 September 2026",
    )


def main() -> None:
    np.random.seed(random_seed())
    max_lag = int(get("modelling.max_interest_to_sales_lag_months"))

    with RunTimer(SCRIPT, logger) as run:
        panel = build_panel()
        run.rows_in = len(panel)
        logger.info(
            "panel: %d months, %s to %s",
            len(panel), panel.index.min().date(), panel.index.max().date(),
        )

        baseline_r2 = fit_without_attention(panel)
        logger.info("controls-only adjusted R squared: %.4f", baseline_r2)

        rows = []
        models = {}
        for lag in range(max_lag + 1):
            summary, model = fit_lag(panel, lag)
            summary["adj_r_squared_controls_only"] = round(baseline_r2, 4)
            summary["improvement_over_controls"] = (
                round(summary["adj_r_squared"] - baseline_r2, 4)
                if "adj_r_squared" in summary else np.nan
            )
            rows.append(summary)
            if model is not None:
                models[lag] = model

        results = pd.DataFrame(rows)
        logger.info("lag comparison:\n%s", results.to_string(index=False))

        lag_table = save_table(
            "interest_to_sales_lags.csv", results,
            note="elasticity is the log-log coefficient on franchise attention, "
                 "controlling for total Canadian retail and month of year",
        )

        usable = results.dropna(subset=["elasticity"])
        if usable.empty:
            log_data_issue(
                SCRIPT, "interest_to_sales",
                "no lag produced a fittable model",
                "the retail module must convert attention to sales using a stated "
                "assumption instead of a measured elasticity",
                severity="error",
            )
            run.rows_out = 0
            return

        # The best lag is the one with the strongest fit, but a lag whose
        # coefficient is not distinguishable from zero is reported as such
        # rather than quietly promoted for having the highest R squared.
        best = usable.loc[usable["adj_r_squared"].idxmax()]
        best_lag = int(best["lag_months"])
        any_significant = bool(usable["significant_at_5pc"].any())

        logger.info(
            "best lag %d months, elasticity %.4f (%.4f to %.4f), p=%.4f",
            best_lag, best["elasticity"], best["ci_lower"], best["ci_upper"], best["p_value"],
        )

        best_model = models[best_lag]
        coefficients = pd.DataFrame({
            "term": best_model.params.index,
            "coefficient": best_model.params.values,
            "std_error": best_model.bse.values,
            "p_value": best_model.pvalues.values,
            "ci_lower": best_model.conf_int()[0].values,
            "ci_upper": best_model.conf_int()[1].values,
        })
        save_table(
            "interest_to_sales_model.csv", coefficients,
            lag_months=best_lag,
            note="full coefficient table for the best fitting lag, Newey-West standard errors",
        )

        significance_text = (
            "distinguishable from zero at the five per cent level"
            if bool(best["significant_at_5pc"])
            else "not distinguishable from zero at the five per cent level"
        )
        headline = (
            f"Attention adds {best['improvement_over_controls']:+.3f} to adjusted R squared "
            f"once season and total retail are controlled for"
        )
        subtitle = (
            f"Best fit at a {best_lag} month lag: elasticity {best['elasticity']:.3f} "
            f"({best['ci_lower']:.3f} to {best['ci_upper']:.3f}), {significance_text}. "
            f"{int(best['observations'])} months, pandemic period excluded."
        )
        figure_path = plot_lags(results, baseline_r2, headline, subtitle)

        models_dir = path("outputs_models", create=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        (models_dir / "interest_to_sales.json").write_text(
            json.dumps({
                "best_lag_months": best_lag,
                "elasticity": float(best["elasticity"]),
                "ci": [float(best["ci_lower"]), float(best["ci_upper"])],
                "p_value": float(best["p_value"]),
                "significant_at_5pc": bool(best["significant_at_5pc"]),
                "adj_r_squared": float(best["adj_r_squared"]),
                "adj_r_squared_controls_only": baseline_r2,
                "observations": int(best["observations"]),
                "specification": (
                    "log category sales ~ log attention (lagged) + log total retail + month dummies"
                ),
                "standard_errors": "Newey-West, 6 lags",
                "interpretation": "correlational, category level, not causal",
            }, indent=2),
            encoding="utf-8",
        )

        if not any_significant:
            log_data_issue(
                SCRIPT, "interest_to_sales",
                "no lag produced an attention coefficient distinguishable from zero",
                "module 6 must not convert attention into sales through this elasticity. "
                "Use the scenario multiples directly against a stated category baseline "
                "and label the conversion an assumption.",
                severity="error",
            )

        if any_significant:
            closing = (
                "This is a real but very small association, which is what should be expected: "
                "wizarding merchandise is a thin slice of a category that contains every bookshop "
                "and hobby shop in Canada, so it cannot move the published series far."
            )
        else:
            closing = (
                "The honest reading is that this series cannot detect a franchise effect at all, "
                "and module 6 therefore converts attention into an order quantity through a stated "
                "assumption rather than through this elasticity."
            )

        finding = (
            f"Once the general Canadian retail cycle and the month of year are controlled for, "
            f"franchise attention adds {best['improvement_over_controls']:+.3f} to the adjusted "
            f"R squared of a model of category sales, moving it from {baseline_r2:.3f} to "
            f"{best['adj_r_squared']:.3f}. The strongest relationship sits at a {best_lag} month "
            f"lag with an elasticity of {best['elasticity']:.3f}, meaning a ten per cent rise in "
            f"attention is associated with a {best['elasticity'] * 10:.2f} per cent change in "
            f"category sales, and that coefficient is {significance_text}. {closing}"
        )

        write_finding(
            "5.2 Interest to sales: the bridge, and how much weight it will bear",
            finding,
            evidence=(
                "Log-log OLS of real category sales (NAICS 459A) on lagged franchise attention, "
                "controlling for log total Canadian retail sales and month of year dummies, with "
                "Newey-West standard errors at six lags to account for autocorrelation. Lags of "
                "zero to three months each fitted and compared against a controls-only baseline."
            ),
            sample=(
                f"{int(best['observations'])} monthly observations after lagging, from "
                f"{panel.index.min():%Y-%m} to {panel.index.max():%Y-%m}. March 2020 to June 2021 "
                f"excluded as pandemic months."
            ),
            uncertainty=(
                "This relationship is correlational and must be described that way everywhere it "
                "appears. It is measured at category level, and wizarding product is a small part "
                "of NAICS 459A, so the elasticity understates the effect on the specific products "
                "a buyer would order while overstating how confidently it can be applied to them. "
                "The confidence interval is in the table and the improvement over the controls-only "
                "baseline is small. Any order quantity derived from it inherits all of that, which "
                "is why module 6 carries a range rather than a point."
            ),
            figure=relative(figure_path),
            table=relative(lag_table),
        )

        run.rows_out = len(results)
        run.note = f"best lag {best_lag}m, elasticity {best['elasticity']:.3f}"

    logger.info("interest to sales analysis complete")


if __name__ == "__main__":
    main()
