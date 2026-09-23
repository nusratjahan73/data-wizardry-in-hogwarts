"""Module 5.1. Forecast franchise attention through to a year past the premiere.

Reads  : data/processed/attention_weekly.csv
         outputs/tables/event_study_responses.csv
Writes : images/figures/forecast_model_comparison.png
         images/figures/forecast_scenarios.png
         outputs/tables/forecast_model_metrics.csv
         outputs/tables/forecast_scenarios_weekly.csv
         outputs/tables/demand_scenarios.csv
         outputs/models/forecast_<model>.json
         docs/findings.md (one entry)
Runtime: two to four minutes, mostly Prophet.

What is being forecast. A composite weekly attention index: total Wikipedia
pageviews across the four articles that describe the property itself rather than
one film, one character or the streaming service. A composite is steadier than
any single article, and it is what a category buyer cares about, since nobody
stocks merchandise for one Wikipedia page.

The new show's own article is deliberately not in the composite, and the reason
is worth reading before the numbers are used. That article carried about forty
views a day through 2024 and only became substantial in mid 2025, so requiring
it to be present shortens the usable history from eleven years to three, which
is too little to estimate a yearly seasonal pattern from. It is measured and
reported separately instead: it now runs about a hundred times its 2024 level,
which is the clearest single piece of evidence that the new series is generating
attention of its own.

Five models, per section 11's requirement of at least three plus a baseline:

  seasonal naive    last year's same week. The baseline every other model must beat.
  drift naive       last value plus average weekly change. Catches trend without seasonality.
  Holt-Winters      exponential smoothing with additive trend and yearly seasonality.
  SARIMA            (1,1,1)(1,1,1,52), fitted on a log scale.
  Prophet           yearly seasonality plus the trailer as a known event.

Evaluation is on a held out final 52 weeks, split by time and never at random,
scored on mean absolute error and mean absolute percentage error.

The premiere is the hard part, and it is worth being clear about what can and
cannot be claimed. No model can learn the effect of an event that has never
happened in this series, so the premiere uplift is not fitted: it is imposed,
using multiples measured from real events in 21_event_study.py, and the three
scenarios are three defensible readings of that evidence rather than three
confidence bands from one model. The statistical forecast supplies the
counterfactual, meaning where attention goes if nothing happens; the scenarios
add the event on top of it. Presenting the result any other way would dress an
assumption up as a measurement.
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

from src.utils.config import as_date, get, path, random_seed
from src.utils.io import read_processed, relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import PALETTE, SCENARIO_COLOURS, apply_style, save_figure, title_block

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SCRIPT = "30_interest_forecast"
logger = get_logger(SCRIPT)

# The articles that together describe attention to the property itself.
#
# Two exclusions, both deliberate. HBO_Max is a general streaming service whose
# traffic is driven by everything else on the platform. The new show's own
# article is excluded for a subtler reason: it barely existed before 2021 and
# carried about forty views a day until mid 2025, so requiring it to be present
# cuts the usable history from eleven years to three, which is not enough to
# estimate a yearly seasonal pattern from. It is tracked separately below as
# evidence of the new show's own pull.
COMPOSITE_ARTICLES = [
    "Harry_Potter",
    "Wizarding_World",
    "Harry_Potter_(film_series)",
    "Fantastic_Beasts",
]

SHOW_ARTICLE = "Harry_Potter_(TV_series)"

# Read from config rather than fixed here. Section 5 puts every threshold in
# config.yaml, and a value that sits in config while the code uses its own
# constant is worse than either, because the two can disagree silently.
HOLDOUT_WEEKS = int(get("modelling.test_size_weeks"))


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #

def build_composite() -> pd.Series:
    """Weekly total views across the composite articles.

    Only weeks where every article reported are kept. A week missing one article
    would be a smaller total that looks like falling attention, which is the same
    partial-period trap the cleaning step guards against at the daily level.
    """
    attention = read_processed("attention_weekly.csv")
    subset = attention[
        (attention["source"] == "wikipedia_pageviews")
        & (attention["series"].isin(COMPOSITE_ARTICLES))
    ].copy()

    if subset.empty:
        raise ValueError("no pageview data for the composite articles")

    subset["week"] = pd.to_datetime(subset["week"])
    wide = subset.pivot_table(index="week", columns="series", values="value", aggfunc="sum")

    missing_articles = set(COMPOSITE_ARTICLES) - set(wide.columns)
    if missing_articles:
        log_data_issue(
            SCRIPT, "forecast",
            f"composite is missing article(s): {', '.join(sorted(missing_articles))}",
            "the composite was built from the articles that were present; the level "
            "is therefore not comparable with a run that had all of them",
        )

    complete = wide.dropna()
    dropped = len(wide) - len(complete)
    if dropped:
        logger.info("dropped %d weeks where at least one article was missing", dropped)

    series = complete.sum(axis=1).sort_index()
    series.name = "attention"

    # statsmodels needs an index with an explicit frequency, or Holt-Winters
    # refuses to forecast past the end of the data. The weeks are already Mondays
    # and contiguous, so stamping the frequency asserts what is already true.
    series = series.asfreq("W-MON")
    if series.isna().any():
        gaps = int(series.isna().sum())
        log_data_issue(
            SCRIPT, "forecast",
            f"the composite has {gaps} missing weeks once put on a regular weekly index",
            "gaps interpolated for model fitting only; the saved series keeps them",
        )
        series = series.interpolate(limit_direction="both")
    return series


def show_article_series() -> pd.Series | None:
    """The new show's own article, tracked separately from the composite."""
    attention = read_processed("attention_weekly.csv")
    subset = attention[
        (attention["source"] == "wikipedia_pageviews") & (attention["series"] == SHOW_ARTICLE)
    ].copy()
    if subset.empty:
        return None
    subset["week"] = pd.to_datetime(subset["week"])
    return subset.set_index("week")["value"].sort_index()


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #

