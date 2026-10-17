"""Drawing my one page infographic from the saved tables, not laying it out by hand (module 9).

Reading: outputs/tables/*.csv
Writing: images/infographic/data_wizardry_infographic.png
         images/infographic/data_wizardry_infographic.pdf
Runtime: about twenty seconds.

I first planned to make this page in Canva. Canva runs in a browser and I
cannot drive it from a script, so I draw the page here. Every number on the
page is read from a file in outputs/tables when the page is drawn, so each
number traces back to a file without anyone checking it by hand.

The page is a portrait canvas with A3 proportions. It has a headline block, a
calendar strip, three charts, a scenario block and a footer.

This file is my only record of the design. I once kept a separate document,
infographic/asset_pack.md, with a table tracing every number to its source
file. One row in it had already gone stale. A list kept by hand can only go
stale, so I deleted it and did not correct it.

The caveat line and the source line at the foot of the page are part of the
design. A one page summary that gives a recommendation should also say what it
rests on, and that costs me only one line.

The calendar strip carries my finding, so it gets the most space after the
headline: two shaded bands that barely overlap, with the premiere between them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.gridspec import GridSpec

from src.utils.config import path, repo_root
from src.utils.io import relative
from src.utils.logging_setup import RunTimer, get_logger
from src.utils.plotting import PALETTE, apply_style

SCRIPT = "28_infographic"
logger = get_logger(SCRIPT)

OUTPUT_DIR = repo_root() / "images" / "infographic"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def table(name: str) -> pd.DataFrame:
    return pd.read_csv(path("outputs_tables", name))


def money_short(value: float) -> str:
    r"""Making a short money label with the dollar sign escaped for matplotlib.

    Two plain dollar signs in one string are read as LaTeX mathtext. That
    swallowed the words between them with no warning and drew "$2.0m to $2.5m"
    as "2.0mto2.5m". Escaping makes every dollar sign literal.
    """
    if abs(value) >= 1_000_000:
        return rf"\${value / 1_000_000:.1f}m"
    if abs(value) >= 1_000:
        return rf"\${value / 1_000:.0f}k"
    return rf"\${value:.0f}"


def draw_headline(ax, recommendation: pd.Series, tradeoff: pd.DataFrame) -> None:
    ax.axis("off")
    best = tradeoff.loc[tradeoff["expected_profit_cad"].idxmax()]
    safest = tradeoff.loc[tradeoff["worst_case_profit_cad"].idxmax()]
    low = min(float(best["january_reserve_proportion"]), float(safest["january_reserve_proportion"]))
    high = max(float(best["january_reserve_proportion"]), float(safest["january_reserve_proportion"]))

    ax.text(0, 1.00, "DATA WIZARDRY IN HOGWARTS", fontsize=11, color=PALETTE["accent"],
            fontweight="bold", va="top", transform=ax.transAxes)
    ax.text(0, 0.90, "The premiere lands on the day\nthe buying stops",
            fontsize=27, color=PALETTE["ink"], fontweight="bold", va="top",
            linespacing=1.15, transform=ax.transAxes)

    ax.text(0, 0.44, money_short(float(recommendation["recommended_buy_cad_retail"])),
            fontsize=62, color=PALETTE["accent"], fontweight="bold", va="top",
            transform=ax.transAxes)
    ax.text(0.005, 0.13,
            f"wizarding category buy for Nov 2026 to Mar 2027, about "
            f"{round(float(recommendation['recommended_units']), -3):,.0f} units",
            fontsize=11.5, color=PALETTE["muted"], va="top", transform=ax.transAxes)
    # Writing the order date the way the README does, as 27 August 2026.
    order_by = pd.Timestamp(recommendation["january_order_by_imported"])
    ax.text(0.005, 0.05,
            f"Hold {low:.0%} to {high:.0%} of it for January. Imported product was due on order by "
            f"{order_by.day} {order_by:%B %Y}.",
            fontsize=11.5, color=PALETTE["ink"], va="top", fontweight="bold",
            transform=ax.transAxes)


def draw_calendar(ax, seasonality: pd.DataFrame) -> None:
    """Drawing the picture that carries my finding: two bands that barely overlap."""
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 1)
    ax.axis("off")

    category = seasonality[seasonality["series"].str.contains("459A", na=False)]
    december = float(category[category["month_number"] == 12]["seasonal_index"].iloc[0])
    january = float(category[category["month_number"] == 1]["seasonal_index"].iloc[0])

    # Placing each date by its real day count, so 1 Nov is x = 0 and 31 Mar is x = 12.
    start, end = pd.Timestamp("2026-11-01"), pd.Timestamp("2027-03-31")

    def x_of(day: str) -> float:
        return 12 * (pd.Timestamp(day) - start).days / (end - start).days

    premiere = x_of("2026-12-25")
    ax.add_patch(plt.Rectangle((0, 0.42), premiere - 0.05, 0.34, color=PALETTE["highlight"], alpha=0.22, lw=0))
    ax.add_patch(plt.Rectangle((premiere + 0.05, 0.42), 12 - premiere - 0.05, 0.34,
                               color=PALETTE["accent"], alpha=0.16, lw=0))

    ax.plot([premiere, premiere], [0.34, 0.86], color=PALETTE["highlight"], lw=2.6, linestyle="--")
    ax.text(premiere, 0.92, "PREMIERE  25 Dec", fontsize=10.5, color=PALETTE["warn"],
            fontweight="bold", ha="center")

    ax.text(premiere / 2, 0.59, "Gift buying window", fontsize=11.5, ha="center",
            va="center", color=PALETTE["ink"], fontweight="bold")
    ax.text(premiere / 2, 0.48, f"category peaks at {december:.0f} in December", fontsize=10,
            ha="center", va="center", color=PALETTE["muted"])

    ax.text((premiere + 12) / 2, 0.59, "Viewing driven demand", fontsize=11.5, ha="center",
            va="center", color=PALETTE["ink"], fontweight="bold")
    ax.text((premiere + 12) / 2, 0.48, f"category normally falls to {january:.0f} in January", fontsize=10,
            ha="center", va="center", color=PALETTE["muted"])

    for x, label in [(0, "1 Nov"), (premiere, "25 Dec"), (x_of("2027-01-31"), "31 Jan"), (12, "31 Mar")]:
        ax.text(x, 0.30, label, fontsize=9, color=PALETTE["muted"],
                ha="left" if x == 0 else ("right" if x == 12 else "center"))
    ax.plot([0, 12], [0.38, 0.38], color=PALETTE["grid"], lw=1)

    ax.text(6, 0.10,
            "The category empties its shelves in the same weeks the show arrives.",
            fontsize=11, ha="center", color=PALETTE["ink"], style="italic")


def draw_seasonality(ax, seasonality: pd.DataFrame) -> None:
    def series(fragment: str) -> list[float]:
        rows = seasonality[seasonality["series"].str.contains(fragment, na=False)]
        return [float(rows[rows["month_number"] == m]["seasonal_index"].iloc[0]) for m in range(1, 13)]

    x = range(1, 13)
    ax.axvspan(10.5, 12.5, color=PALETTE["highlight"], alpha=0.12, zorder=0)
    ax.plot(x, series("459A"), color=PALETTE["support"], lw=2.4, marker="o", markersize=4,
            label="book & hobby retail")
    ax.plot(x, series("Franchise attention"), color=PALETTE["accent"], lw=2.4, marker="o",
            markersize=4, label="franchise attention")
    ax.axhline(100, color=PALETTE["grid"], lw=1, zorder=0)
    ax.set_xticks(list(x))
    ax.set_xticklabels(MONTHS, fontsize=8)
    # Reading both swings from the table, so my title cannot go stale.
    retail_swing = max(series("459A")) - min(series("459A"))
    attention_swing = max(series("Franchise attention")) - min(series("Franchise attention"))
    ax.set_title(f"Retail swings {retail_swing:.0f} points a year. "
                 f"Attention swings {attention_swing:.0f}.",
                 loc="left", fontsize=11, fontweight="bold")
    ax.set_ylabel("index, 100 = average month", fontsize=9)
    ax.legend(fontsize=8.5, loc="upper left")


def draw_demand(ax, profile: pd.DataFrame) -> None:
    central = profile[profile["scenario"] == "central"]
    months = central["month_name"].tolist()
    x = np.arange(len(months))

    ax.bar(x, central["forecast_sales_cad"] / 1000, color=PALETTE["accent"],
           width=0.6, label="with premiere")
    ax.plot(x, central["baseline_sales_cad"] / 1000, color=PALETTE["ink"], lw=2.0,
            linestyle="--", marker="o", markersize=4, label="without")
    ax.axvline(1.5, color=PALETTE["highlight"], lw=1.8, linestyle="--")

    ax.set_xticks(x)
    ax.set_xticklabels([m.replace(" 202", "\n'2") for m in months], fontsize=8)
    ax.set_title("January is where the premiere pays.", loc="left", fontsize=11, fontweight="bold")
    ax.set_ylabel("category sales, $000", fontsize=9)
    ax.legend(fontsize=8.5, loc="upper right")


def draw_tradeoff(ax, tradeoff: pd.DataFrame) -> None:
    x = tradeoff["january_reserve_proportion"] * 100
    best_index = int(tradeoff["expected_profit_cad"].idxmax())
    colours = [
        PALETTE["accent"] if i == best_index else PALETTE["muted"]
        for i in range(len(tradeoff))
    ]
    ax.bar(x, tradeoff["expected_profit_cad"] / 1000, color=colours, width=7)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(v)}%" for v in x], fontsize=8)
    # Reading the two reserve shares from the table, the same way my headline does.
    safest_index = int(tradeoff["worst_case_profit_cad"].idxmax())
    shares = sorted(float(tradeoff["january_reserve_proportion"][i]) for i in (best_index, safest_index))
    ax.set_title(f"Hold back {shares[0]:.0%} to {shares[1]:.0%}. Expected profit peaks there.",
                 loc="left", fontsize=11, fontweight="bold")
    ax.set_ylabel("expected profit, $000", fontsize=9)
    ax.set_xlabel("share held for January", fontsize=9)


def draw_footer(ax, sensitivity: pd.DataFrame, assumption: float) -> None:
    ax.axis("off")
    low = float(sensitivity["season_sales_central_cad"].iloc[0])
    high = float(sensitivity["season_sales_central_cad"].iloc[-1])

    ax.text(0, 0.86,
            f"The conversion from attention to sales is an assumption ({assumption:.0%}), not a "
            f"measurement. Across its plausible range central season sales run {money_short(low)} to "
            f"{money_short(high)}.",
            fontsize=10, color=PALETTE["warn"], va="top", transform=ax.transAxes, wrap=True)
    ax.plot([0, 1], [0.62, 0.62], color=PALETTE["grid"], lw=1, transform=ax.transAxes)
    ax.text(0, 0.50,
            "Sources: Wikimedia pageviews, Google Trends, Statistics Canada 20-10-0056 and "
            "20-10-0008, PotterDB, Rebrickable, The Numbers, Box Office Mojo, Rotten Tomatoes, "
            "TEA/AECOM Theme Index.",
            fontsize=8, color=PALETTE["muted"], va="top", transform=ax.transAxes)
    ax.text(0, 0.24,
            "Nusrat Jahan · MBAI, Ontario Tech University · Analysis 3 September 2026 · "
            "Every number generated from outputs/tables",
            fontsize=8, color=PALETTE["muted"], va="top", transform=ax.transAxes)


def main() -> None:
    apply_style()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with RunTimer(SCRIPT, logger) as run:
        recommendation = table("retail_recommendation.csv").iloc[0]
        seasonality = table("seasonality_monthly_index.csv")
        profile = table("retail_demand_profile.csv")
        tradeoff = table("retail_january_reserve_tradeoff.csv")
        sensitivity = table("retail_sensitivity.csv")
        assumptions = table("retail_assumptions.csv")

        pass_through = float(
            assumptions.loc[
                assumptions["assumption"] == "attention to sales pass-through", "value"
            ].iloc[0]
        )

        fig = plt.figure(figsize=(11.7, 16.5))  # Using A3 proportions, portrait
        grid = GridSpec(
            5, 2, figure=fig,
            height_ratios=[1.45, 0.85, 1.15, 1.15, 0.55],
            hspace=0.42, wspace=0.26,
            left=0.075, right=0.945, top=0.965, bottom=0.035,
        )

        draw_headline(fig.add_subplot(grid[0, :]), recommendation, tradeoff)
        draw_calendar(fig.add_subplot(grid[1, :]), seasonality)
        draw_seasonality(fig.add_subplot(grid[2, 0]), seasonality)
        draw_demand(fig.add_subplot(grid[2, 1]), profile)
        draw_tradeoff(fig.add_subplot(grid[3, 0]), tradeoff)

        # Putting the three scenario numbers as text in the right cell of row 3.
        # That reads better than a fourth chart on a page this full.
        ax_numbers = fig.add_subplot(grid[3, 1])
        ax_numbers.axis("off")
        ax_numbers.set_title("The range, and why it is wide.", loc="left",
                             fontsize=11, fontweight="bold")
        lines = [
            ("Low", float(recommendation["low_season_demand_cad"])),
            ("Central", float(recommendation["central_season_demand_cad"])),
            ("High", float(recommendation["high_season_demand_cad"])),
        ]
        for i, (label, value) in enumerate(lines):
            y = 0.74 - i * 0.19
            ax_numbers.text(0.02, y, label, fontsize=11, color=PALETTE["muted"],
                            transform=ax_numbers.transAxes)
            ax_numbers.text(0.45, y, money_short(value), fontsize=17,
                            color=PALETTE["accent"] if label == "Central" else PALETTE["ink"],
                            fontweight="bold" if label == "Central" else "normal",
                            transform=ax_numbers.transAxes)
        ax_numbers.text(
            0.02, 0.10,
            "The premiere response is imposed from measured\n"
            "franchise events, not fitted. These are three readings\n"
            "of that evidence, not confidence intervals.",
            fontsize=8.5, color=PALETTE["muted"], transform=ax_numbers.transAxes,
        )

        draw_footer(fig.add_subplot(grid[4, :]), sensitivity, pass_through)

        png = OUTPUT_DIR / "data_wizardry_infographic.png"
        pdf = OUTPUT_DIR / "data_wizardry_infographic.pdf"
        fig.savefig(png, dpi=170, facecolor=PALETTE["ground"])
        fig.savefig(pdf, facecolor=PALETTE["ground"])
        plt.close(fig)

        run.rows_out = 1
        run.note = "one page, PNG and PDF"
        logger.info("infographic written to %s and %s", relative(png), relative(pdf))

    logger.info("infographic complete")


if __name__ == "__main__":
    main()
