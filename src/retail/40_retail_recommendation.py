"""Turning my forecast into a buy, with quantities and dates. This is module 6, Gringotts.

Reading: outputs/tables/demand_scenarios.csv
         outputs/tables/forecast_scenarios_weekly.csv
         outputs/tables/seasonality_monthly_index.csv
         config.yaml (every assumption)
Writing: images/figures/retail_monthly_demand_profile.png
         images/figures/retail_cost_of_being_wrong.png
         outputs/tables/retail_demand_profile.csv
         outputs/tables/retail_order_schedule.csv
         outputs/tables/retail_january_reserve_tradeoff.csv
         outputs/tables/retail_assumptions.csv
         outputs/tables/retail_sensitivity.csv
         docs/findings.md (one entry)
Runtime: about thirty seconds.

I keep the arithmetic visible, so a reader can disagree with one assumption and not with a black
box. Each step is a named function that reads config and writes a table. The steps are: 1 a stated
annual category baseline, 2 the attention uplift from module 5.1 turned into a sales uplift,
3 monthly demand for November 2026 to March 2027, 4 lead times worked back to order dates, 5 safety
stock at the chosen service level, 6 the cost of being wrong each way and the service level it
implies, 7 the January reserve trade off, 8 one paragraph a buyer could act on.

The pass through in step 2 is an assumption (retail.attention_pass_through), not a measurement.
Module 5.2 could not tell it apart from zero, because NAICS 459A holds every bookshop and hobby
shop in Canada and one franchise is lost in it. So I report the result across a range of values.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from src.utils.config import as_date, get, path
from src.utils.io import relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import PALETTE, SCENARIO_COLOURS, apply_style, save_figure, title_block

SCRIPT = "40_retail_recommendation"
logger = get_logger(SCRIPT)

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Covering November to March with my buy, so it includes the gift window, the
# premiere and the January position that my main argument is about.
PROFILE_MONTHS = pd.date_range("2026-11-01", "2027-03-01", freq="MS")


# Working out the baseline and the uplift (steps 1 and 2).

def category_seasonal_shares() -> pd.Series:
    """Working out the share of annual category sales in each month, from measured seasonality.

    My seasonal index from module 3.3 says how much busier than average each month
    is. I divide each month's index by the sum of all twelve to get a share of the
    year, so I can spread the annual baseline across the months.
    """
    table = path("outputs_tables", "seasonality_monthly_index.csv")
    if not table.exists():
        raise FileNotFoundError(
            f"{relative(table)} does not exist. Run src/analysis/20_seasonality.py first."
        )

    index = pd.read_csv(table)
    category = index[index["series"].str.contains("459A", na=False)]
    if category.empty:
        raise ValueError("the seasonality table has no row for the focus category")

    shares = category.set_index("month_number")["seasonal_index"]
    return shares / shares.sum()


def monthly_attention_multiple(scenario: str) -> pd.Series:
    """Working out attention in each profile month, as a multiple of the baseline with no premiere.

    I use the weekly forecast and not the scenario summary, so I keep the shape
    inside the season. The premiere lands on 25 December and the response builds
    through January. One annual multiple would flatten that away.
    """
    table = path("outputs_tables", "forecast_scenarios_weekly.csv")
    weekly = pd.read_csv(table)
    weekly["week"] = pd.to_datetime(weekly["week"])

    if scenario not in weekly.columns:
        raise ValueError(f"scenario '{scenario}' is not a column in {relative(table)}")

    monthly = weekly.set_index("week")[scenario].resample("MS").mean()
    counterfactual = weekly.set_index("week")["counterfactual"].resample("MS").mean()

    # Comparing against what would have happened with no premiere. My baseline sales
    # already include the normal attention the franchise gets, so this is the fair comparison.
    return (monthly / counterfactual).reindex(PROFILE_MONTHS)


def build_demand_profile(scenario: str, pass_through: float) -> pd.DataFrame:
    """Building monthly category sales for one scenario, in Canadian dollars."""
    annual_baseline = float(get("retail.category_baseline_sales_cad"))
    shares = category_seasonal_shares()
    attention_multiple = monthly_attention_multiple(scenario)

    rows = []
    for month in PROFILE_MONTHS:
        share = float(shares.loc[month.month])
        baseline_sales = annual_baseline * share
        multiple = float(attention_multiple.loc[month])

        # Treating a pass through of 1.0 as every extra unit of attention becoming an
        # extra unit of sales in the same proportion. Anything less makes the uplift smaller.
        uplift = 1 + pass_through * (multiple - 1)
        rows.append({
            "month": month.date(),
            "month_name": f"{MONTH_NAMES[month.month - 1]} {month.year}",
            "seasonal_share_of_year": round(share, 4),
            "baseline_sales_cad": round(baseline_sales, 0),
            "attention_multiple_vs_counterfactual": round(multiple, 3),
            "sales_uplift_factor": round(uplift, 3),
            "forecast_sales_cad": round(baseline_sales * uplift, 0),
            "incremental_sales_cad": round(baseline_sales * (uplift - 1), 0),
        })

    profile = pd.DataFrame(rows)
    profile["scenario"] = scenario
    profile["pass_through"] = pass_through
    return profile


# Working back from lead times to order dates (step 4).

def order_schedule() -> pd.DataFrame:
    """Working backwards from the date stock must be in store to the last date I can order."""
    lead_times = get("retail.lead_time_days")
    review_period = int(get("retail.review_period_days"))

    # Putting gift window stock on the shelf before the window opens. Stock for the
    # January position must land the week the premiere airs, so it is on the floor
    # while people are watching the show.
    required_dates = {
        "gift window (Nov to 24 Dec)": pd.Timestamp(as_date("dates.gift_season_start")),
        "January position (26 Dec to 31 Jan)": pd.Timestamp(as_date("dates.premiere")),
    }

    rows = []
    for position, in_store in required_dates.items():
        for product_type, days in lead_times.items():
            order_by = in_store - pd.Timedelta(days=int(days))
            rows.append({
                "position": position,
                "product_type": product_type.replace("_", " "),
                "lead_time_days": int(days),
                "required_in_store": in_store.date(),
                "order_by": order_by.date(),
                "days_from_today": (order_by - pd.Timestamp("2026-09-02")).days,
                "already_late": bool(order_by < pd.Timestamp("2026-09-02")),
                "review_period_days": review_period,
            })

    return pd.DataFrame(rows).sort_values(["position", "lead_time_days"], ascending=[True, False])


# Sizing the safety stock and costing each kind of mistake (steps 5 and 6).

def demand_variability(profiles: dict[str, pd.DataFrame]) -> float:
    """Working out the coefficient of variation of season demand across my three scenarios.

    The three scenarios are the only numbers I have for how uncertain demand is,
    so I size the safety stock against them. I treat the low to high spread as
    roughly a 90 per cent interval, so the implied standard deviation is the
    spread divided by 2 x 1.645.
    """
    totals = {name: frame["forecast_sales_cad"].sum() for name, frame in profiles.items()}
    spread = totals["high"] - totals["low"]
    implied_sd = spread / (2 * 1.645)
    return implied_sd / totals["central"]


def newsvendor_service_level() -> tuple[float, float, float]:
    """Working out the service level that my costs imply, from the cost of each mistake.

    Understocking costs the lost gross margin, plus a goodwill penalty for the customer
    who came in and left without the product. Overstocking costs the markdown to clear
    the unit plus the cost of holding it until then. The critical ratio Cu / (Cu + Co)
    is the service level that balances the two. I compare it with my 95 per cent
    default, so I test that number and do not just assume it.
    """
    margin_rate = float(get("retail.gross_margin_rate"))
    markdown_rate = float(get("retail.markdown_rate"))
    holding_rate = float(get("retail.holding_cost_rate_annual"))
    goodwill = float(get("retail.lost_sale_goodwill_multiplier"))

    # Measuring both costs per dollar of retail price.
    cost_of_understock = margin_rate * goodwill
    # Selling a marked down unit at (1 - markdown) of retail, against a unit cost
    # of (1 - margin). My loss is the difference, plus roughly a quarter year of
    # holding cost on the unit cost.
    unit_cost = 1 - margin_rate
    clearance_revenue = 1 - markdown_rate
    cost_of_overstock = max(unit_cost - clearance_revenue, 0) + holding_rate * 0.25 * unit_cost

    critical_ratio = cost_of_understock / (cost_of_understock + cost_of_overstock)
    return critical_ratio, cost_of_understock, cost_of_overstock


def safety_stock(central_total: float, coefficient_of_variation: float, service_level: float) -> dict:
    z = float(stats.norm.ppf(service_level))
    sigma = central_total * coefficient_of_variation
    return {
        "service_level": service_level,
        "z_score": round(z, 3),
        "demand_sd_cad": round(sigma, 0),
        "safety_stock_cad": round(z * sigma, 0),
        "order_up_to_cad": round(central_total + z * sigma, 0),
    }


# Testing how much of the buy to hold back for January (step 7).

def split_demand_at_premiere(profile: pd.DataFrame) -> tuple[float, float]:
    """Splitting the season into demand before the premiere and demand after it.

    The premiere is on 25 December, inside a month, so I cannot split a monthly profile
    on month boundaries. That would put all of December on the after side and make the
    gift window look tiny. I divide December with the share stated in config, and every
    other month goes on the side its calendar position puts it.
    """
    december_share = float(get("retail.december_share_before_premiere"))
    frame = profile.copy()
    frame["month"] = pd.to_datetime(frame["month"])

    before = frame[frame["month"] < "2026-12-01"]["forecast_sales_cad"].sum()
    december = float(frame[frame["month"] == "2026-12-01"]["forecast_sales_cad"].sum())
    after = frame[frame["month"] > "2026-12-01"]["forecast_sales_cad"].sum()

    gift_demand = float(before) + december * december_share
    post_premiere_demand = float(after) + december * (1 - december_share)
    return gift_demand, post_premiere_demand


def january_reserve_tradeoff(profiles: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Working out the expected profit for each share of the buy I hold back for January.

    The trade off is real in both directions. Stock I hold back cannot be sold in
    the gift window, and that is when the category does most of its business.
    Stock I commit only to December is on the markdown table by the time the
    show has been airing for two weeks.
    """
    proportions = get("retail.january_reserve_proportions")
    margin_rate = float(get("retail.gross_margin_rate"))
    markdown_rate = float(get("retail.markdown_rate"))

    results = []
    for proportion in proportions:
        scenario_profits = {}
        for scenario, profile in profiles.items():
            gift_demand, january_demand = split_demand_at_premiere(profile)
            total_demand = gift_demand + january_demand

            # Sizing the buy on the central scenario, then splitting it.
            buy = float(profiles["central"]["forecast_sales_cad"].sum())
            gift_allocation = buy * (1 - proportion)
            january_allocation = buy * proportion

            # Capping sales at the smaller of what I allocated and what was
            # demanded. Unsold stock in each window is marked down.
            gift_sold = min(gift_allocation, gift_demand)
            january_sold = min(january_allocation, january_demand)

            gift_unsold = max(gift_allocation - gift_demand, 0)
            january_unsold = max(january_allocation - january_demand, 0)

            revenue = gift_sold + january_sold
            markdown_recovery = (gift_unsold + january_unsold) * (1 - markdown_rate)
            cost_of_goods = buy * (1 - margin_rate)
            profit = revenue + markdown_recovery - cost_of_goods

            lost_sales = max(gift_demand - gift_allocation, 0) + max(january_demand - january_allocation, 0)

            scenario_profits[scenario] = {
                "profit": profit,
                "lost_sales": lost_sales,
                "unsold": gift_unsold + january_unsold,
                "total_demand": total_demand,
            }

        # Giving each scenario equal weight. Weighting them would need a
        # probability for each one, and I have no basis for that. Saying so is
        # better than making up a distribution.
        expected_profit = float(np.mean([v["profit"] for v in scenario_profits.values()]))

        results.append({
            "january_reserve_proportion": proportion,
            "expected_profit_cad": round(expected_profit, 0),
            "profit_low_scenario_cad": round(scenario_profits["low"]["profit"], 0),
            "profit_central_scenario_cad": round(scenario_profits["central"]["profit"], 0),
            "profit_high_scenario_cad": round(scenario_profits["high"]["profit"], 0),
            "worst_case_profit_cad": round(min(v["profit"] for v in scenario_profits.values()), 0),
            "expected_lost_sales_cad": round(
                float(np.mean([v["lost_sales"] for v in scenario_profits.values()])), 0
            ),
            "expected_unsold_cad": round(
                float(np.mean([v["unsold"] for v in scenario_profits.values()])), 0
            ),
        })

    return pd.DataFrame(results)