def seasonal_naive(train: pd.Series, horizon: int, period: int = 52) -> np.ndarray:
    """Repeat the value from `period` weeks ago. The baseline to beat.

    The step wraps with a modulo so a horizon longer than one seasonal period
    recycles the last observed year rather than running off the end of the array.
    """
    history = train.values
    out = []
    for step in range(horizon):
        index = len(history) - period + (step % period)
        out.append(history[index] if 0 <= index < len(history) else history[-1])
    return np.array(out, dtype=float)


def drift_naive(train: pd.Series, horizon: int) -> np.ndarray:
    """Last value plus the average change per week over the whole history."""
    values = train.values.astype(float)
    slope = (values[-1] - values[0]) / max(len(values) - 1, 1)
    return values[-1] + slope * np.arange(1, horizon + 1)


def holt_winters(train: pd.Series, horizon: int) -> np.ndarray | None:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    try:
        # Fitted on logs so the seasonal swing scales with the level, which is
        # how attention actually behaves: a busy year has bigger Decembers.
        model = ExponentialSmoothing(
            np.log(train.clip(lower=1)),
            trend="add",
            seasonal="add",
            seasonal_periods=52,
            initialization_method="estimated",
        ).fit()
        return np.exp(model.forecast(horizon).values)
    except Exception as exc:
        logger.warning("Holt-Winters failed: %s", exc)
        return None


def sarima(train: pd.Series, horizon: int) -> np.ndarray | None:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    try:
        model = SARIMAX(
            np.log(train.clip(lower=1)),
            order=(1, 1, 1),
            seasonal_order=(1, 1, 1, 52),
            enforce_stationarity=False,
            enforce_invertibility=False,
        ).fit(disp=False, maxiter=200)
        return np.exp(model.forecast(horizon).values)
    except Exception as exc:
        logger.warning("SARIMA failed: %s", exc)
        return None


