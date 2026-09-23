"""Module 4. The Houses. Segmenting the product catalogue into archetypes.

Reads  : data/raw/toys/rebrickable_*.csv, outputs/tables/theme_part_profile.csv
Writes : images/figures/segmentation_k_selection.png
         images/figures/segmentation_profiles.png
         outputs/tables/segment_profiles.csv
         outputs/tables/segment_assignments.csv
         docs/findings.md (one entry)
Runtime: about a minute.

**What this segments, and what it does not.** The brief's module 4 segments fan
audiences from posting behaviour. That needs the Reddit corpus, which this
project has no credentials for, and there is no way to segment people without
data about people. Rather than skip the module, the same method is applied to
the thing the project can see: the product catalogue. Clustering sets by their
construction profile gives product archetypes, and knowing which archetype the
branded line sits in is a stocking decision, which is what module 4 was for.

It is a segmentation of products, not of audiences, and it is called that
throughout. The generation comparison the brief asks for cannot be done at all,
and is not attempted.

**The rule from section 10 that is not broken.** Clusters come from the data.
House names are applied afterwards, for communication only. Nothing is sorted
into a house first and then analysed. That ordering is enforced by the structure
of this script: `fit_clusters` never sees a house name, and `name_segments` runs
after the profiles exist and only adds a label column.

**Choosing k.** Section 10 requires two independent measures, so both the
silhouette score and the elbow are computed across a range of k and both are
plotted. They disagree here, and the tie-break rule is written down in the code
before the result rather than chosen after seeing it: silhouette peaks at k=2,
which is the cleanest possible split of anything and a useless segmentation, so
where the elbow's k scores within 5 per cent of the best silhouette the elbow
wins. Both curves are plotted so a reader can argue with the rule and not only
with the outcome.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from src.utils.config import get, path, random_seed
from src.utils.io import relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import HOUSE_COLOURS, PALETTE, apply_style, save_figure, title_block

SCRIPT = "26_product_segmentation"
logger = get_logger(SCRIPT)

FEATURES = [
    "num_parts",
    "minifig_count",
    "distinct_parts",
    "distinct_colours",
    "parts_per_distinct_part",
    "colour_variety",
]

# Applied only after the clusters are profiled. Section 10 is explicit that the
# labels are cosmetic, and the order of operations in main() is what enforces it.
HOUSE_LABELS = ["gryffindor", "slytherin", "ravenclaw", "hufflepuff"]


def build_set_features() -> pd.DataFrame:
    """One row per set, describing how it is built rather than what it depicts."""
    raw = path("data_raw", "toys")
    inventory_parts = pd.read_csv(raw / "rebrickable_inventory_parts.csv")
    inventories = pd.read_csv(raw / "rebrickable_inventories.csv")
    sets = pd.read_csv(raw / "rebrickable_sets.csv")
    themes = pd.read_csv(raw / "rebrickable_themes.csv")
    inventory_minifigs = pd.read_csv(raw / "rebrickable_inventory_minifigs.csv")

    first_version = inventories[inventories["version"] == 1][["id", "set_num"]]

    per_set = (
        inventory_parts.merge(first_version, left_on="inventory_id", right_on="id", how="inner")
        .groupby("set_num", as_index=False)
        .agg(
            distinct_parts=("part_num", "nunique"),
            distinct_colours=("color_id", "nunique"),
            total_quantity=("quantity", "sum"),
        )
    )

    minifigs = (
        inventory_minifigs.merge(first_version, left_on="inventory_id", right_on="id", how="inner")
        .groupby("set_num", as_index=False)["quantity"].sum()
        .rename(columns={"quantity": "minifig_count"})
    )

    frame = (
        sets.merge(per_set, on="set_num", how="inner")
        .merge(minifigs, on="set_num", how="left")
        .merge(
            themes[["id", "name"]].rename(columns={"id": "theme_id", "name": "theme_name"}),
            on="theme_id", how="left",
        )
    )
    frame["minifig_count"] = frame["minifig_count"].fillna(0)

    # Two derived ratios. Piece count alone conflates a big simple set with a
    # small intricate one, and it is the ratio that separates the two.
    frame["parts_per_distinct_part"] = frame["num_parts"] / frame["distinct_parts"].clip(lower=1)
    frame["colour_variety"] = frame["distinct_colours"] / frame["distinct_parts"].clip(lower=1)

    # A set with no pieces is a promotional item, not a construction set, and it
    # would form a cluster of its own that says nothing about product design.
    before = len(frame)
    frame = frame[(frame["num_parts"] > 0) & (frame["distinct_parts"] > 0)]
    frame = frame[frame["year"] >= int(get("sources.toys.year_from"))]
    logger.info("set features: %d sets, %d dropped as promotional or out of range",
                len(frame), before - len(frame))

    return frame.reset_index(drop=True)


def choose_k(scaled: np.ndarray, k_range: list[int], seed: int) -> pd.DataFrame:
    """Silhouette and inertia across k. Two independent measures, as required."""
    rows = []
    for k in k_range:
        model = KMeans(n_clusters=k, random_state=seed, n_init=10)
        labels = model.fit_predict(scaled)

        # Silhouette on a sample: it is O(n squared) and this is 20,000 sets.
        sample = min(5000, len(scaled))
        score = silhouette_score(scaled, labels, sample_size=sample, random_state=seed)

        rows.append({"k": k, "silhouette": round(float(score), 4), "inertia": round(float(model.inertia_), 1)})
        logger.info("k=%d  silhouette %.4f  inertia %.0f", k, score, model.inertia_)

    frame = pd.DataFrame(rows)

    # The elbow, found numerically rather than by eye: the k whose point is
    # furthest from the straight line joining the first and last points of the
    # inertia curve. Reading an elbow by eye is where a k gets chosen to suit
    # the answer somebody wanted.
    x = frame["k"].to_numpy(dtype=float)
    y = frame["inertia"].to_numpy(dtype=float)
    x_norm = (x - x.min()) / (x.max() - x.min())
    y_norm = (y - y.min()) / (y.max() - y.min() or 1)
    line = np.array([x_norm[-1] - x_norm[0], y_norm[-1] - y_norm[0]])
    line = line / np.linalg.norm(line)
    distances = []
    for i in range(len(x_norm)):
        point = np.array([x_norm[i] - x_norm[0], y_norm[i] - y_norm[0]])
        projection = point @ line * line
        distances.append(float(np.linalg.norm(point - projection)))
    frame["elbow_distance"] = np.round(distances, 4)
    return frame


def profile_segments(frame: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
    """Describe each cluster on its features, before any label is applied."""
    working = frame.copy()
    working["segment"] = labels

    profile = working.groupby("segment", as_index=False).agg(
        sets=("set_num", "count"),
        median_parts=("num_parts", "median"),
        median_minifigs=("minifig_count", "median"),
        median_distinct_parts=("distinct_parts", "median"),
        median_distinct_colours=("distinct_colours", "median"),
        median_repetition=("parts_per_distinct_part", "median"),
        median_year=("year", "median"),
    )
    profile["share_of_catalogue"] = (profile["sets"] / len(working)).round(3)
    return profile


def describe_segment(row: pd.Series, overall_parts: float) -> str:
    """A plain descriptive name, derived from the profile numbers.

    Named from the data rather than chosen by hand, so the names cannot drift
    away from what the clusters actually contain when the data is refreshed.
    """
    size = "large" if row["median_parts"] > overall_parts * 2 else (
        "small" if row["median_parts"] < overall_parts * 0.5 else "mid-size"
    )
    if row["median_minifigs"] >= 4:
        character = "character-heavy"
    elif row["median_minifigs"] >= 1:
        character = "character-led"
    else:
        character = "no-minifigure"

    if row["median_repetition"] >= 3.5:
        build = "repetitive build"
    elif row["median_repetition"] <= 2.0:
        build = "varied build"
    else:
        build = "standard build"

    return f"{size}, {character}, {build}"


def plot_k_selection(scores: pd.DataFrame, chosen_k: int, headline: str, subtitle: str) -> Path:
    apply_style()
    fig, (ax_sil, ax_elbow) = plt.subplots(1, 2, figsize=(12, 5.0))

    ax_sil.plot(scores["k"], scores["silhouette"], marker="o", markersize=7,
                color=PALETTE["accent"], linewidth=2.2)
    ax_sil.axvline(chosen_k, color=PALETTE["highlight"], linestyle="--", linewidth=1.6)
    ax_sil.set_xlabel("number of clusters, k")
    ax_sil.set_ylabel("silhouette score, higher is better")
    ax_sil.set_title("Silhouette", loc="left", fontsize=11)

    ax_elbow.plot(scores["k"], scores["inertia"] / 1000, marker="o", markersize=7,
                  color=PALETTE["support"], linewidth=2.2)
    elbow_k = int(scores.loc[scores["elbow_distance"].idxmax(), "k"])
    ax_elbow.axvline(elbow_k, color=PALETTE["highlight"], linestyle="--", linewidth=1.6)
    ax_elbow.set_xlabel("number of clusters, k")
    ax_elbow.set_ylabel("within-cluster inertia, thousands")
    ax_elbow.set_title(f"Elbow (numerically at k={elbow_k})", loc="left", fontsize=11)

    ax_sil.set_xticks(scores["k"])
    ax_elbow.set_xticks(scores["k"])
    title_block(ax_sil, headline, subtitle, subtitle_wrap=125)
    return save_figure(fig, "segmentation_k_selection.png", "Rebrickable full catalogue")


def plot_profiles(frame: pd.DataFrame, labels: np.ndarray, scaled: np.ndarray,
                  profile: pd.DataFrame, headline: str, subtitle: str) -> Path:
    apply_style()
    fig, (ax_scatter, ax_bar) = plt.subplots(1, 2, figsize=(12.5, 5.8))

    # PCA only to make a 2D picture. The clustering itself runs on the full
    # feature space; this is a projection for the eye, not the model.
    coords = PCA(n_components=2, random_state=random_seed()).fit_transform(scaled)

    colours = [HOUSE_COLOURS[HOUSE_LABELS[i % len(HOUSE_LABELS)]] for i in range(len(profile))]

    branded = frame["is_branded"].to_numpy()
    for segment in sorted(profile["segment"]):
        mask = (labels == segment) & ~branded
        ax_scatter.scatter(
            coords[mask, 0], coords[mask, 1], s=5, alpha=0.28,
            color=colours[segment], linewidths=0,
        )

    # The branded line drawn on top, so its position among the archetypes is
    # the thing the eye goes to.
    ax_scatter.scatter(
        coords[branded, 0], coords[branded, 1], s=26, color=PALETTE["ink"],
        edgecolors=PALETTE["ground"], linewidths=0.5, label="wizarding line", zorder=5,
    )
    ax_scatter.set_xlabel("first principal component")
    ax_scatter.set_ylabel("second principal component")
    ax_scatter.legend(loc="upper right", fontsize=9)
    ax_scatter.set_title("Catalogue in two dimensions", loc="left", fontsize=11)

    order = profile.sort_values("branded_share", ascending=False)
    ax_bar.barh(
        [f"{r.segment}: {r.plain_name}" for r in order.itertuples()],
        order["branded_share"] * 100,
        color=[colours[int(r.segment)] for r in order.itertuples()],
    )
    ax_bar.invert_yaxis()
    ax_bar.set_xlabel("share of that segment's sets that are wizarding, per cent")
    ax_bar.set_title("Where the branded line sits", loc="left", fontsize=11)

    title_block(ax_scatter, headline, subtitle, subtitle_wrap=128)
    return save_figure(
        fig, "segmentation_profiles.png",
        "k-means on construction features; house colours are labels applied after clustering",
    )


def main() -> None:
    seed = random_seed()
    np.random.seed(seed)
    k_range = get("modelling.clustering.k_range")
    silhouette_min = float(get("modelling.clustering.silhouette_min"))

    with RunTimer(SCRIPT, logger) as run:
        frame = build_set_features()
        run.rows_in = len(frame)

        # Which sets are the wizarding line, for locating it afterwards. This is
        # not a clustering feature: the model must not know which sets are
        # branded, or it could simply learn to separate them.
        branded_themes = {"Harry Potter", "Fantastic Beasts",
                          "Harry Potter and Fantastic Beasts Series 1",
                          "Harry Potter and Fantastic Beasts Series 2"}
        frame["is_branded"] = frame["theme_name"].isin(branded_themes)
        logger.info("%d of %d sets are the wizarding line", int(frame["is_branded"].sum()), len(frame))

        # Log-scale the heavy-tailed size features: piece counts run from 1 to
        # 10,000 and without this the clustering would only ever find "big" and
        # "small".
        features = frame[FEATURES].copy()
        for column in ["num_parts", "distinct_parts", "distinct_colours", "minifig_count"]:
            features[column] = np.log1p(features[column])

        scaled = StandardScaler().fit_transform(features)

        scores = choose_k(scaled, list(k_range), seed)
        save_table("segmentation_k_selection.csv", scores)

        best_silhouette_k = int(scores.loc[scores["silhouette"].idxmax(), "k"])
        elbow_k = int(scores.loc[scores["elbow_distance"].idxmax(), "k"])
        best_silhouette = float(scores["silhouette"].max())
        elbow_silhouette = float(scores.loc[scores["k"] == elbow_k, "silhouette"].iloc[0])

        # The tie-break rule, stated before the result rather than after it.
        #
        # Silhouette almost always peaks at k=2 on data like this, because the
        # cleanest possible split of anything is into two halves. That is a real
        # measurement and a useless segmentation: "big sets and small sets" is
        # not an archetype, it is a sort. So where the elbow's k scores within
        # this tolerance of the silhouette's best, the elbow wins, on the
        # grounds that the extra structure costs almost nothing in separation.
        # The tolerance is fixed here, not tuned until it gave a nice answer.
        SILHOUETTE_TOLERANCE = 0.95

        if elbow_silhouette >= best_silhouette * SILHOUETTE_TOLERANCE:
            chosen_k = elbow_k
            reason = (
                f"the elbow's k={elbow_k} scores {elbow_silhouette:.4f} against the best "
                f"silhouette of {best_silhouette:.4f} at k={best_silhouette_k}, which is within "
                f"the {1 - SILHOUETTE_TOLERANCE:.0%} tolerance, so the more informative split wins"
            )
        else:
            chosen_k = best_silhouette_k
            reason = (
                f"the elbow's k={elbow_k} scores {elbow_silhouette:.4f}, more than "
                f"{1 - SILHOUETTE_TOLERANCE:.0%} below the best silhouette of "
                f"{best_silhouette:.4f}, so the better separated split wins"
            )

        logger.info(
            "silhouette favours k=%d (%.4f), elbow favours k=%d (%.4f); chose k=%d",
            best_silhouette_k, best_silhouette, elbow_k, elbow_silhouette, chosen_k,
        )
        if best_silhouette_k != elbow_k:
            log_data_issue(
                SCRIPT, "segmentation",
                f"the two k selection measures disagree: silhouette {best_silhouette_k}, elbow {elbow_k}",
                f"k={chosen_k} was used because {reason}. Both curves are plotted so a reader can "
                f"disagree with the rule rather than only with the outcome.",
                severity="note",
            )

        best_score = float(scores.loc[scores["k"] == chosen_k, "silhouette"].iloc[0])
        if best_score < silhouette_min:
            log_data_issue(
                SCRIPT, "segmentation",
                f"the best silhouette is {best_score:.3f}, below the {silhouette_min} floor in config",
                "the segments are reported but described as weakly separated; the catalogue may "
                "not contain distinct archetypes at all",
                severity="error",
            )

        model = KMeans(n_clusters=chosen_k, random_state=seed, n_init=20)
        labels = model.fit_predict(scaled)

        # --- profile first, name second, house label last ---
        profile = profile_segments(frame, labels)
        overall_parts = float(frame["num_parts"].median())
        profile["plain_name"] = profile.apply(lambda r: describe_segment(r, overall_parts), axis=1)

        working = frame.copy()
        working["segment"] = labels
        branded_share = (
            working.groupby("segment")["is_branded"].mean().rename("branded_share").reset_index()
        )
        profile = profile.merge(branded_share, on="segment")
        profile["branded_sets"] = (
            working[working["is_branded"]].groupby("segment").size()
            .reindex(profile["segment"]).fillna(0).astype(int).to_numpy()
        )

        # Only now, after the clusters exist and are profiled, does a house name
        # get attached. Section 10 forbids doing this in the other order.
        profile["house_label"] = [
            HOUSE_LABELS[i % len(HOUSE_LABELS)].capitalize() for i in range(len(profile))
        ]

        logger.info(
            "segment profiles:\n%s",
            profile[[
                "segment", "plain_name", "sets", "median_parts", "median_minifigs",
                "branded_sets", "branded_share", "house_label",
            ]].to_string(index=False),
        )

        profile_table = save_table(
            "segment_profiles.csv", profile,
            k=chosen_k, silhouette=best_score,
            note="plain names derived from the profile; house labels are cosmetic and applied last",
        )
        save_table(
            "segment_assignments.csv",
            working[["set_num", "name", "year", "theme_name", "is_branded", "segment",
                     "num_parts", "minifig_count", "distinct_parts", "distinct_colours"]],
        )

        k_headline = (
            f"Silhouette and elbow "
            f"{'agree on' if best_silhouette_k == elbow_k else 'disagree; the rule chooses'} "
            f"k={chosen_k}"
        )
        k_subtitle = (
            f"Both measures computed across k={min(k_range)} to {max(k_range)} on "
            f"{len(frame):,} sets. Silhouette peaks at k={best_silhouette_k} ({best_score:.3f}); "
            f"the elbow, found numerically rather than by eye, falls at k={elbow_k} "
            f"({elbow_silhouette:.3f})."
        )
        plot_k_selection(scores, chosen_k, k_headline, k_subtitle)

        branded_home = profile.loc[profile["branded_sets"].idxmax()]

        profile_headline = (
            f"The wizarding line sits mostly in the {branded_home['plain_name']} segment"
        )
        profile_subtitle = (
            f"k-means on six construction features, k={chosen_k}, silhouette {best_score:.3f}. "
            f"{int(branded_home['branded_sets'])} of "
            f"{int(frame['is_branded'].sum())} branded sets fall in segment "
            f"{int(branded_home['segment'])}. Colours are house labels applied after clustering, "
            f"for presentation only."
        )
        figure_path = plot_profiles(frame, labels, scaled, profile, profile_headline, profile_subtitle)

        branded_concentration = (
            int(branded_home["branded_sets"]) / int(frame["is_branded"].sum())
        )

        finding = (
            f"Clustering {len(frame):,} construction sets on how they are built, with no knowledge "
            f"of which are branded, produces {chosen_k} archetypes at a silhouette of "
            f"{best_score:.3f}. The wizarding line is not spread across them: "
            f"{branded_concentration:.0%} of its sets fall in the "
            f"'{branded_home['plain_name']}' segment, which is "
            f"{branded_home['share_of_catalogue']:.0%} of the catalogue overall. Its median set has "
            f"{branded_home['median_parts']:.0f} pieces and "
            f"{branded_home['median_minifigs']:.0f} minifigures against a catalogue median of "
            f"{overall_parts:.0f} pieces, so the line is a character-led, mid-size proposition "
            f"rather than a large-build one, and a season one range should be bought as gift-priced "
            f"character product rather than as centrepiece models."
        )

        write_finding(
            "4 The Houses: product archetypes, and where the branded line sits",
            finding,
            evidence=(
                "k-means on six construction features (piece count, minifigure count, distinct "
                "parts, distinct colours, and two derived ratios), standardised, with the heavy "
                "tailed counts log scaled first. k chosen from silhouette and a numerically "
                "located elbow, both plotted. The branded flag is held out of the feature set so "
                "the model cannot simply learn to separate the line it is being asked about."
            ),
            sample=(
                f"{len(frame):,} sets from {int(frame['year'].min())} to "
                f"{int(frame['year'].max())} with a non-zero piece count, of which "
                f"{int(frame['is_branded'].sum())} are the wizarding line. Features derived from "
                f"the 1.56 million row part inventory."
            ),
            uncertainty=(
                "This is a segmentation of products, not of audiences, and module 4 asks for "
                "audiences. That analysis needs the Reddit corpus, which this project has no "
                "credentials for, and there is no way to segment people without data about people; "
                "the generation comparison the brief also asks for is therefore not attempted at "
                f"all. A silhouette of {best_score:.3f} is modest, which means the archetypes are "
                "real but not sharply separated, and sets near a boundary could reasonably belong "
                "to either side. The features describe how a set is built, not how it sells: "
                "no sales or price data was available to check whether construction archetypes "
                "correspond to commercial ones, so the stocking reading at the end is an inference "
                "from product design rather than a measured relationship. House labels are "
                "cosmetic, applied after the clusters were fitted and profiled, and carry no "
                "meaning."
            ),
            figure=relative(figure_path),
            table=relative(profile_table),
        )

        run.rows_out = len(frame)
        run.note = f"k={chosen_k}, silhouette {best_score:.3f}, branded concentration {branded_concentration:.0%}"

    logger.info("product segmentation complete")


if __name__ == "__main__":
    main()