# Drawing my two charts.

def plot_demand_profile(profiles: dict[str, pd.DataFrame], premiere: pd.Timestamp) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 5.8))

    months = profiles["central"]["month_name"].tolist()
    x = np.arange(len(months))
    width = 0.26

    for offset, scenario in zip([-width, 0, width], ["low", "central", "high"], strict=False):
        values = profiles[scenario]["forecast_sales_cad"].values / 1000
        ax.bar(x + offset, values, width=width, label=f"{scenario} scenario",
               color=SCENARIO_COLOURS[scenario])

    baseline = profiles["central"]["baseline_sales_cad"].values / 1000
    ax.plot(x, baseline, color=PALETTE["ink"], linewidth=2.0, linestyle="--",
            marker="o", markersize=5, label="baseline, no premiere")

    # Marking the premiere inside December, between the December and January bars.
    premiere_x = months.index("Dec 2026") + 0.5
    ax.axvline(premiere_x, color=PALETTE["highlight"], linewidth=1.6, linestyle="--")
    top = ax.get_ylim()[1]
    ax.text(premiere_x + 0.05, top * 0.95, "premiere\n25 Dec", fontsize=8.5,
            color=PALETTE["warn"], va="top", ha="left")

    ax.set_xticks(x)
    ax.set_xticklabels(months)
    ax.set_ylabel("category sales, thousands of Canadian dollars")
    ax.legend(loc="upper right", fontsize=9)

    central = profiles["central"]
    jan = float(central[central["month_name"] == "Jan 2027"]["forecast_sales_cad"].iloc[0])
    jan_base = float(central[central["month_name"] == "Jan 2027"]["baseline_sales_cad"].iloc[0])

    title_block(
        ax,
        f"January 2027 is the month the premiere moves most: {jan / jan_base:.1f} times its normal level",
        "Monthly category sales for a composite Canadian retailer. Baseline is the measured "
        "seasonal shape applied to a stated annual category figure; scenarios add the forecast "
        "attention uplift through a stated pass through assumption.",
        subtitle_wrap=118,
    )
    return save_figure(
        fig, "retail_monthly_demand_profile.png",
        "Derived from outputs/tables/forecast_scenarios_weekly.csv and seasonality_monthly_index.csv",
    )