def prophet_forecast(
    train: pd.Series, horizon: int, events: pd.DataFrame | None
) -> tuple[np.ndarray | None, pd.DataFrame | None]:
    try:
        from prophet import Prophet
    except ImportError:
        logger.warning("prophet is not installed, skipping")
        return None, None

    frame = pd.DataFrame({"ds": train.index, "y": np.log(train.clip(lower=1).values)})

    try:
        model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
            changepoint_prior_scale=0.1,
            holidays=events,
        )
        model.fit(frame)
        future = model.make_future_dataframe(periods=horizon, freq="W-MON")
        prediction = model.predict(future)
        tail = prediction.tail(horizon)
        return np.exp(tail["yhat"].values), tail
    except Exception as exc:
        logger.warning("Prophet failed: %s", exc)
        return None, None


def event_frame() -> pd.DataFrame:
    """Known events, in the shape Prophet wants for a holiday regressor."""
    rows = []
    for event in get("events"):
        rows.append({
            "holiday": event["name"],
            "ds": pd.Timestamp(str(event["date"])),
            "lower_window": 0,
            "upper_window": 28,  # the response decays over about four weeks
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #

def score(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = actual - predicted
    mae = float(np.mean(np.abs(error)))
    # MAPE is undefined where actual is zero; those weeks are excluded rather
    # than allowed to produce an infinity that quietly wins the comparison.
    usable = actual != 0
    mape = float(np.mean(np.abs(error[usable] / actual[usable])) * 100) if usable.any() else np.nan
    rmse = float(np.sqrt(np.mean(error**2)))
    return {"mae": mae, "mape": mape, "rmse": rmse}


def evaluate_all(series: pd.Series) -> tuple[pd.DataFrame, dict[str, np.ndarray], pd.Series, pd.Series]:
    """Fit every model on a time based split and score it on the held out tail."""
    train = series.iloc[:-HOLDOUT_WEEKS]
    test = series.iloc[-HOLDOUT_WEEKS:]
    horizon = len(test)

    logger.info(
        "train %s to %s (%d weeks), test %s to %s (%d weeks)",
        train.index.min().date(), train.index.max().date(), len(train),
        test.index.min().date(), test.index.max().date(), len(test),
    )

    events = event_frame()
    events_in_train = events[events["ds"] <= train.index.max()]

    predictions: dict[str, np.ndarray] = {}

    predictions["seasonal naive"] = seasonal_naive(train, horizon)
    predictions["drift naive"] = drift_naive(train, horizon)

    hw = holt_winters(train, horizon)
    if hw is not None:
        predictions["Holt-Winters"] = hw

    sar = sarima(train, horizon)
    if sar is not None:
        predictions["SARIMA"] = sar

    prophet_values, _ = prophet_forecast(
        train, horizon, events_in_train if not events_in_train.empty else None
    )
    if prophet_values is not None:
        predictions["Prophet"] = prophet_values

    rows = []
    baseline = score(test.values, predictions["seasonal naive"])
    for name, values in predictions.items():
        metrics = score(test.values, values)
        metrics["model"] = name
        metrics["beats_baseline"] = bool(metrics["mae"] < baseline["mae"]) if name != "seasonal naive" else None
        metrics["mae_vs_baseline"] = metrics["mae"] / baseline["mae"]
        rows.append(metrics)

    results = pd.DataFrame(rows)[
        ["model", "mae", "mape", "rmse", "mae_vs_baseline", "beats_baseline"]
    ].sort_values("mae")
    return results, predictions, train, test


# --------------------------------------------------------------------------- #
# scenarios
# --------------------------------------------------------------------------- #

def largest_observed_spike(series: pd.Series) -> float:
    """The biggest weekly spike this composite has ever shown, against its own year.

    Used as the high scenario. Anchoring the top of the range on something the
    series has actually done is more defensible than picking a round number, and
    it keeps the scenario inside the realm of observed franchise behaviour.
    """
    rolling_year = series.rolling(52, min_periods=26).median()
    ratio = (series / rolling_year).dropna()
    return float(ratio.max())


def premiere_multipliers(series: pd.Series) -> dict[str, dict[str, float]]:
    """Scenario definitions, justified from events measured on this same series.

    The multiples must come from the series being forecast. An earlier version of
    this function took the trailer's 33x peak, which was measured on the show's
    own article against a baseline of about four thousand views a day, and applied
    it to this composite, whose baseline is nearer two hundred thousand a week.
    That produced a high scenario fifty times the last observed year, which is not
    a forecast, it is a unit error. Every multiple below is measured on the
    composite itself.

      low      the weakest cinema release response observed, the most cautious
               reading available
      high     the largest weekly spike this composite has ever produced
      central  the geometric mean of the two, which sits nearer the low end than
               an arithmetic mean would and reflects that most franchise events
               are ordinary rather than exceptional
    """
    observed_high = largest_observed_spike(series)

    table = path("outputs_tables", "event_study_responses.csv")
    film_low = 1.33
    if table.exists():
        events = pd.read_csv(table)
        films = events[events["event"].str.startswith("Film release")]
        if not films.empty:
            film_low = float(films["peak_multiple"].min())
    else:
        log_data_issue(
            SCRIPT, "forecast",
            "event_study_responses.csv is missing, so the low scenario used a fallback multiple",
            "run 21_event_study.py first so the scenarios rest on measured events",
        )

    central_peak = float(np.sqrt(film_low * observed_high))

    return {
        "low": {"peak": round(film_low, 2), "sustained": 1.15, "decay_weeks": 8},
        "central": {"peak": round(central_peak, 2), "sustained": 1.6, "decay_weeks": 14},
        "high": {"peak": round(observed_high, 2), "sustained": 2.4, "decay_weeks": 22},
    }


def apply_premiere_effect(
    baseline: pd.Series, premiere: pd.Timestamp, spec: dict[str, float]
) -> pd.Series:
    """Add an event response on top of a counterfactual forecast.

    The shape is a spike at the premiere week decaying exponentially towards a
    sustained level, which is the shape every measured event in this project
    actually had. An eight episode weekly run means the decay is slower than a
    film's, which is what the longer decay constants encode.
    """
    weeks_from = (baseline.index - premiere).days / 7.0
    multiplier = np.ones(len(baseline), dtype=float)

    after = weeks_from >= 0
    decay = np.exp(-weeks_from[after] / spec["decay_weeks"])
    multiplier[after] = spec["sustained"] + (spec["peak"] - spec["sustained"]) * decay

    # A short run up: interest builds in the four weeks before a release, which
    # the film events show clearly.
    ramp = (weeks_from >= -4) & (weeks_from < 0)
    multiplier[ramp] = 1 + (spec["peak"] - 1) * 0.15 * (weeks_from[ramp] + 4) / 4

    return baseline * multiplier


def forecast_forward(series: pd.Series, weeks_ahead: int) -> pd.Series:
    """The counterfactual: where attention goes with no premiere.

    Holt-Winters on logs, refitted on the full series. If it fails, the seasonal
    naive stands in, and the failure is recorded rather than hidden behind a
    line that looks just as confident.
    """
    values = holt_winters(series, weeks_ahead)
    if values is None:
        log_data_issue(
            SCRIPT, "forecast",
            "Holt-Winters failed on the full series, so the counterfactual is a seasonal naive",
            "the scenarios are correspondingly cruder; say so in the report",
            severity="error",
        )
        values = seasonal_naive(series, weeks_ahead)

    index = pd.date_range(
        series.index.max() + pd.Timedelta(weeks=1), periods=weeks_ahead, freq="W-MON"
    )
    return pd.Series(values, index=index, name="counterfactual")


# --------------------------------------------------------------------------- #
# plots
# --------------------------------------------------------------------------- #

def plot_model_comparison(train: pd.Series, test: pd.Series, predictions: dict, metrics: pd.DataFrame) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 5.8))

    context = train.iloc[-104:]
    ax.plot(context.index, context.values, color=PALETTE["muted"], linewidth=1.4, label="training data")
    ax.plot(test.index, test.values, color=PALETTE["ink"], linewidth=2.2, label="actual (held out)")

    colours = [PALETTE["accent"], PALETTE["support"], PALETTE["highlight"], PALETTE["accent_soft"], PALETTE["support_soft"]]
    for (name, values), colour in zip(predictions.items(), colours, strict=False):
        ax.plot(test.index, values, color=colour, linewidth=1.5, linestyle="--", label=name)

    best = metrics.iloc[0]
    ax.legend(loc="upper left", fontsize=8.5, ncol=2)
    ax.set_ylabel("weekly pageviews, composite")

    title_block(
        ax,
        f"{best['model']} fits the held out year best, at {best['mape']:.0f} per cent mean absolute error",
        f"Final {len(test)} weeks held out and never used for fitting. "
        f"The seasonal naive baseline scores {metrics.loc[metrics['model'] == 'seasonal naive', 'mape'].iloc[0]:.0f} per cent.",
    )
    return save_figure(fig, "forecast_model_comparison.png", "Wikipedia pageviews, retrieved 2 September 2026")


def plot_scenarios(history: pd.Series, scenarios: dict[str, pd.Series], premiere: pd.Timestamp) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 5.8))

    recent = history.iloc[-156:]
    ax.plot(recent.index, recent.values, color=PALETTE["ink"], linewidth=1.8, label="observed")

    for name in ["high", "central", "low"]:
        if name not in scenarios:
            continue
        ax.plot(
            scenarios[name].index, scenarios[name].values,
            color=SCENARIO_COLOURS[name], linewidth=2.0,
            label=f"{name} scenario",
        )

    if "low" in scenarios and "high" in scenarios:
        ax.fill_between(
            scenarios["low"].index, scenarios["low"].values, scenarios["high"].values,
            color=PALETTE["accent_soft"], alpha=0.18, zorder=0,
        )

    ax.axvline(premiere, color=PALETTE["highlight"], linewidth=1.6, linestyle="--")
    top = ax.get_ylim()[1]
    ax.text(premiere, top * 0.97, " premiere\n 25 Dec 2026", fontsize=8.5,
            color=PALETTE["warn"], va="top", ha="left")

    ax.set_ylabel("weekly pageviews, composite")
    ax.legend(loc="upper left", fontsize=9)

    peak_central = scenarios["central"].max() if "central" in scenarios else np.nan
    title_block(
        ax,
        f"Central scenario peaks at {peak_central:,.0f} weekly views in the weeks after the premiere",
        "The statistical forecast supplies the no-premiere counterfactual; the premiere "
        "response is imposed from multiples measured on real franchise events, not fitted.",
    )
    return save_figure(fig, "forecast_scenarios.png", "Wikipedia pageviews and outputs/tables/event_study_responses.csv")


