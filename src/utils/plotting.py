"""One palette and one chart style for the whole project.

Reads  : nothing at import time.
Writes : figures, through `save_figure`, only into images/figures.
Runtime: instant.

Section 15 of the brief requires the dashboard, the infographic and the report
figures to share a palette, and warns against using four saturated house colours
as a chart palette. The values below are declared once here and once in
web/css/base.css, and the two must stay in step. Nothing else in the project may
name a colour.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

# A dark turquoise accent on a near-white ground, with one deep blue for a second
# series and a warm gold reserved for the premiere marker. Restrained on purpose:
# the charts have to stay readable when printed small on a one page infographic,
# and turquoise against gold keeps the one thing that matters, the premiere date,
# separable from everything else at a glance.
#
# Gold rather than a second cool colour for the highlight because it is the only
# warm note in the palette, so nothing else on a chart can be mistaken for it.
PALETTE = {
    "ink": "#10262B",          # text and axes, a near-black with a teal cast
    "ground": "#FFFFFF",       # figure background
    "ground_alt": "#F1F7F8",   # panel fills
    "grid": "#D9E4E7",
    "muted": "#5F7A80",        # secondary text, baselines, context series
    "accent": "#0E7C86",       # dark turquoise, carries the main series
    "accent_soft": "#93C9CF",  # confidence bands and fills
    "support": "#14405C",      # deep blue, the one contrasting series
    "support_soft": "#9FB4C4",
    "highlight": "#C9932B",    # warm gold, sparingly: premiere marker and callouts
    "warn": "#8A6412",
}

# Ordered series colours. Four is the deliberate maximum for any one chart.
SERIES = [PALETTE["accent"], PALETTE["support"], PALETTE["muted"], PALETTE["highlight"]]

# The four house colours. Reserved for the segmentation figure only, where the
# colour carries meaning. Never used as a general chart palette.
HOUSE_COLOURS = {
    "gryffindor": "#7B1E22",
    "slytherin": "#1E4D3A",
    "ravenclaw": "#22406B",
    "hufflepuff": "#B08A1E",
}

SCENARIO_COLOURS = {
    "low": PALETTE["muted"],
    "central": PALETTE["accent"],
    "high": PALETTE["support"],
}


def apply_style() -> None:
    """Set the matplotlib defaults every figure in the project inherits."""
    mpl.rcParams.update(
        {
            "figure.figsize": (10, 5.5),
            "figure.dpi": 110,
            "savefig.dpi": 200,
            "figure.facecolor": PALETTE["ground"],
            "axes.facecolor": PALETTE["ground"],
            "savefig.facecolor": PALETTE["ground"],
            "axes.edgecolor": PALETTE["grid"],
            "axes.labelcolor": PALETTE["ink"],
            "axes.titlecolor": PALETTE["ink"],
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.titlepad": 12,
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": PALETTE["grid"],
            "grid.linewidth": 0.8,
            "xtick.color": PALETTE["muted"],
            "ytick.color": PALETTE["muted"],
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "text.color": PALETTE["ink"],
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 1.8,
            "font.size": 10,
            "font.family": "sans-serif",
            "font.sans-serif": ["Segoe UI", "Calibri", "DejaVu Sans", "sans-serif"],
        }
    )


def title_block(ax, finding: str, subtitle: str = "", subtitle_wrap: int = 110) -> None:
    """Put the finding in the title and the method underneath it.

    The brief asks every figure to state a finding rather than name a variable.
    Both lines are drawn as axes text rather than through set_title, because
    set_title puts the title at a fixed offset and the subtitle then has to be
    positioned relative to a height nobody knows in advance, which is how the two
    end up printed on top of each other. Drawing both explicitly, subtitle first
    and title above it, keeps them apart at any figure size.

    A long subtitle is wrapped rather than allowed to run past the axes.
    """
    import textwrap

    if subtitle:
        wrapped = textwrap.fill(subtitle, subtitle_wrap)
        line_count = wrapped.count("\n") + 1
        ax.text(
            0.0, 1.015, wrapped,
            transform=ax.transAxes, fontsize=9.5, color=PALETTE["muted"],
            va="bottom", ha="left",
        )
        title_y = 1.015 + 0.030 * line_count
    else:
        title_y = 1.02

    ax.text(
        0.0, title_y, finding,
        transform=ax.transAxes, fontsize=13, fontweight="bold",
        color=PALETTE["ink"], va="bottom", ha="left",
    )


def mark_premiere(ax, premiere_date, label: str = "Premiere 25 Dec 2026") -> None:
    """Draw the premiere date on any time axis, always the same way."""
    ax.axvline(premiere_date, color=PALETTE["highlight"], linewidth=1.6, linestyle="--", zorder=1)
    ax.annotate(
        label,
        xy=(premiere_date, ax.get_ylim()[1]),
        xytext=(4, -12),
        textcoords="offset points",
        fontsize=8.5,
        color=PALETTE["warn"],
        ha="left",
        va="top",
    )


def source_note(fig, text: str) -> None:
    """Footer giving the source and the retrieval date, on every exported figure."""
    fig.text(
        0.01,
        0.005,
        text,
        fontsize=7.5,
        color=PALETTE["muted"],
        ha="left",
        va="bottom",
    )


def save_figure(fig, filename: str, source: str = "") -> Path:
    """Write a figure to images/figures and close it.

    Importing io here rather than at module scope keeps `plotting` usable from a
    notebook without dragging in the placement rules.
    """
    from .io import figure_path

    if source:
        source_note(fig, source)
    target = figure_path(filename)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(target, bbox_inches="tight")
    plt.close(fig)
    return target
