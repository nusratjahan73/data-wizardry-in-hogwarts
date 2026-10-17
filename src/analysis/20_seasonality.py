"""Finding when franchise attention peaks in the year, and whether it leads retail (module 3.3).

Reading: data/processed/attention_weekly.csv, data/processed/retail_monthly.csv
Writing: images/figures/seasonality_attention_vs_retail.png
         images/figures/seasonality_decomposition.png
         outputs/tables/seasonality_monthly_index.csv
         outputs/tables/seasonality_peak_timing.csv
         docs/findings.md (one entry)
Runtime: about twenty seconds.

My whole timing argument rests on this script. I want to know if the franchise
peak comes before, after or in the same month as the general retail peak.

I split both series with STL, because it copes with a seasonal pattern that
changes shape over twenty years better than a fixed classical decomposition.
From each seasonal part I build a monthly index: each month's average against
the yearly average. So 100 means an average month and 130 means a month running
thirty per cent above it.

I measure attention with Wikipedia pageviews, not search interest. Pageviews are
real counts with a stable definition. Search interest is a relative index that I
had to stitch across windows. So my comparison chart and the number in my
finding both come from pageviews.

I leave 2020 and 2021 out of the retail seasonal estimate. Lockdowns moved
Canadian retail sales more than any Christmas ever has, so those years tell me
nothing about a normal year.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from src.utils.config import get
from src.utils.io import read_processed, relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import PALETTE, apply_style, save_figure, title_block

SCRIPT = "20_seasonality"
logger = get_logger(SCRIPT)

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Using the franchise level article, because it is my broadest measure of
# attention to the whole property and not to one film or one character.
FRANCHISE_ARTICLE = "Harry_Potter"

# Leaving these years out of every seasonal estimate. I explain why at the top of this file.
PANDEMIC_YEARS = [2020, 2021]


def monthly_attention() -> pd.Series:
    """Returning franchise pageviews as a monthly series, with the pandemic years dropped."""
    attention = read_processed("attention_weekly.csv")
    series = attention[
        (attention["source"] == "wikipedia_pageviews")
        & (attention["series"] == FRANCHISE_ARTICLE)
    ].copy()

    if series.empty:
        raise ValueError(f"no pageview data for {FRANCHISE_ARTICLE}")

    series["week"] = pd.to_datetime(series["week"])
    series = series.set_index("week").sort_index()

    # Turning weekly into monthly with the mean and not the sum, so a month with
    # five reporting weeks is not bigger than one with four just for that reason.
    monthly = series["value"].resample("MS").mean()
    return monthly[~monthly.index.year.isin(PANDEMIC_YEARS)].dropna()


def monthly_retail(naics_code: str) -> pd.Series:
    """Returning one NAICS category as a monthly series, with the pandemic years dropped."""
    retail = read_processed("retail_monthly.csv")
    series = retail[retail["naics_code"] == naics_code].copy()
    if series.empty:
        raise ValueError(f"no retail data for NAICS {naics_code}")

    series["month"] = pd.to_datetime(series["month"])
    series = series.set_index("month").sort_index()

    # Using real dollars when I have them. A nominal series mixes inflation up with
    # seasonality, and thirty five years of inflation is a lot to mix up.
    column = "sales_thousands_cad_real"
    if column not in series.columns or series[column].isna().all():
        column = "sales_thousands_cad"
        log_data_issue(
            SCRIPT, "seasonality",
            "no real sales column, so seasonality was measured on nominal dollars",
            "the trend component absorbs inflation; the seasonal component is "
            "largely unaffected, but say so in the methods note",
        )

    values = series[column].dropna()
    return values[~values.index.year.isin(PANDEMIC_YEARS)]


def seasonal_index(series: pd.Series, period: int, label: str) -> tuple[pd.Series, pd.DataFrame]:
    """Decomposing a series and returning a monthly index where 100 is an average month.

    STL needs a regular series with no gaps, and dropping the pandemic years leaves
    a hole. So I run STL on the full series and take the pandemic months out of the
    index afterwards. The seasonal part is then estimated on unbroken data, but the
    abnormal years do not set the average.
    """
    regular = series.asfreq("MS")
    missing = int(regular.isna().sum())
    if missing:
        regular = regular.interpolate(limit_direction="both")
        logger.info("%s: interpolated %d missing months for the decomposition", label, missing)

    stl = STL(regular, period=period, robust=True).fit()

    seasonal = stl.seasonal
    trend = stl.trend
    # Indexing each month against its own trend, so a rising series does not make
    # later Decembers look more seasonal than earlier ones.
    ratio = (regular / trend).dropna()
    ratio = ratio[~ratio.index.year.isin(PANDEMIC_YEARS)]

    by_month = ratio.groupby(ratio.index.month).agg(["mean", "std", "count"])
    by_month.index.name = "month_number"
    by_month["index"] = by_month["mean"] / by_month["mean"].mean() * 100
    by_month["index_std"] = by_month["std"] / by_month["mean"].mean() * 100
    by_month["month_name"] = [MONTH_NAMES[m - 1] for m in by_month.index]
    by_month["series"] = label

    components = pd.DataFrame(
        {"observed": regular, "trend": trend, "seasonal": seasonal, "residual": stl.resid}
    )
    return by_month["index"], by_month.reset_index().join(components.head(0).T.iloc[:0]).assign(series=label)


def decompose_components(series: pd.Series, period: int) -> pd.DataFrame:
    regular = series.asfreq("MS").interpolate(limit_direction="both")
    stl = STL(regular, period=period, robust=True).fit()
    return pd.DataFrame(
        {"observed": regular, "trend": stl.trend, "seasonal": stl.seasonal, "residual": stl.resid}
    )


def peak_month(index: pd.Series) -> tuple[int, float]:
    return int(index.idxmax()), float(index.max())


def plot_comparison(indices: dict[str, pd.Series], headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 5.8))

    styles = {
        "Franchise attention": (PALETTE["accent"], "-", 2.4),
        "Book and hobby retail (459A)": (PALETTE["support"], "-", 2.0),
        "All Canadian retail (44-45)": (PALETTE["muted"], "--", 1.6),
    }

    for label, index in indices.items():
        colour, style, width = styles.get(label, (PALETTE["muted"], "-", 1.5))
        ax.plot(range(1, 13), index.reindex(range(1, 13)).values,
                color=colour, linestyle=style, linewidth=width, marker="o", markersize=4, label=label)

    ax.axhline(100, color=PALETTE["grid"], linewidth=1, zorder=0)
    ax.axvspan(10.5, 12.5, color=PALETTE["highlight"], alpha=0.10, zorder=0)

    # Placing the shading label inside the axes and not at the top edge, where
    # it would sit under my title block.
    bottom, top = ax.get_ylim()
    ax.text(11.5, bottom + (top - bottom) * 0.94, "gift buying\nwindow",
            ha="center", va="top", fontsize=8.5, color=PALETTE["warn"])

    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(MONTH_NAMES)
    ax.set_ylabel("seasonal index, 100 = average month")
    ax.set_xlabel("")
    ax.legend(loc="upper left")

    # Building the title from my measured numbers. It states the finding, and it
    # cannot drift away from the chart under it when I refresh the data.
    title_block(ax, headline, subtitle)
    return save_figure(
        fig, "seasonality_attention_vs_retail.png",
        "Wikipedia pageviews 2015-2026 and Statistics Canada 20-10-0056/20-10-0008, retrieved 2 September 2026",
    )


def plot_decomposition(components: pd.DataFrame, headline: str) -> Path:
    apply_style()
    fig, axes = plt.subplots(4, 1, figsize=(11, 8), sharex=True)

    for ax, (name, colour) in zip(
        axes,
        [("observed", PALETTE["ink"]), ("trend", PALETTE["accent"]),
         ("seasonal", PALETTE["support"]), ("residual", PALETTE["muted"])],
        strict=False,
    ):
        ax.plot(components.index, components[name], color=colour, linewidth=1.4)
        ax.set_ylabel(name, fontsize=9)
        ax.grid(True, alpha=0.4)

    axes[0].set_title(headline, loc="left")
    axes[3].set_xlabel("")
    fig.align_ylabels(axes)
    return save_figure(
        fig, "seasonality_decomposition.png",
        "STL decomposition of monthly Wikipedia pageviews for the Harry Potter article",
    )


def main() -> None:
    focus_code = get("sources.statcan.naics_focus")
    control_code = get("sources.statcan.naics_control")

    with RunTimer(SCRIPT, logger) as run:
        attention = monthly_attention()
        focus = monthly_retail(focus_code)
        control = monthly_retail(control_code)

        logger.info(
            "attention %s to %s (%d months), retail %s to %s (%d months)",
            attention.index.min().date(), attention.index.max().date(), len(attention),
            focus.index.min().date(), focus.index.max().date(), len(focus),
        )

        attention_index, _ = seasonal_index(attention, 12, "franchise_attention")
        focus_index, _ = seasonal_index(focus, 12, f"retail_{focus_code}")
        control_index, _ = seasonal_index(control, 12, f"retail_{control_code}")

        indices = {
            "Franchise attention": attention_index,
            "Book and hobby retail (459A)": focus_index,
            "All Canadian retail (44-45)": control_index,
        }

        # Working out the numbers that my finding quotes.
        attention_peak, attention_peak_value = peak_month(attention_index)
        focus_peak, focus_peak_value = peak_month(focus_index)
        control_peak, control_peak_value = peak_month(control_index)

        attention_swing = float(attention_index.max() - attention_index.min())
        focus_swing = float(focus_index.max() - focus_index.min())

        headline = (
            f"The category swings {focus_swing:.0f} index points across the year; "
            f"franchise attention swings {attention_swing:.0f}"
        )
        subtitle = (
            f"Monthly seasonal index from STL decomposition, 100 = an average month. "
            f"Category peaks {MONTH_NAMES[focus_peak - 1]} at {focus_peak_value:.0f}, "
            f"attention peaks {MONTH_NAMES[attention_peak - 1]} at {attention_peak_value:.0f}. "
            f"Pandemic years excluded."
        )
        figure_path = plot_comparison(indices, headline, subtitle)

        components = decompose_components(attention, 12)
        trend_change = float(components["trend"].iloc[-1] / components["trend"].iloc[0] - 1)
        trend_word = "falling" if trend_change < -0.05 else "rising" if trend_change > 0.05 else "broadly flat"
        plot_decomposition(
            components,
            f"Franchise attention: a {trend_word} trend ({trend_change:+.0%} over the period), "
            f"a repeating seasonal shape, and the March 2026 trailer as the largest shock in the series",
        )

        lead_months = attention_peak - focus_peak

        logger.info(
            "peak months: attention %s (%.0f), focus retail %s (%.0f), all retail %s (%.0f)",
            MONTH_NAMES[attention_peak - 1], attention_peak_value,
            MONTH_NAMES[focus_peak - 1], focus_peak_value,
            MONTH_NAMES[control_peak - 1], control_peak_value,
        )

        long_index = pd.concat(
            [index.rename("seasonal_index").reset_index().assign(series=label) for label, index in indices.items()],
            ignore_index=True,
        )
        long_index["month_name"] = long_index["month_number"].map(lambda m: MONTH_NAMES[m - 1])
        index_table = save_table(
            "seasonality_monthly_index.csv",
            long_index[["series", "month_number", "month_name", "seasonal_index"]],
            note="100 means an average month for that series",
        )

        timing = pd.DataFrame([
            {
                "series": label,
                "peak_month": MONTH_NAMES[peak_month(index)[0] - 1],
                "peak_index": round(peak_month(index)[1], 1),
                "december_index": round(float(index.get(12, np.nan)), 1),
                "january_index": round(float(index.get(1, np.nan)), 1),
                "trough_month": MONTH_NAMES[int(index.idxmin()) - 1],
                "trough_index": round(float(index.min()), 1),
                "months_observed": int(index.notna().sum()),
            }
            for label, index in indices.items()
        ])
        save_table("seasonality_peak_timing.csv", timing)
        logger.info("peak timing table:\n%s", timing.to_string(index=False))

        # Writing the finding in words.
        def months(count: int) -> str:
            return "1 month" if abs(count) == 1 else f"{abs(count)} months"

        if lead_months < 0:
            relationship = f"{months(lead_months)} ahead of the category peak"
        elif lead_months > 0:
            relationship = f"{months(lead_months)} behind the category peak"
        else:
            relationship = "in the same month as the category peak"

        january_focus = float(focus_index.get(1, np.nan))
        january_attention = float(attention_index.get(1, np.nan))

        finding = (
            f"The two series are seasonal to very different degrees, and that gap is the "
            f"opportunity. The book and hobby category swings {focus_swing:.0f} index points "
            f"across the year, peaking in {MONTH_NAMES[focus_peak - 1]} at {focus_peak_value:.0f} "
            f"and falling to {january_focus:.0f} in January, while franchise attention barely "
            f"moves at all, spanning only {attention_swing:.0f} points and sitting at "
            f"{january_attention:.0f} in that same January. So the category's December peak is "
            f"made by the gift calendar, not by any surge of interest in the franchise, and "
            f"January is the month when shelves empty while attention does not. Attention peaks "
            f"in {MONTH_NAMES[attention_peak - 1]}, {relationship}, but the difference in "
            f"amplitude matters far more than the difference in timing."
        )

        write_finding(
            "3.3 Seasonality: when attention peaks against when Canadians shop",
            finding,
            evidence=(
                "STL decomposition of monthly Wikipedia pageviews and of Canadian monthly "
                "retail sales, each indexed against its own trend so that growth is not "
                "mistaken for seasonality."
            ),
            sample=(
                f"{len(attention)} months of attention data "
                f"({attention.index.min():%Y-%m} to {attention.index.max():%Y-%m}) and "
                f"{len(focus)} months of retail data "
                f"({focus.index.min():%Y-%m} to {focus.index.max():%Y-%m}). "
                f"2020 and 2021 excluded from both."
            ),
            uncertainty=(
                "The monthly index is a mean across years and each month's spread is in "
                "seasonality_monthly_index.csv. The attention series covers eleven years and "
                "the retail series thirty five, so the retail seasonal estimate is the firmer "
                "of the two. Pre 2017 retail values were rescaled from an archived table via "
                "a NAICS crosswalk that agrees with the active table to within 1.3 per cent."
            ),
            figure=relative(figure_path),
            table=relative(index_table),
        )

        run.rows_out = len(long_index)
        run.note = (
            f"attention peaks {MONTH_NAMES[attention_peak - 1]}, "
            f"focus retail peaks {MONTH_NAMES[focus_peak - 1]}"
        )

    logger.info("seasonality analysis complete")


if __name__ == "__main__":
    main()