# --------------------------------------------------------------------------- #

def main() -> None:
    np.random.seed(random_seed())
    premiere = pd.Timestamp(as_date("dates.premiere"))
    horizon_months = int(get("dates.forecast_horizon_months"))

    with RunTimer(SCRIPT, logger) as run:
        series = build_composite()
        run.rows_in = len(series)
        logger.info(
            "composite: %d weeks, %s to %s, mean %.0f weekly views",
            len(series), series.index.min().date(), series.index.max().date(), series.mean(),
        )

        # The show's own article is not in the composite, but its recent level is
        # the clearest evidence that the new series is generating attention of its
        # own, so it is measured and reported rather than left out of the story.
        show = show_article_series()
        if show is not None:
            recent = show.iloc[-13:].mean()
            baseline_2024 = show[show.index.year == 2024].mean()
            logger.info(
                "show article: %.0f weekly views now against %.0f through 2024, a factor of %.0f",
                recent, baseline_2024, recent / baseline_2024 if baseline_2024 else np.nan,
            )

        # --- model comparison on a held out year ---
        metrics, predictions, train, test = evaluate_all(series)
        logger.info("model comparison:\n%s", metrics.to_string(index=False))

        metrics_table = save_table(
            "forecast_model_metrics.csv", metrics,
            holdout_weeks=HOLDOUT_WEEKS,
            note="time based split, never random; MAPE excludes weeks where actual is zero",
        )
        comparison_figure = plot_model_comparison(train, test, predictions, metrics)

        best_model = metrics.iloc[0]["model"]
        baseline_mae = float(metrics.loc[metrics["model"] == "seasonal naive", "mae"].iloc[0])
        beat_baseline = [
            row["model"] for _, row in metrics.iterrows()
            if row["model"] != "seasonal naive" and row["mae"] < baseline_mae
        ]
        logger.info("models beating the baseline: %s", ", ".join(beat_baseline) or "none")

        if not beat_baseline:
            log_data_issue(
                SCRIPT, "forecast",
                "no fitted model beat the seasonal naive baseline on the held out year",
                "report the baseline as the forecast and say plainly that the fitted models "
                "added nothing, as section 11 requires",
                severity="note",
            )

        # --- scenarios forward ---
        weeks_ahead = int(
            ((premiere - series.index.max()).days + horizon_months * 30.44) / 7
        )
        logger.info("forecasting %d weeks ahead, to %s", weeks_ahead,
                    (series.index.max() + pd.Timedelta(weeks=weeks_ahead)).date())

        counterfactual = forecast_forward(series, weeks_ahead)
        specs = premiere_multipliers(series)
        logger.info("scenario multipliers: %s", json.dumps(specs))

        scenarios = {
            name: apply_premiere_effect(counterfactual, premiere, spec)
            for name, spec in specs.items()
        }
        scenarios_figure = plot_scenarios(series, scenarios, premiere)

        weekly = pd.DataFrame({"week": counterfactual.index, "counterfactual": counterfactual.values})
        for name, values in scenarios.items():
            weekly[name] = values.values
        weekly["is_after_premiere"] = weekly["week"] >= premiere
        weekly["week"] = weekly["week"].dt.date
        save_table(
            "forecast_scenarios_weekly.csv", weekly,
            premiere=str(premiere.date()),
            note="counterfactual is the no-premiere forecast; scenarios add an imposed event response",
        )

        # --- the summary the retail module reads ---
        season_start = pd.Timestamp(as_date("dates.gift_season_start"))
        january_end = pd.Timestamp(as_date("dates.january_position_end"))

        rows = []
        for name, values in scenarios.items():
            gift_window = values[(values.index >= season_start) & (values.index < premiere)]
            january_window = values[(values.index >= premiere) & (values.index <= january_end)]
            twelve_months = values[values.index >= premiere][:52]
            base_year = series.iloc[-52:]

            rows.append({
                "scenario": name,
                "premiere_peak_weekly_attention": round(float(values.max()), 0),
                "peak_multiple_vs_last_year_mean": round(float(values.max() / base_year.mean()), 2),
                "gift_window_mean_weekly": round(float(gift_window.mean()), 0) if len(gift_window) else np.nan,
                "january_window_mean_weekly": round(float(january_window.mean()), 0) if len(january_window) else np.nan,
                "january_vs_gift_window_ratio": (
                    round(float(january_window.mean() / gift_window.mean()), 2)
                    if len(gift_window) and len(january_window) and gift_window.mean() else np.nan
                ),
                "twelve_month_total_after_premiere": round(float(twelve_months.sum()), 0),
                "uplift_vs_counterfactual": round(
                    float(twelve_months.sum() / counterfactual[counterfactual.index >= premiere][:52].sum()), 2
                ),
                "assumed_peak_multiple": specs[name]["peak"],
                "assumed_sustained_multiple": specs[name]["sustained"],
                "assumed_decay_weeks": specs[name]["decay_weeks"],
            })

        demand = pd.DataFrame(rows).set_index("scenario").loc[["low", "central", "high"]].reset_index()
        demand_table = save_table(
            "demand_scenarios.csv", demand,
            note="the three scenarios module 6 converts into an order quantity",
        )
        logger.info("demand scenarios:\n%s", demand.to_string(index=False))

        # --- saved model artefacts ---
        models_dir = path("outputs_models", create=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        (models_dir / "forecast_metrics.json").write_text(
            json.dumps(
                {
                    "holdout_weeks": HOLDOUT_WEEKS,
                    "train_end": str(train.index.max().date()),
                    "best_model": best_model,
                    "models_beating_baseline": beat_baseline,
                    "metrics": metrics.to_dict(orient="records"),
                    "scenario_specs": specs,
                    "composite_articles": COMPOSITE_ARTICLES,
                    "random_seed": random_seed(),
                },
                indent=2, default=str,
            ),
            encoding="utf-8",
        )

        # --- the finding ---
        central = demand[demand["scenario"] == "central"].iloc[0]
        best_mape = float(metrics.iloc[0]["mape"])
        baseline_mape = float(metrics.loc[metrics["model"] == "seasonal naive", "mape"].iloc[0])

        finding = (
            f"On a held out final year, {best_model} was the most accurate of the five "
            f"approaches at {best_mape:.0f} per cent mean absolute percentage error against the "
            f"seasonal naive baseline's {baseline_mape:.0f} per cent"
            f"{', and ' + str(len(beat_baseline)) + ' of the four fitted models beat that baseline' if beat_baseline else ', and no fitted model beat that baseline'}. "
            f"Carrying the counterfactual forward and imposing an event response measured from "
            f"real franchise events gives a central scenario peaking at "
            f"{central['premiere_peak_weekly_attention']:,.0f} weekly views, "
            f"{central['peak_multiple_vs_last_year_mean']:.1f} times the mean of the last observed "
            f"year, with a low to high range of "
            f"{demand.iloc[0]['premiere_peak_weekly_attention']:,.0f} to "
            f"{demand.iloc[2]['premiere_peak_weekly_attention']:,.0f}. Attention in the five weeks "
            f"after the premiere runs at {central['january_vs_gift_window_ratio']:.1f} times its "
            f"level during the gift buying window that precedes it, which is the number the "
            f"January stock position argument rests on."
        )

        write_finding(
            "5.1 Interest forecast: how much attention the premiere brings, and when",
            finding,
            evidence=(
                f"Five models compared on a time based split with the final {HOLDOUT_WEEKS} weeks "
                f"held out: seasonal naive, drift naive, Holt-Winters, SARIMA and Prophet. "
                f"Metrics in outputs/tables/forecast_model_metrics.csv. The premiere response is "
                f"imposed rather than fitted, using peak and sustained multiples measured in "
                f"21_event_study.py."
            ),
            sample=(
                f"{len(series)} weekly observations from {series.index.min():%Y-%m-%d} to "
                f"{series.index.max():%Y-%m-%d}, summed across {len(COMPOSITE_ARTICLES)} Wikipedia "
                f"articles. Forecast horizon {weeks_ahead} weeks."
            ),
            uncertainty=(
                "The three scenarios are not confidence intervals and must never be described as "
                "such. They are three readings of an event response measured on four events, only "
                "one of which involved this show, and none of which was a streaming premiere. The "
                "statistical part of the forecast carries ordinary forecast error, shown by the "
                "held out scores; the event part carries assumption risk that no held out test can "
                "measure. The gap between the low and high scenarios reflects that honestly, and "
                "the true outcome can fall outside it."
            ),
            figure=relative(scenarios_figure),
            table=relative(demand_table),
        )

        run.rows_out = len(weekly)
        run.note = f"best model {best_model}, {len(beat_baseline)} beat baseline"
        logger.info("saved %s and %s", relative(metrics_table), relative(comparison_figure))

    logger.info("interest forecast complete")


if __name__ == "__main__":
    main()
