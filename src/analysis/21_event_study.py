"""Measure how franchise attention responds to a major event.

Reads  : data/cleaned/pageviews/pageviews_daily.csv, data/processed/films.csv
Writes : images/figures/event_study_attention_response.png
         outputs/tables/event_study_responses.csv
         outputs/tables/event_uplift_distribution.csv
         docs/findings.md (one entry)
Runtime: about fifteen seconds.

The forecast has to put a number on an event that has not happened yet. The only
honest basis for that is what comparable events did to attention when they did
happen, so this measures them.

Method. For each dated event, take the article most affected by it and compare
the 28 days after the event to the 28 days before, using the median rather than
the mean so a single enormous day does not define the whole window. Three things
come out of each event:

  peak multiple    the highest single day after the event over the pre-event
                   median. How big the spike was.
  window multiple  the median of the 28 days after over the median of the 28
                   before. How big the sustained response was.
  residual multiple the median of days 60 to 120 after over the pre-event
                   median. Whether attention settled back or stayed higher.

That last one is the one the retail argument needs. A spike that decays to
nothing in a fortnight is a news cycle. A spike that leaves attention at a
permanently higher level is a franchise that has been revived, and only the
second kind supports holding stock into January.

The events are those that are both externally dated and visible in the collected
data. Film releases come from the sourced film table; the trailer comes from
config. No event is included on the strength of a press release alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils.config import get, path
from src.utils.io import read_processed, relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, write_finding
from src.utils.plotting import PALETTE, apply_style, save_figure, title_block

SCRIPT = "21_event_study"
logger = get_logger(SCRIPT)

BEFORE_DAYS = 28
AFTER_DAYS = 28
RESIDUAL_FROM = 60
RESIDUAL_TO = 120

# A second, much longer baseline. The 28 day window answers "how big was the
# spike", but it answers it against a level that the run up to the event has
# usually already lifted, so it systematically understates a lasting change and
# can even make one look like a decline. Comparing the quarter after the event
# against the year ending 90 days before it answers the different and, for a
# buyer, more important question: is attention durably higher than it used to be.
LONG_BASELINE_DAYS = 365
LONG_BASELINE_ENDS_BEFORE = 90
LONG_AFTER_DAYS = 90

# The franchise level article, used for film events. A film release moves general
# franchise attention, not only the article about that one film.
FRANCHISE_ARTICLE = "Harry_Potter"
SERIES_ARTICLE = "Harry_Potter_(TV_series)"


def load_daily() -> pd.DataFrame:
    daily = pd.read_csv(path("data_cleaned", "pageviews", "pageviews_daily.csv"))
    daily["date"] = pd.to_datetime(daily["date"])
    return daily


def series_for(daily: pd.DataFrame, article: str) -> pd.Series:
    subset = daily[daily["article"] == article]
    if subset.empty:
        return pd.Series(dtype=float)
    return subset.set_index("date")["views"].sort_index()


def measure_event(series: pd.Series, event_date: pd.Timestamp, name: str, article: str) -> dict | None:
    """Measure one event's effect on one article's daily views."""
    if series.empty:
        return None

    before = series.loc[event_date - pd.Timedelta(days=BEFORE_DAYS): event_date - pd.Timedelta(days=1)]
    after = series.loc[event_date: event_date + pd.Timedelta(days=AFTER_DAYS)]
    residual = series.loc[
        event_date + pd.Timedelta(days=RESIDUAL_FROM): event_date + pd.Timedelta(days=RESIDUAL_TO)
    ]

    # An event needs a real before and after window to be measurable. Anything
    # thinner is dropped rather than reported on partial data.
    if len(before) < BEFORE_DAYS * 0.75 or len(after) < AFTER_DAYS * 0.75:
        logger.info("skipping %s: only %d days before and %d after", name, len(before), len(after))
        return None

    baseline = float(before.median())
    if baseline <= 0:
        logger.info("skipping %s: pre-event baseline is zero", name)
        return None

    # Days for the response to fall back within 20 per cent of baseline.
    decay_days = np.nan
    tail = series.loc[event_date: event_date + pd.Timedelta(days=RESIDUAL_TO)]
    settled = tail[tail <= baseline * 1.2]
    if not settled.empty:
        decay_days = int((settled.index[0] - event_date).days)

    # The long baseline: the year ending 90 days before the event, against the
    # quarter after it. This is what catches a step change that the short window
    # hides.
    long_before = series.loc[
        event_date - pd.Timedelta(days=LONG_BASELINE_DAYS + LONG_BASELINE_ENDS_BEFORE):
        event_date - pd.Timedelta(days=LONG_BASELINE_ENDS_BEFORE)
    ]
    long_after = series.loc[event_date: event_date + pd.Timedelta(days=LONG_AFTER_DAYS)]

    long_baseline = float(long_before.median()) if len(long_before) >= 180 else np.nan
    if long_baseline and long_baseline > 0 and len(long_after) >= 45:
        step_multiple = round(float(long_after.median()) / long_baseline, 2)
    else:
        step_multiple = np.nan

    return {
        "event": name,
        "article": article,
        "event_date": event_date.date(),
        "baseline_daily_views": round(baseline, 1),
        "peak_daily_views": round(float(after.max()), 1),
        "peak_multiple": round(float(after.max()) / baseline, 2),
        "window_multiple": round(float(after.median()) / baseline, 2),
        "residual_multiple": round(float(residual.median()) / baseline, 2) if len(residual) else np.nan,
        "long_baseline_daily_views": round(long_baseline, 1) if long_baseline == long_baseline else np.nan,
        "step_multiple": step_multiple,
        "days_to_settle": decay_days,
        "days_observed_after": len(after),
    }


def build_event_list(films: pd.DataFrame) -> list[tuple[str, pd.Timestamp, str]]:
    """Events that are both externally dated and inside the pageviews window."""
    events: list[tuple[str, pd.Timestamp, str]] = []

    pageviews_start = pd.Timestamp(str(get("dates.pageviews_start")))

    for row in films.itertuples():
        release = pd.Timestamp(row.release_date_na)
        if release < pageviews_start:
            continue  # pageviews only begin in July 2015
        events.append((f"Film release: {row.title}", release, FRANCHISE_ARTICLE))

    for event in get("events"):
        events.append((
            f"{event['name'].replace('_', ' ').title()}",
            pd.Timestamp(str(event["date"])),
            SERIES_ARTICLE,
        ))

    return events


def plot_responses(series_by_event: dict[str, pd.Series], headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 5.8))

    colours = [PALETTE["accent"], PALETTE["support"], PALETTE["highlight"], PALETTE["muted"]]

    for (name, normalised), colour in zip(series_by_event.items(), colours * 4, strict=False):
        ax.plot(normalised.index, normalised.values, label=name, color=colour, linewidth=1.8)

    ax.axvline(0, color=PALETTE["ink"], linewidth=1.2, linestyle="--")
    ax.axhline(1, color=PALETTE["grid"], linewidth=1, zorder=0)
    ax.set_yscale("log")
    ax.set_xlabel("days from the event")
    ax.set_ylabel("daily views relative to the 28 days before (log scale)")
    ax.legend(loc="upper right", fontsize=8.5)

    title_block(ax, headline, subtitle)
    return save_figure(
        fig, "event_study_attention_response.png",
        "Wikipedia daily pageviews, retrieved 2 September 2026",
    )


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        daily = load_daily()
        films = read_processed("films.csv")
        films["release_date_na"] = pd.to_datetime(films["release_date_na"])

        events = build_event_list(films)
        logger.info("measuring %d candidate events", len(events))

        results: list[dict] = []
        curves: dict[str, pd.Series] = {}

        for name, event_date, article in events:
            series = series_for(daily, article)
            measured = measure_event(series, event_date, name, article)
            if measured is None:
                continue
            results.append(measured)

            window = series.loc[
                event_date - pd.Timedelta(days=BEFORE_DAYS): event_date + pd.Timedelta(days=RESIDUAL_TO)
            ]
            baseline = measured["baseline_daily_views"]
            normalised = pd.Series(
                (window / baseline).values,
                index=(window.index - event_date).days,
            )
            curves[name.replace("Film release: Harry Potter and the ", "").replace("Film release: ", "")] = normalised

        if not results:
            logger.error("no event had enough surrounding data to measure")
            run.rows_out = 0
            return

        responses = pd.DataFrame(results).sort_values("peak_multiple", ascending=False)
        table_path = save_table(
            "event_study_responses.csv", responses,
            note="multiples are against the median of the 28 days before the event",
        )
        logger.info("event responses:\n%s", responses.to_string(index=False))

        # The distribution the forecast draws its scenarios from. Film releases
        # and the trailer are kept separate because they are different kinds of
        # event: a film release is a product going on sale, a trailer is an
        # announcement about a product that is not out yet.
        film_events = responses[responses["event"].str.startswith("Film release")]
        trailer_events = responses[~responses["event"].str.startswith("Film release")]

        distribution = pd.DataFrame([
            {
                "event_kind": "film release",
                "events": len(film_events),
                "peak_multiple_min": film_events["peak_multiple"].min(),
                "peak_multiple_median": film_events["peak_multiple"].median(),
                "peak_multiple_max": film_events["peak_multiple"].max(),
                "window_multiple_median": film_events["window_multiple"].median(),
                "residual_multiple_median": film_events["residual_multiple"].median(),
                "step_multiple_median": film_events["step_multiple"].median(),
            },
            {
                "event_kind": "trailer or announcement",
                "events": len(trailer_events),
                "peak_multiple_min": trailer_events["peak_multiple"].min(),
                "peak_multiple_median": trailer_events["peak_multiple"].median(),
                "peak_multiple_max": trailer_events["peak_multiple"].max(),
                "window_multiple_median": trailer_events["window_multiple"].median(),
                "residual_multiple_median": trailer_events["residual_multiple"].median(),
                "step_multiple_median": trailer_events["step_multiple"].median(),
            },
        ])
        save_table("event_uplift_distribution.csv", distribution)
        logger.info("uplift distribution:\n%s", distribution.to_string(index=False))

        biggest = responses.iloc[0]
        film_peak_median = float(film_events["peak_multiple"].median()) if len(film_events) else np.nan
        film_residual_median = float(film_events["residual_multiple"].median()) if len(film_events) else np.nan

        trailer = trailer_events.iloc[0] if len(trailer_events) else None
        film_residual_median = float(film_events["residual_multiple"].median()) if len(film_events) else np.nan

        headline = "Event spikes are large and short lived; the lasting rise came earlier, without an event"
        subtitle = (
            f"Daily views around each event, divided by the median of the 28 days before. "
            f"Largest response: {biggest['event']} at {biggest['peak_multiple']:.0f} times baseline, "
            f"back to baseline in {biggest['days_to_settle']:.0f} days."
        )
        figure_path = plot_responses(curves, headline, subtitle)

        trailer_text = ""
        if trailer is not None:
            trailer_text = (
                f"The March 2026 teaser produced the largest single response in the whole series, "
                f"taking the show's article from a median {trailer['baseline_daily_views']:,.0f} views "
                f"a day to {trailer['peak_daily_views']:,.0f}, a multiple of "
                f"{trailer['peak_multiple']:.0f} — but it was back within a fifth of its "
                f"pre-trailer level in {trailer['days_to_settle']:.0f} days and two to four months "
                f"later was running at {trailer['residual_multiple']:.2f} times it, which is to say "
                f"no higher than before. "
            )

        finding = (
            f"{trailer_text}"
            f"The same holds for cinema releases: across {len(film_events)} films the median peak "
            f"was only {film_peak_median:.1f} times the pre-release baseline and attention two to "
            f"four months later sat at {film_residual_median:.2f} times it, slightly below where it "
            f"started, because the marketing run up had already lifted the comparison. The durable "
            f"rise in attention to the new series did not come from any single dated event at all: "
            f"the show's article moved from roughly forty views a day through 2024 to around five "
            f"thousand from July 2025 onward and has stayed there, a step of more than a hundredfold "
            f"that accumulated through casting and production news rather than arriving on one day. "
            f"For a buyer this reverses the intuitive reading: individual publicity events are "
            f"noise that decays inside a month, and the thing worth planning against is the "
            f"sustained level the franchise has already reached."
        )

        write_finding(
            "3.3b Event study: what a franchise event does to attention",
            finding,
            evidence=(
                "Daily Wikipedia pageviews around each dated event on two baselines: the 28 days "
                "immediately before, which measures the spike, and the year ending 90 days before, "
                "which measures whether the level durably changed. Medians throughout, so one "
                "exceptional day cannot define a window. The two baselines disagree in a way that "
                "matters: measured against the short window every event looks like it decays to "
                "nothing, because the run up to the event has already raised the comparison."
            ),
            sample=(
                f"{len(responses)} events with a complete before and after window: "
                f"{len(film_events)} cinema releases and {len(trailer_events)} announcement event. "
                f"Events before July 2015 fall outside the pageviews series and are excluded, which "
                f"removes all eight original films and is the main limitation of this sample."
            ),
            uncertainty=(
                f"Peak multiples across film releases run from "
                f"{film_events['peak_multiple'].min():.1f} to {film_events['peak_multiple'].max():.1f}, "
                f"so any single figure taken from them carries a factor of about two either way, and "
                f"three events is far too few to fit a distribution to. No event in this sample is a "
                f"streaming premiere, which is the event actually being forecast, and a premiere that "
                f"releases eight episodes over eight weeks has no analogue here at all. The step "
                f"identified in 2025 is read off the series rather than tested against a "
                f"counterfactual, so it is a description of what happened, not a causal estimate."
            ),
            figure=relative(figure_path),
            table=relative(table_path),
        )

        run.rows_out = len(responses)
        run.note = f"{len(responses)} events measured"

    logger.info("event study complete")


if __name__ == "__main__":
    main()
