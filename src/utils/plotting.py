"""Setting one palette and one chart style for my whole project.

Reading: nothing at import time.
Writing: figures, through `save_figure`, only into images/figures.
Runtime: instant.

I want my dashboard, my infographic and my report figures to share one palette,
and I do not want the four saturated house colours used as a chart palette. I
declare the values once here and once in web/css/base.css, and the two must stay
the same. Nothing else in my project may name a colour.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

# Using a dark turquoise accent on a near white ground, with one deep blue for a
# second series and a warm gold kept for the premiere line. I kept it calm on
# purpose. My charts have to stay readable when printed small on a one page
# infographic, and turquoise against gold makes the premiere date, the one thing
# that matters, easy to tell apart from everything else at a glance.
# I chose gold and not a second cool colour for the highlight, because it is the
# only warm colour in my palette, so nothing else on a chart can be mistaken for it.
PALETTE = {
    "ink": "#10262B",          # Colouring text and axes, a near black with a teal cast
    "ground": "#FFFFFF",       # Filling the figure background
    "ground_alt": "#F1F7F8",   # Filling panels
    "grid": "#D9E4E7",
    "muted": "#5F7A80",        # Colouring secondary text, baselines and context series
    "accent": "#0E7C86",       # Using dark turquoise for my main series
    "accent_soft": "#93C9CF",  # Shading confidence bands and fills
    "support": "#14405C",      # Using deep blue for my one contrasting series
    "support_soft": "#9FB4C4",
    "highlight": "#C9932B",    # Using warm gold sparingly, for the premiere line and callouts
    "warn": "#8A6412",
}

# Listing my series colours in order. I allow at most four in any one chart, on purpose.
SERIES = [PALETTE["accent"], PALETTE["support"], PALETTE["muted"], PALETTE["highlight"]]

# Keeping the four house colours for my segmentation figure only, where the
# colour carries meaning. I never use them as a general chart palette.
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
    """Setting the matplotlib defaults that every figure in my project uses."""
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
    """Putting the finding in the title and the method under it.

    I want every figure to state a finding, not just name a variable. I draw both
    lines as axes text and not with set_title, because set_title uses a fixed
    offset and the two lines can end up printed on top of each other. Drawing the
    subtitle first and the title above it keeps them apart at any figure size.
    I wrap a long subtitle so it does not run past the axes.
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
    """Drawing the premiere date on any time axis, always the same way."""
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
    """Adding a footer with the source and the retrieval date to every figure I export."""
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
    """Saving a figure to images/figures and closing it.

    I import io here and not at the top of the file, so I can use `plotting` from
    a notebook without pulling in my file placement rules.
    """
    from .io import figure_path

    if source:
        source_note(fig, source)
    target = figure_path(filename)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(target, bbox_inches="tight")
    plt.close(fig)
    return target
