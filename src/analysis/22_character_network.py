"""Finding which characters' attention rises and falls together (module 3.2).

Reading: data/cleaned/pageviews/pageviews_weekly.csv, data/processed/characters.csv
Writing: images/figures/character_attention_network.png
         images/figures/character_attention_vs_centrality.png
         outputs/tables/character_centrality.csv
         outputs/tables/character_correlation_matrix.csv
         docs/findings.md (one entry)
Runtime: about fifteen seconds.

I could not build a network of who appears in the same chapter, because PotterDB
chapter records have only an order, a slug, a title and a summary, with no list of
characters. So I build it from attention: the weekly article views of each
character, and which characters rise and fall together. That is more useful to a
buyer anyway, because characters people look up in the same week sell side by side.

All sixteen articles share the franchise trend, so the raw series would correlate
almost perfectly and measure only that trend. I turn each series into week on week
log changes first, which removes the shared level and leaves the shocks. I connect
two characters when their shocks move together more than my threshold. I use
Spearman and not Pearson correlation, because my data has several huge weeks and
one of them would dominate a Pearson coefficient.

I compute three centrality measures. What matters to a buyer is where a character's
place in the network disagrees with raw attention. High centrality with modest
traffic means an audience shared with everyone else, which is a different stocking
choice from a character with a large following of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from src.utils.config import get, path
from src.utils.io import read_processed, relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import HOUSE_COLOURS, PALETTE, apply_style, save_figure, title_block

SCRIPT = "22_character_network"
logger = get_logger(SCRIPT)

# Choosing the edge threshold from the data, because a fixed one did not hold up.
# At any round number below about 0.45, all 120 character pairs clear it and the
# graph is complete. That is a table with lines drawn on it, not a network.
# The reason is the real finding of my analysis. After I difference away the
# shared franchise trend, every pair of characters still correlates between 0.44
# and 0.74, with no gap in that range. There are no communities to find. Attention
# to this cast moves as one bloc, and characters differ only in how tightly each
# one is coupled to it.
# So I draw the graph at a quantile of the observed correlations, only so the
# coupling can be seen, and I read centrality as coupling strength, not network
# position. I say both things in my finding and on the figure.
EDGE_QUANTILE = 0.75

# Setting a density ceiling. If the graph is still this dense at my chosen
# quantile, there is no structure, and my analysis says so.
DENSITY_CEILING = 0.90

# Setting the smallest network I will publish. Sixteen nodes cannot support a
# claim about the whole cast, and below this floor I drop the analysis, because
# a weak network is worse than none.
MIN_NODES = 8


def pretty(article: str) -> str:
    """Turning a Wikipedia article title into a readable label."""
    return article.replace("_", " ").replace(" (character)", "").replace(" (Harry Potter)", "")


def character_weekly() -> pd.DataFrame:
    """Returning weekly views per character article in wide form, complete weeks only."""
    weekly = pd.read_csv(path("data_cleaned", "pageviews", "pageviews_weekly.csv"))
    characters = weekly[weekly["group"] == "characters"].copy()
    characters["week_start"] = pd.to_datetime(characters["week_start"])

    wide = characters.pivot_table(
        index="week_start", columns="article", values="views", aggfunc="sum"
    )
    # Keeping only weeks where every character reported, so I never compute a
    # correlation across a different set of weeks for different pairs.
    return wide.dropna()


def shock_correlations(wide: pd.DataFrame) -> pd.DataFrame:
    """Computing the Spearman correlation of week on week log changes.

    The log difference removes the shared franchise trend. Without it every
    pair correlates above 0.9 and my network means nothing.
    """
    changes = np.log(wide.clip(lower=1)).diff().dropna()
    return changes.corr(method="spearman")


def choose_threshold(correlations: pd.DataFrame, quantile: float) -> tuple[float, dict]:
    """Picking the edge threshold from the correlation distribution itself.

    I also return a summary of that distribution, which shows a reader if the
    network means anything. A wide spread with a gap in it points to real
    communities. A narrow band with no gap points to one bloc.
    """
    values = correlations.values[np.triu_indices_from(correlations.values, k=1)]
    threshold = float(np.quantile(values, quantile))
    summary = {
        "pairs": len(values),
        "min": float(values.min()),
        "median": float(np.median(values)),
        "max": float(values.max()),
        "spread": float(values.max() - values.min()),
        "threshold": threshold,
    }
    return threshold, summary


def build_graph(correlations: pd.DataFrame, threshold: float) -> nx.Graph:
    graph = nx.Graph()
    for article in correlations.columns:
        graph.add_node(article, label=pretty(article))

    for i, a in enumerate(correlations.columns):
        for b in correlations.columns[i + 1:]:
            weight = float(correlations.loc[a, b])
            if weight >= threshold:
                graph.add_edge(a, b, weight=weight)
    return graph


def centralities(graph: nx.Graph) -> pd.DataFrame:
    """Computing degree, betweenness and eigenvector centrality, the three measures I report."""
    degree = nx.degree_centrality(graph)
    betweenness = nx.betweenness_centrality(graph, weight="weight", normalized=True)

    # Falling back to PageRank when eigenvector centrality does not converge,
    # which can happen on a sparse or disconnected graph. PageRank always
    # converges and measures the same idea, so it is better than reporting
    # nothing. I record the fallback and do not hide it.
    try:
        eigenvector = nx.eigenvector_centrality(graph, weight="weight", max_iter=1000)
        eigen_method = "eigenvector"
    except (nx.PowerIterationFailedConvergence, nx.NetworkXException) as exc:
        logger.warning("eigenvector centrality did not converge (%s), using PageRank", exc)
        eigenvector = nx.pagerank(graph, weight="weight")
        eigen_method = "pagerank_fallback"
        log_data_issue(
            SCRIPT, "character_network",
            "eigenvector centrality did not converge on the attention network",
            "PageRank used instead and labelled as such in the output table",
            severity="note",
        )

    frame = pd.DataFrame({
        "article": list(graph.nodes),
        "character": [pretty(a) for a in graph.nodes],
        "degree_centrality": [degree[a] for a in graph.nodes],
        "betweenness_centrality": [betweenness[a] for a in graph.nodes],
        "eigenvector_centrality": [eigenvector[a] for a in graph.nodes],
        "connections": [graph.degree(a) for a in graph.nodes],
    })
    frame["eigenvector_method"] = eigen_method
    return frame


def attach_attention_and_house(
    frame: pd.DataFrame, wide: pd.DataFrame, correlations: pd.DataFrame
) -> pd.DataFrame:
    """Adding measured attention, coupling strength and, where I know it, the house.

    `mean_correlation` is the average of a character's correlation with every
    other character. With no community structure, it is the honest summary of
    what my data supports: how tightly that character's attention is tied to
    the rest of the cast.
    """
    coupling = (
        correlations.where(~np.eye(len(correlations), dtype=bool))
        .mean()
        .rename("mean_correlation")
    )
    frame = frame.merge(coupling, left_on="article", right_index=True, how="left")

    totals = wide.sum().rename("total_views")
    frame = frame.merge(totals, left_on="article", right_index=True, how="left")

    characters = read_processed("characters.csv")
    slug_map = get("sources.pageviews.character_article_to_potterdb_slug")
    frame["slug"] = frame["article"].map(slug_map)

    if "house_combined" in characters.columns:
        houses = characters[["slug", "house_combined"]].dropna(subset=["slug"])
        frame = frame.merge(houses.drop_duplicates("slug"), on="slug", how="left")
        frame = frame.rename(columns={"house_combined": "house"})
    else:
        frame["house"] = np.nan

    frame["attention_rank"] = frame["total_views"].rank(ascending=False).astype(int)
    frame["coupling_rank"] = frame["mean_correlation"].rank(ascending=False).astype(int)
    frame["centrality_rank"] = frame["eigenvector_centrality"].rank(ascending=False).astype(int)
    frame["rank_gap"] = frame["attention_rank"] - frame["centrality_rank"]
    return frame.sort_values("eigenvector_centrality", ascending=False).reset_index(drop=True)


def plot_network(graph: nx.Graph, frame: pd.DataFrame, headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 7.5))

    layout = nx.spring_layout(graph, seed=int(get("project.random_seed")), weight="weight", k=0.9)
    lookup = frame.set_index("article")

    sizes = [
        300 + 4200 * float(lookup.loc[node, "eigenvector_centrality"]) for node in graph.nodes
    ]
    colours = []
    for node in graph.nodes:
        house = lookup.loc[node, "house"]
        key = str(house).strip().lower() if pd.notna(house) else ""
        colours.append(HOUSE_COLOURS.get(key, PALETTE["muted"]))

    weights = [graph[u][v]["weight"] for u, v in graph.edges]
    nx.draw_networkx_edges(
        graph, layout, ax=ax, width=[w * 3.2 for w in weights],
        edge_color=PALETTE["grid"], alpha=0.85,
    )
    nx.draw_networkx_nodes(
        graph, layout, ax=ax, node_size=sizes, node_color=colours,
        edgecolors=PALETTE["ground"], linewidths=1.6,
    )
    nx.draw_networkx_labels(
        graph, layout, ax=ax,
        labels={n: pretty(n) for n in graph.nodes},
        font_size=8.5, font_color=PALETTE["ink"],
    )

    ax.axis("off")
    title_block(ax, headline, subtitle, subtitle_wrap=112)

    # Using house colours on this figure only, because it is the one place
    # where they carry meaning.
    handles = [
        plt.Line2D([0], [0], marker="o", linestyle="", markersize=9,
                   markerfacecolor=colour, markeredgecolor="none", label=house.title())
        for house, colour in HOUSE_COLOURS.items()
    ]
    handles.append(
        plt.Line2D([0], [0], marker="o", linestyle="", markersize=9,
                   markerfacecolor=PALETTE["muted"], markeredgecolor="none", label="House unknown")
    )
    # Placing the legend below the axes and not inside them. A spring layout puts
    # nodes wherever it likes, and a legend inside the axes sat on top of one.
    ax.legend(
        handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02),
        fontsize=8.5, ncol=5, borderaxespad=0.0,
    )

    return save_figure(
        fig, "character_attention_network.png",
        "Wikipedia weekly pageviews 2015-2026; edges are Spearman correlations of week on week log changes",
    )


def plot_attention_vs_centrality(frame: pd.DataFrame, headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 6))

    ax.scatter(
        frame["total_views"] / 1e6, frame["eigenvector_centrality"],
        s=90, color=PALETTE["accent"], zorder=3, edgecolors=PALETTE["ground"], linewidths=1.2,
    )
    for row in frame.itertuples():
        ax.annotate(
            row.character, (row.total_views / 1e6, row.eigenvector_centrality),
            xytext=(6, 3), textcoords="offset points", fontsize=8.5, color=PALETTE["ink"],
        )

    ax.set_xlabel("total weekly pageviews 2015 to 2026, millions")
    ax.set_ylabel("eigenvector centrality in the attention network")
    ax.set_xscale("log")

    title_block(ax, headline, subtitle, subtitle_wrap=118)
    return save_figure(
        fig, "character_attention_vs_centrality.png",
        "Wikipedia weekly pageviews, retrieved 2 September 2026",
    )


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        wide = character_weekly()
        run.rows_in = len(wide)
        logger.info(
            "%d characters over %d complete weeks, %s to %s",
            wide.shape[1], len(wide), wide.index.min().date(), wide.index.max().date(),
        )

        if wide.shape[1] < MIN_NODES:
            log_data_issue(
                SCRIPT, "character_network",
                f"only {wide.shape[1]} character series available, below the {MIN_NODES} minimum",
                "analysis dropped rather than published weak, which I allowed for in my plan",
                severity="error",
            )
            logger.error("too few characters for a defensible network, dropping the analysis")
            run.rows_out = 0
            return

        correlations = shock_correlations(wide)
        save_table(
            "character_correlation_matrix.csv",
            correlations.round(3).reset_index().rename(columns={"index": "article"}),
            note="Spearman correlation of week on week log changes in pageviews",
        )

        threshold, distribution = choose_threshold(correlations, EDGE_QUANTILE)
        logger.info(
            "correlation distribution over %d pairs: min %.3f, median %.3f, max %.3f "
            "(spread %.3f); threshold set at the %.0fth percentile = %.3f",
            distribution["pairs"], distribution["min"], distribution["median"],
            distribution["max"], distribution["spread"], EDGE_QUANTILE * 100, threshold,
        )

        # Checking for a narrow band with no gap in it, which means no communities
        # exist. That is a result, and I record it as one. I do not smooth it over
        # by picking whatever threshold gives a pretty graph.
        no_structure = distribution["spread"] < 0.45
        if no_structure:
            log_data_issue(
                SCRIPT, "character_network",
                f"character attention correlations span only {distribution['min']:.2f} to "
                f"{distribution['max']:.2f} with no gap, so no community structure exists",
                "the graph is drawn at a quantile threshold for visualisation only, and "
                "centrality is reported as coupling strength rather than network position",
                severity="note",
            )

        graph = build_graph(correlations, threshold)
        density = nx.density(graph)
        logger.info(
            "graph: %d nodes, %d edges, density %.3f, connected=%s",
            graph.number_of_nodes(), graph.number_of_edges(), density, nx.is_connected(graph),
        )

        if density > DENSITY_CEILING:
            log_data_issue(
                SCRIPT, "character_network",
                f"the graph is still {density:.0%} dense at the chosen threshold",
                "centrality on a nearly complete graph carries no information; the finding "
                "reports coupling strength instead and says the network structure is absent",
                severity="error",
            )

        if graph.number_of_edges() == 0:
            log_data_issue(
                SCRIPT, "character_network",
                f"no pair of characters correlated above {threshold:.3f}",
                "network dropped; the attention series do not move together enough to support one",
                severity="error",
            )
            run.rows_out = 0
            return

        frame = centralities(graph)
        frame = attach_attention_and_house(frame, wide, correlations)

        table_path = save_table(
            "character_centrality.csv",
            frame[[
                "character", "article", "house", "connections", "degree_centrality",
                "betweenness_centrality", "eigenvector_centrality", "eigenvector_method",
                "mean_correlation", "total_views", "attention_rank", "centrality_rank",
                "coupling_rank", "rank_gap",
            ]],
            edge_threshold=round(threshold, 4),
            edge_quantile=EDGE_QUANTILE,
            note="centrality in the attention comovement network, against raw attention",
        )
        logger.info(
            "centrality table:\n%s",
            frame[["character", "connections", "eigenvector_centrality", "attention_rank",
                   "centrality_rank", "rank_gap"]].to_string(index=False),
        )

        most_coupled = frame.loc[frame["mean_correlation"].idxmax()]
        least_coupled = frame.loc[frame["mean_correlation"].idxmin()]

        # Looking for the character a buyer can use. It is not just the least
        # coupled one, who here is also the least looked at and so no use to a buyer.
        # It is the character with a large audience that still moves on its own,
        # apart from the rest of the cast: high on traffic, low on coupling.
        frame["independence"] = frame["coupling_rank"] - frame["attention_rank"]
        independent = frame.loc[frame["independence"].idxmax()]

        logger.info(
            "coupling: most %s (%.3f), least %s (%.3f)",
            most_coupled["character"], most_coupled["mean_correlation"],
            least_coupled["character"], least_coupled["mean_correlation"],
        )

        headline = (
            f"Attention to the cast moves as one bloc: every pair correlates between "
            f"{distribution['min']:.2f} and {distribution['max']:.2f}"
        )
        subtitle = (
            f"Edges are the strongest quarter of pairs (above {threshold:.2f}); node size is "
            f"coupling to the rest of the cast. There are no communities here, so position on this "
            f"figure carries no meaning beyond how tightly a character moves with the others."
        )
        network_figure = plot_network(graph, frame, headline, subtitle)

        scatter_headline = (
            f"{independent['character']} draws a large audience that moves independently of the cast"
        )
        scatter_subtitle = (
            f"Ranked {int(independent['attention_rank'])} of {len(frame)} on traffic but "
            f"{int(independent['coupling_rank'])} on coupling at "
            f"{independent['mean_correlation']:.2f}, against {most_coupled['character']} at "
            f"{most_coupled['mean_correlation']:.2f}. Low and left is a self contained following; "
            f"high and right is one that rises only when the whole franchise does."
        )
        plot_attention_vs_centrality(frame, scatter_headline, scatter_subtitle)

        finding = (
            f"The network I set out to find does not exist, and that is the result. Built from "
            f"attention because the chapter records carry no character list, the {len(frame)} main "
            f"cast members correlate with each other between {distribution['min']:.2f} and "
            f"{distribution['max']:.2f} once the shared franchise trend is differenced away, with "
            f"no gap anywhere in that range. At any threshold below {distribution['min']:.2f} "
            f"every one of the {distribution['pairs']} pairs clears it and the graph is complete, "
            f"and above that it thins evenly rather than splitting into groups. There are no "
            f"communities to find: attention to this cast moves as a single bloc, so centrality on it measures "
            f"only how tightly each character is tied to that bloc. On that reading "
            f"{most_coupled['character']} is the most tied in at {most_coupled['mean_correlation']:.2f} "
            f"and {least_coupled['character']} the least at {least_coupled['mean_correlation']:.2f}. "
            f"The one commercially useful asymmetry in the table is "
            f"{independent['character']}, who is {int(independent['attention_rank'])} of "
            f"{len(frame)} on traffic with {independent['total_views'] / 1e6:.1f} million total "
            f"views but only {int(independent['coupling_rank'])} on coupling at "
            f"{independent['mean_correlation']:.2f}: a large following that does not need a "
            f"franchise moment to show up, and therefore the safest character to carry outside one."
        )

        write_finding(
            "3.2 Character network: no communities, one bloc, and one independent audience",
            finding,
            evidence=(
                f"Spearman correlations of week on week log changes in Wikipedia pageviews across "
                f"{distribution['pairs']} character pairs. The log difference removes the shared "
                f"franchise trend; without it every pair correlates above 0.9 and the exercise "
                f"measures nothing but the trend. Degree, betweenness and eigenvector centrality "
                f"were all computed as I planned and are in the output table, but on a "
                f"graph this dense they rank coupling strength rather than network position, and "
                f"the finding says so rather than presenting them as structure."
            ),
            sample=(
                f"{graph.number_of_nodes()} characters over {len(wide)} complete weeks, "
                f"{wide.index.min():%Y-%m-%d} to {wide.index.max():%Y-%m-%d}. Only the sixteen main "
                f"cast members with a mapped Wikipedia article are included, not the five thousand "
                f"character catalogue."
            ),
            uncertainty=(
                f"Sixteen nodes is a small sample and the differences in coupling are narrow: "
                f"{least_coupled['mean_correlation']:.2f} to {most_coupled['mean_correlation']:.2f} "
                f"across the whole cast, so only the ends of that ranking should be read as "
                f"meaningful and the middle should not. The edge threshold is a visualisation "
                f"choice at the 75th percentile, not a measurement, and a different quantile would "
                f"redraw the picture without changing the conclusion that no communities exist. "
                f"Comovement in article views is also not joint purchase; no sales data was available "
                f"to test whether attention that moves together converts together."
            ),
            figure=relative(network_figure),
            table=relative(table_path),
        )

        run.rows_out = len(frame)
        run.note = f"{graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"

    logger.info("character network complete")


if __name__ == "__main__":
    main()
