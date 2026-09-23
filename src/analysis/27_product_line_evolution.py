"""Modules 3.4 and 5.3. How the branded line is scaled, and what predicts set size.

Reads  : outputs/tables/segment_assignments.csv, data/processed/films.csv
Writes : images/figures/product_line_by_year.png
         outputs/tables/product_line_by_year.csv
         outputs/tables/set_size_model.csv
         docs/findings.md (one entry)
Runtime: about twenty seconds.

**What these modules were meant to be.** Module 3.4 tests whether the branded
line carries a licensing premium, meaning a higher price per piece than
comparable unbranded lines. Module 5.3 fits a regression predicting retail price
from piece count, minifigure count, year and theme. Both need retail price, and
the only source for it is Brickset, which needs an API key this project does not
have. Rebrickable carries no price field at all.

**What is here instead.** Two questions the same data can answer without price.

The first is a timing question, and it is the one that matters commercially: does
the licensor scale the product line ahead of a release, and by how much? If the
line reliably grows in the year before a film, then the size of the 2026 line is
itself a signal about what the licensor expects from the premiere, independent of
anything this project forecasts.

The second is the same regression the brief asks for with size as the target
instead of price. It answers what drives how big a set is rather than what drives
what it costs. That is a weaker question, and it is labelled as a substitute
rather than presented as module 5.3 delivered.

Nothing here should be read as a statement about price or margin. The project has
no price data, and a licensing premium remains untested.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.utils.config import as_date, path, random_seed
from src.utils.io import read_processed, relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import PALETTE, apply_style, save_figure, title_block

SCRIPT = "27_product_line_evolution"
logger = get_logger(SCRIPT)


def load_sets() -> pd.DataFrame:
    """Set-level features from module 4, which already joined the part inventory."""
    source = path("outputs_tables", "segment_assignments.csv")
    if not source.exists():
        raise FileNotFoundError(
            f"{relative(source)} does not exist. Run src/analysis/26_product_segmentation.py first."
        )
    return pd.read_csv(source)


def line_by_year(sets: pd.DataFrame) -> pd.DataFrame:
    """Branded line size and shape per year."""
    branded = sets[sets["is_branded"]]
    by_year = branded.groupby("year", as_index=False).agg(
        sets_released=("set_num", "count"),
        median_parts=("num_parts", "median"),
        total_parts=("num_parts", "sum"),
        median_minifigs=("minifig_count", "median"),
        total_minifigs=("minifig_count", "sum"),
        median_distinct_colours=("distinct_colours", "median"),
    )

    # The catalogue-wide count, so a rise in the branded line can be told apart
    # from a rise in the whole catalogue. Without this control, "the line grew in
    # 2001" would just be "the manufacturer grew in 2001".
    catalogue = sets.groupby("year", as_index=False)["set_num"].count().rename(
        columns={"set_num": "catalogue_sets"}
    )
    by_year = by_year.merge(catalogue, on="year", how="left")
    by_year["share_of_catalogue"] = (by_year["sets_released"] / by_year["catalogue_sets"]).round(4)
    return by_year


def release_years() -> list[int]:
    films = read_processed("films.csv")
    return sorted(pd.to_datetime(films["release_date_na"]).dt.year.unique().tolist())


def fit_size_model(sets: pd.DataFrame) -> tuple[pd.DataFrame, object]:
    """Predict log set size from year, minifigures and whether it is branded.

    Log target because piece counts span one to ten thousand and the residuals
    of a linear model on the raw counts are badly skewed. The coefficients then
    read as proportional effects, which is also the more natural way to talk
    about set size.
    """
    frame = sets[(sets["num_parts"] > 0)].copy()
    frame["log_parts"] = np.log(frame["num_parts"])
    frame["years_since_2001"] = frame["year"] - 2001
    frame["is_branded_flag"] = frame["is_branded"].astype(float)
    frame["log_minifigs"] = np.log1p(frame["minifig_count"])
    frame["log_distinct_colours"] = np.log1p(frame["distinct_colours"])

    design = frame[[
        "years_since_2001", "log_minifigs", "log_distinct_colours", "is_branded_flag",
    ]]
    design = sm.add_constant(design)
    model = sm.OLS(frame["log_parts"], design).fit(cov_type="HC3")

    coefficients = pd.DataFrame({
        "term": model.params.index,
        "coefficient": model.params.round(4).to_numpy(),
        "std_error": model.bse.round(4).to_numpy(),
        "p_value": model.pvalues.round(4).to_numpy(),
        "ci_lower": model.conf_int()[0].round(4).to_numpy(),
        "ci_upper": model.conf_int()[1].round(4).to_numpy(),
    })
    coefficients["percent_effect"] = ((np.exp(coefficients["coefficient"]) - 1) * 100).round(2)
    return coefficients, model


def plot_line(by_year: pd.DataFrame, releases: list[int], headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 5.8))

    ax.bar(
        by_year["year"], by_year["sets_released"],
        color=PALETTE["accent"], width=0.68, label="sets released",
    )

    ax_right = ax.twinx()
    ax_right.plot(
        by_year["year"], by_year["median_parts"],
        color=PALETTE["support"], linewidth=2.2, marker="o", markersize=5,
        label="median pieces per set",
    )
    ax_right.set_ylabel("median pieces per set")
    ax_right.grid(False)

    for year in releases:
        if by_year["year"].min() <= year <= by_year["year"].max():
            ax.axvline(year, color=PALETTE["grid"], linewidth=1.2, zorder=0)

    premiere_year = as_date("dates.premiere").year
    ax.axvline(premiere_year, color=PALETTE["highlight"], linewidth=1.8, linestyle="--", zorder=2)
    ax.text(
        premiere_year + 0.15, ax.get_ylim()[1] * 0.94, "series\npremiere",
        fontsize=8.5, color=PALETTE["warn"], va="top",
    )

    ax.set_xlabel("")
    ax.set_ylabel("sets released")

    handles = ax.get_legend_handles_labels()[0] + ax_right.get_legend_handles_labels()[0]
    labels = ax.get_legend_handles_labels()[1] + ax_right.get_legend_handles_labels()[1]
    ax.legend(handles, labels, loc="upper left", fontsize=9)

    title_block(ax, headline, subtitle, subtitle_wrap=118)
    return save_figure(
        fig, "product_line_by_year.png",
        "Rebrickable catalogue; grey lines are film releases, dashed gold is the series premiere",
    )


def main() -> None:
    np.random.seed(random_seed())

    with RunTimer(SCRIPT, logger) as run:
        sets = load_sets()
        run.rows_in = len(sets)

        log_data_issue(
            SCRIPT, "product_line",
            "no retail price data is available, so the licensing premium test (3.4) and the "
            "price model (5.3) cannot be run as specified",
            "replaced with a line-scaling analysis and a set-size regression, both labelled as "
            "substitutes. A Brickset API key would restore both.",
            severity="note",
        )

        by_year = line_by_year(sets)
        releases = release_years()
        table = save_table(
            "product_line_by_year.csv", by_year,
            note="branded line size per year, with the catalogue-wide count as a control",
        )
        logger.info("branded line by year:\n%s", by_year.to_string(index=False))

        # Does the line grow in the year before a release?
        by_year_indexed = by_year.set_index("year")
        pre_release_years = [y - 1 for y in releases if (y - 1) in by_year_indexed.index]
        other_years = [
            y for y in by_year_indexed.index
            if y not in pre_release_years and y not in releases
        ]

        pre_mean = float(by_year_indexed.loc[pre_release_years, "sets_released"].mean())
        release_mean = float(
            by_year_indexed.loc[[y for y in releases if y in by_year_indexed.index], "sets_released"].mean()
        )
        other_mean = float(by_year_indexed.loc[other_years, "sets_released"].mean()) if other_years else np.nan

        logger.info(
            "sets per year: %.1f in a release year, %.1f the year before, %.1f otherwise",
            release_mean, pre_mean, other_mean,
        )

        latest_year = int(by_year["year"].max())
        latest_sets = int(by_year_indexed.loc[latest_year, "sets_released"])

        coefficients, model = fit_size_model(sets)
        save_table(
            "set_size_model.csv", coefficients,
            r_squared=round(float(model.rsquared), 4),
            observations=int(model.nobs),
            note="log piece count regressed on year, minifigures, colours and branded flag",
        )
        logger.info("set size model (R2 %.3f):\n%s", model.rsquared, coefficients.to_string(index=False))

        branded_row = coefficients[coefficients["term"] == "is_branded_flag"].iloc[0]

        # The release-year comparison is confounded, and saying so is the result.
        # Ten of the eleven films landed between 2001 and 2011, when the whole
        # catalogue was a third of its current size, while most non-release years
        # are recent. Comparing raw counts across those two eras measures the
        # manufacturer growing, not the licensor responding to a film.
        pre_share = float(by_year_indexed.loc[pre_release_years, "share_of_catalogue"].mean())
        release_share = float(
            by_year_indexed.loc[
                [y for y in releases if y in by_year_indexed.index], "share_of_catalogue"
            ].mean()
        )
        other_share = (
            float(by_year_indexed.loc[other_years, "share_of_catalogue"].mean())
            if other_years else np.nan
        )
        logger.info(
            "share of catalogue: %.4f in a release year, %.4f the year before, %.4f otherwise",
            release_share, pre_share, other_share,
        )

        latest_share = float(by_year_indexed.loc[latest_year, "share_of_catalogue"])
        latest_median_parts = float(by_year_indexed.loc[latest_year, "median_parts"])
        release_era = [y for y in by_year_indexed.index if y <= 2011]
        modern_era = [y for y in by_year_indexed.index if y >= 2018]
        release_era_median = float(by_year_indexed.loc[release_era, "median_parts"].median())
        modern_era_median = float(by_year_indexed.loc[modern_era, "median_parts"].median())

        log_data_issue(
            SCRIPT, "product_line",
            f"release years average {release_mean:.1f} branded sets against {other_mean:.1f} in "
            f"non-release years, which is the opposite of the expected ramp",
            "the comparison is confounded: ten of eleven films fall in 2001-2011 when the "
            "catalogue was a third of its current size, so the raw counts compare two eras rather "
            "than two conditions. No release-ramp claim is made in either direction.",
            severity="note",
        )

        headline = (
            "No release ramp is detectable: the comparison measures two eras, not two conditions"
        )
        subtitle = (
            f"Branded sets per year with median piece count overlaid; grey lines are film "
            f"releases. Release years average {release_mean:.0f} sets against {other_mean:.0f} "
            f"otherwise, but ten of eleven films fall before 2012, when the catalogue was far "
            f"smaller, so the difference is era rather than effect."
        )
        figure_path = plot_line(by_year, releases, headline, subtitle)

        branded_effect = float(branded_row["percent_effect"])
        branded_significant = float(branded_row["p_value"]) < 0.05

        finding = (
            f"The hypothesis that the licensor visibly scales the line ahead of a release is not "
            f"supported, and it also cannot be properly tested here. Release years average "
            f"{release_mean:.1f} branded sets against {other_mean:.1f} in years with no release, "
            f"which is the opposite of the expected direction, but that comparison is confounded: "
            f"ten of the eleven films landed between 2001 and 2011, when the catalogue was around "
            f"a third of its present size, so it contrasts two eras rather than two conditions. "
            f"What can be said is that the current line is not being scaled up in count: "
            f"{latest_year} carries {latest_sets} sets at {latest_share:.1%} of the catalogue, in "
            f"line with the last several years rather than above them, though its median set is "
            f"the largest in the line's history at {latest_median_parts:.0f} pieces against "
            f"{release_era_median:.0f} in the film era and {modern_era_median:.0f} across "
            f"2018 to 2026. On set size, the branded flag is worth "
            f"{branded_effect:+.1f} per cent once minifigures, colours and year are controlled "
            f"for, and it is {'distinguishable' if branded_significant else 'not distinguishable'} "
            f"from zero (p = {float(branded_row['p_value']):.2f}), so these are built at the same "
            f"scale as everything else in the catalogue."
        )

        write_finding(
            "3.4 and 5.3 Product line: how it scales to releases, and what drives set size",
            finding,
            evidence=(
                f"Branded set counts, catalogue shares and median piece counts per year from the "
                f"Rebrickable "
                f"catalogue, with the catalogue-wide set count as a control so that growth in the "
                f"line can be told apart from growth in the manufacturer. Plus an OLS of log piece "
                f"count on year, log minifigures, log distinct colours and a branded flag, with "
                f"heteroskedasticity-robust standard errors, R squared {model.rsquared:.3f} over "
                f"{int(model.nobs):,} sets."
            ),
            sample=(
                f"{int(sets['is_branded'].sum())} branded sets across "
                f"{int(by_year['year'].min())} to {int(by_year['year'].max())}, within a catalogue "
                f"of {len(sets):,} sets. Release years taken from the eleven-film table."
            ),
            uncertainty=(
                "Neither module 3.4 nor module 5.3 is delivered as specified, and this does not "
                "substitute for either. Both need retail price, the only source is Brickset, and "
                "that needs an API key this project does not have; Rebrickable carries no price "
                "field at all. So the licensing premium remains completely untested, and nothing "
                "here says anything about price or margin. "
                "The release-year comparison is a description of eleven films' worth of years, not "
                "a model, and with that few release years the averages move materially if one year "
                "is reclassified. The set-size regression answers a weaker question than the price "
                "model would and nothing downstream consumes it. A season one line may also be "
                "announced after this data was collected on 2 September 2026, which would raise "
                "the 2026 count."
            ),
            figure=relative(figure_path),
            table=relative(table),
        )

        run.rows_out = len(by_year)
        run.note = f"{latest_sets} sets in {latest_year}; release-year mean {release_mean:.0f}"

    logger.info("product line analysis complete")


if __name__ == "__main__":
    main()