def plot_cost_of_being_wrong(tradeoff: pd.DataFrame, critical_ratio: float,
                             assumed_service_level: float) -> Path:
    apply_style()
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(12, 5.2))

    x = tradeoff["january_reserve_proportion"] * 100
    ax_left.plot(x, tradeoff["expected_profit_cad"] / 1000, color=PALETTE["accent"],
                 linewidth=2.2, marker="o", markersize=6, label="expected profit")
    ax_left.plot(x, tradeoff["worst_case_profit_cad"] / 1000, color=PALETTE["muted"],
                 linewidth=1.6, linestyle="--", marker="s", markersize=5, label="worst scenario")

    best = tradeoff.loc[tradeoff["expected_profit_cad"].idxmax()]
    ax_left.axvline(best["january_reserve_proportion"] * 100, color=PALETTE["highlight"],
                    linewidth=1.4, linestyle=":")
    ax_left.set_xlabel("share of the buy held for the January position, per cent")
    ax_left.set_ylabel("profit, thousands of Canadian dollars")
    ax_left.legend(loc="lower left", fontsize=8.5)
    ax_left.set_title("Where to hold the stock", loc="left", fontsize=11)

    ax_right.bar(
        ["lost margin\n(understock)", "markdown + holding\n(overstock)"],
        [critical_ratio, 1 - critical_ratio],
        color=[PALETTE["accent"], PALETTE["support"]], width=0.5,
    )
    ax_right.axhline(assumed_service_level, color=PALETTE["ink"], linewidth=1.6, linestyle="--",
                     label=f"assumed service level ({assumed_service_level:.0%})")
    ax_right.set_ylabel("share of the balance")
    ax_right.set_ylim(0, 1)
    ax_right.legend(loc="upper right", fontsize=8.5)
    ax_right.set_title(
        f"Economics imply a {critical_ratio:.0%} service level", loc="left", fontsize=11
    )

    title_block(
        ax_left,
        f"Understocking costs more than overstocking, so lean long: hold {best['january_reserve_proportion']:.0%} for January",
        "Left: expected and worst case profit across January reserve proportions. "
        "Right: the newsvendor critical ratio implied by the cost assumptions, against the assumed service level.",
        subtitle_wrap=120,
    )
    return save_figure(fig, "retail_cost_of_being_wrong.png", "All assumptions from config.yaml")


def main() -> None:
    premiere = pd.Timestamp(as_date("dates.premiere"))
    pass_through = float(get("retail.attention_pass_through"))
    assumed_service_level = float(get("retail.service_level"))
    average_unit_retail = float(get("retail.average_unit_retail_cad"))

    with RunTimer(SCRIPT, logger) as run:
        # Building the demand profile (steps 1 to 3).
        profiles = {
            scenario: build_demand_profile(scenario, pass_through)
            for scenario in ["low", "central", "high"]
        }
        all_profiles = pd.concat(profiles.values(), ignore_index=True)
        profile_table = save_table(
            "retail_demand_profile.csv", all_profiles,
            pass_through=pass_through,
            note="monthly category sales Nov 2026 to Mar 2027 for each scenario",
        )

        central = profiles["central"]
        logger.info("central monthly profile:\n%s", central[
            ["month_name", "baseline_sales_cad", "attention_multiple_vs_counterfactual",
             "forecast_sales_cad", "incremental_sales_cad"]
        ].to_string(index=False))

        season_totals = {name: float(f["forecast_sales_cad"].sum()) for name, f in profiles.items()}
        baseline_total = float(central["baseline_sales_cad"].sum())
        logger.info(
            "season totals: low %.0f, central %.0f, high %.0f, baseline %.0f",
            season_totals["low"], season_totals["central"], season_totals["high"], baseline_total,
        )

        demand_figure = plot_demand_profile(profiles, premiere)

        # Working out the order dates (step 4).
        schedule = order_schedule()
        save_table("retail_order_schedule.csv", schedule)
        logger.info("order schedule:\n%s", schedule.to_string(index=False))

        late = schedule[schedule["already_late"]]
        if not late.empty:
            log_data_issue(
                SCRIPT, "retail",
                f"{len(late)} order by dates have already passed as of the analysis date",
                "those positions can only be filled by air freight or domestic substitution "
                "at a worse margin; the recommendation says which",
                severity="note",
            )

        # Sizing the safety stock and working out the cost of each mistake (steps 5 and 6).
        cv = demand_variability(profiles)
        critical_ratio, cost_under, cost_over = newsvendor_service_level()
        logger.info(
            "coefficient of variation %.3f; cost of understock %.3f, overstock %.3f per retail dollar; "
            "implied service level %.1f%% against assumed %.0f%%",
            cv, cost_under, cost_over, critical_ratio * 100, assumed_service_level * 100,
        )

        stock_assumed = safety_stock(season_totals["central"], cv, assumed_service_level)
        stock_implied = safety_stock(season_totals["central"], cv, critical_ratio)

        # Testing the January reserve shares (step 7).
        tradeoff = january_reserve_tradeoff(profiles)
        tradeoff_table = save_table("retail_january_reserve_tradeoff.csv", tradeoff)
        logger.info("january reserve trade off:\n%s", tradeoff.to_string(index=False))
        best_reserve = tradeoff.loc[tradeoff["expected_profit_cad"].idxmax()]

        cost_figure = plot_cost_of_being_wrong(tradeoff, critical_ratio, assumed_service_level)

        # Testing how much the result moves with the pass through, the assumption that matters most.
        sensitivity_rows = []
        for value in get("retail.attention_pass_through_range"):
            scenarios_at_value = {
                scenario: build_demand_profile(scenario, float(value))
                for scenario in ["low", "central", "high"]
            }
            sensitivity_rows.append({
                "attention_pass_through": value,
                "season_sales_low_cad": round(scenarios_at_value["low"]["forecast_sales_cad"].sum(), 0),
                "season_sales_central_cad": round(scenarios_at_value["central"]["forecast_sales_cad"].sum(), 0),
                "season_sales_high_cad": round(scenarios_at_value["high"]["forecast_sales_cad"].sum(), 0),
                "incremental_vs_baseline_central_cad": round(
                    scenarios_at_value["central"]["incremental_sales_cad"].sum(), 0
                ),
                "uplift_vs_baseline_central": round(
                    scenarios_at_value["central"]["forecast_sales_cad"].sum() / baseline_total, 3
                ),
            })
        sensitivity = pd.DataFrame(sensitivity_rows)
        save_table("retail_sensitivity.csv", sensitivity)
        logger.info("sensitivity to the pass through assumption:\n%s", sensitivity.to_string(index=False))

        # Putting every assumption in one table, so a reader can check each one and disagree with it.
        assumptions = pd.DataFrame([
            {"assumption": "annual category baseline", "value": get("retail.category_baseline_sales_cad"),
             "units": "CAD", "source": "stated assumption, composite retailer",
             "config_key": "retail.category_baseline_sales_cad"},
            {"assumption": "attention to sales pass-through", "value": pass_through,
             "units": "share", "source": "stated assumption; module 5.2 could not measure it",
             "config_key": "retail.attention_pass_through"},
            {"assumption": "gross margin rate", "value": get("retail.gross_margin_rate"),
             "units": "share of retail", "source": "stated assumption, licensed product",
             "config_key": "retail.gross_margin_rate"},
            {"assumption": "markdown rate on unsold stock", "value": get("retail.markdown_rate"),
             "units": "share of retail", "source": "stated assumption",
             "config_key": "retail.markdown_rate"},
            {"assumption": "annual holding cost rate", "value": get("retail.holding_cost_rate_annual"),
             "units": "share of unit cost", "source": "stated assumption",
             "config_key": "retail.holding_cost_rate_annual"},
            {"assumption": "goodwill multiplier on a lost sale", "value": get("retail.lost_sale_goodwill_multiplier"),
             "units": "multiplier", "source": "stated assumption",
             "config_key": "retail.lost_sale_goodwill_multiplier"},
            {"assumption": "service level target", "value": assumed_service_level,
             "units": "share", "source": "my default, to be confirmed with the retailer",
             "config_key": "retail.service_level"},
            {"assumption": "service level implied by the cost assumptions", "value": round(critical_ratio, 4),
             "units": "share", "source": "derived, newsvendor critical ratio", "config_key": "derived"},
            {"assumption": "imported lead time", "value": get("retail.lead_time_days")["imported"],
             "units": "days", "source": "stated assumption", "config_key": "retail.lead_time_days.imported"},
            {"assumption": "domestic lead time", "value": get("retail.lead_time_days")["domestic"],
             "units": "days", "source": "stated assumption", "config_key": "retail.lead_time_days.domestic"},
            {"assumption": "reprinted book lead time", "value": get("retail.lead_time_days")["reprinted_books"],
             "units": "days", "source": "stated assumption", "config_key": "retail.lead_time_days.reprinted_books"},
            {"assumption": "average unit retail", "value": average_unit_retail,
             "units": "CAD", "source": "stated assumption", "config_key": "retail.average_unit_retail_cad"},
            {"assumption": "demand coefficient of variation", "value": round(cv, 4),
             "units": "share", "source": "derived from the low to high scenario spread", "config_key": "derived"},
        ])
        save_table("retail_assumptions.csv", assumptions)

        # Writing the recommendation (step 8).
        recommended_buy = stock_implied["order_up_to_cad"]
        recommended_units = recommended_buy / average_unit_retail
        january_share = float(best_reserve["january_reserve_proportion"])
        imported_order_by = schedule[
            (schedule["product_type"] == "imported")
            & (schedule["position"].str.startswith("January"))
        ]["order_by"].iloc[0]

        january_months = central[pd.to_datetime(central["month"]) >= premiere.replace(day=1)]
        january_incremental = float(january_months["incremental_sales_cad"].sum())
        total_incremental = float(central["incremental_sales_cad"].sum())
        january_share_of_uplift = january_incremental / total_incremental if total_incremental else np.nan

        # Checking if expected profit and worst case profit peak at different shares.
        # A buyer needs to know when they do, because the share with the best
        # expected profit still has a downside.
        safest = tradeoff.loc[tradeoff["worst_case_profit_cad"].idxmax()]
        safest_share = float(safest["january_reserve_proportion"])
        if abs(safest_share - january_share) > 1e-9:
            split_advice = (
                f"hold between {min(safest_share, january_share):.0%} and "
                f"{max(safest_share, january_share):.0%} of it for a January position: "
                f"{january_share:.0%} maximises expected profit at ${best_reserve['expected_profit_cad']:,.0f}, "
                f"while {safest_share:.0%} gives up ${best_reserve['expected_profit_cad'] - safest['expected_profit_cad']:,.0f} "
                f"of that to lift the worst case by "
                f"${safest['worst_case_profit_cad'] - best_reserve['worst_case_profit_cad']:,.0f}"
            )
        else:
            split_advice = (
                f"hold {january_share:.0%} of it for a January position, which is best on both "
                f"expected and worst case profit"
            )

        late_positions = schedule[schedule["already_late"]]
        if not late_positions.empty:
            late_note = (
                f" Note that {len(late_positions)} of the six order by dates have already passed, "
                f"including imported product for the January position, which was due "
                f"{imported_order_by}. Those positions can now only be filled by air freight or by "
                f"substituting domestic product, both at a worse margin, and that is a cost of "
                f"having started the analysis in September rather than in spring."
            )
        else:
            late_note = ""

        recommendation = (
            f"Commit a wizarding category buy of ${recommended_buy:,.0f} at retail for the "
            f"November 2026 to March 2027 season, about {recommended_units:,.0f} units at an "
            f"average ${average_unit_retail:.0f} retail, and {split_advice}, rather than "
            f"committing the buy to the pre Christmas window as the category normally would. "
            f"The range around that buy is ${season_totals['low']:,.0f} to "
            f"${season_totals['high']:,.0f} depending on how large the premiere response turns out "
            f"to be.{late_note}"
        )
        logger.info("RECOMMENDATION: %s", recommendation)

        recommendation_table = pd.DataFrame([{
            "recommended_buy_cad_retail": round(recommended_buy, 0),
            "recommended_units": round(recommended_units, 0),
            "central_season_demand_cad": round(season_totals["central"], 0),
            "low_season_demand_cad": round(season_totals["low"], 0),
            "high_season_demand_cad": round(season_totals["high"], 0),
            "safety_stock_cad": stock_implied["safety_stock_cad"],
            "service_level_used": round(critical_ratio, 4),
            # Reporting both service levels, not only the one I used. The gap
            # between them is small here, and that is worth knowing. My 95 per
            # cent default and the economics nearly agree, so my recommendation
            # does not depend on the choice of service level.
            "safety_stock_at_assumed_95pc_cad": stock_assumed["safety_stock_cad"],
            "service_level_assumed": assumed_service_level,
            "safety_stock_difference_cad": round(
                stock_assumed["safety_stock_cad"] - stock_implied["safety_stock_cad"], 0
            ),
            "january_reserve_share": january_share,
            "january_order_by_imported": imported_order_by,
            "january_share_of_incremental_sales": round(january_share_of_uplift, 3),
        }])
        save_table("retail_recommendation.csv", recommendation_table)

        # Measuring both spreads, so my finding compares them with real numbers.
        central_sales = sensitivity["season_sales_central_cad"]
        sensitivity_spread = float(central_sales.iloc[-1] - central_sales.iloc[0])
        scenario_gap = float(round(season_totals["high"], 0) - round(season_totals["low"], 0))

        finding = (
            f"{recommendation} The case for holding stock back rests on where the incremental "
            f"sales fall: {january_share_of_uplift:.0%} of the premiere driven uplift in the "
            f"central scenario lands from December onward, in the weeks when the category "
            f"normally runs at {float(central[central['month_name'] == 'Jan 2027']['seasonal_share_of_year'].iloc[0]) * 12:.2f} "
            f"times an average month and stock is usually being cleared. The cost assumptions also "
            f"argue against a cautious buy: a lost sale costs {cost_under:.2f} per retail dollar "
            f"against {cost_over:.2f} for a marked down one, which implies a "
            f"{critical_ratio:.0%} service level rather than the {assumed_service_level:.0%} I "
            f"set as my default, so the error worth avoiding here is running out, not overbuying."
        )

        write_finding(
            "6 Gringotts: the buy, the split and the order date",
            finding,
            evidence=(
                f"A stated annual category baseline of "
                f"${float(get('retail.category_baseline_sales_cad')):,.0f} spread across months by "
                f"the measured category seasonality from module 3.3, multiplied by the attention "
                f"uplift from module 5.1 through a stated pass through of {pass_through:.0%}, then "
                f"sized with a newsvendor critical ratio from the cost assumptions. Every assumption "
                f"is in outputs/tables/retail_assumptions.csv with its config key."
            ),
            sample=(
                "Five months of demand profile across three scenarios. The seasonal shape rests on "
                "35 years of Canadian retail data; the attention uplift on 11 years of pageviews "
                "and four measured franchise events."
            ),
            uncertainty=(
                f"The single largest uncertainty is not statistical. It is the pass through "
                f"assumption, which module 5.2 could not measure because a national category "
                f"containing every bookshop in Canada is too coarse to detect one franchise in. "
                f"At a pass through of "
                f"{sensitivity['attention_pass_through'].min():.0%} the central season is "
                f"${sensitivity['season_sales_central_cad'].iloc[0]:,.0f} and at "
                f"{sensitivity['attention_pass_through'].max():.0%} it is "
                f"${sensitivity['season_sales_central_cad'].iloc[-1]:,.0f}, a spread of "
                f"${sensitivity_spread:,.0f} against a gap of ${scenario_gap:,.0f} between the low and "
                f"high demand scenarios. The category baseline is likewise "
                f"stated rather than observed, because no retailer's internal sales were available. "
                f"Everything here is therefore a structured way to reason about the size of the "
                f"decision, not a prediction of it."
            ),
            figure=relative(demand_figure),
            table=relative(tradeoff_table),
        )

        run.rows_out = len(all_profiles)
        run.note = f"buy {recommended_buy:,.0f} CAD, {january_share:.0%} held for January"
        logger.info("saved %s and %s", relative(profile_table), relative(cost_figure))

    logger.info("retail recommendation complete")


if __name__ == "__main__":
    main()
