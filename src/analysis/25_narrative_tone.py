"""Module 3.1. Narrative tone and character presence, and what season one contains.

Reads  : data/cleaned/potterdb/chapters.csv, data/processed/characters.csv
Writes : images/figures/narrative_tone_by_book.png
         images/figures/character_presence_vs_attention.png
         outputs/tables/narrative_tone_by_chapter.csv
         outputs/tables/character_presence_by_book.csv
         docs/findings.md (one entry)
Runtime: about fifteen seconds.

The brief's module 3.1 asks for sentiment over time across fan reviews and
discussion posts, plotted against a timeline of franchise announcements. That
corpus was never collected, for want of Reddit credentials, so the analysis as
specified cannot be run and is not pretended.

What replaces it uses text the project already holds and answers a question the
buyer actually has. The new series adapts one book per season, and season one is
Philosopher's Stone. So two things about that book are worth knowing before
committing a buy: how dark it is compared with the rest of the series, and which
characters are actually in it.

The second is the commercially useful half. A character who draws heavy
attention today but does not appear until book four is a poor bet for a season
one buy, however popular they are, because the season will not put them on
screen. That is a stocking decision that follows directly from the data.

Two methods, both with real limits.

Tone is scored with VADER, a lexicon method. There is no trained sentiment
classifier here as a check, because checking a lexicon against a trained model
needs labelled sentiment data and this project has none: labelling chapters by
hand would be inventing the ground truth then marking my own work. Module 5.4
demonstrates a trained text classifier on data that does have real labels.

Character presence is name matching against chapter summaries, which the brief
allows as its first workaround and requires be described as approximate. It is
approximate in a specific direction: a character mentioned in a summary is
present, but a character present in a chapter the summary does not mention will
be missed. So presence counts here are a floor, not a measurement.

The summaries are fan-written encyclopedia text from PotterDB, not the novels.
Section 6 forbids storing the text of the books, and nothing here does.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from src.utils.config import path
from src.utils.io import read_processed, relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import PALETTE, apply_style, save_figure, title_block

SCRIPT = "25_narrative_tone"
logger = get_logger(SCRIPT)

# Reading order. PotterDB gives each book a slug but not a series position, and
# alphabetical order would put Chamber of Secrets before Philosopher's Stone.
BOOK_ORDER = [
    "harry-potter-and-the-philosopher-s-stone",
    "harry-potter-and-the-chamber-of-secrets",
    "harry-potter-and-the-prisoner-of-azkaban",
    "harry-potter-and-the-goblet-of-fire",
    "harry-potter-and-the-order-of-the-phoenix",
    "harry-potter-and-the-half-blood-prince",
    "harry-potter-and-the-deathly-hallows",
]

SHORT_TITLES = {
    "harry-potter-and-the-philosopher-s-stone": "1. Philosopher's Stone",
    "harry-potter-and-the-chamber-of-secrets": "2. Chamber of Secrets",
    "harry-potter-and-the-prisoner-of-azkaban": "3. Prisoner of Azkaban",
    "harry-potter-and-the-goblet-of-fire": "4. Goblet of Fire",
    "harry-potter-and-the-order-of-the-phoenix": "5. Order of the Phoenix",
    "harry-potter-and-the-half-blood-prince": "6. Half-Blood Prince",
    "harry-potter-and-the-deathly-hallows": "7. Deathly Hallows",
}


def load_chapters() -> pd.DataFrame:
    chapters = pd.read_csv(path("data_cleaned", "potterdb", "chapters.csv"))
    chapters = chapters.dropna(subset=["summary"])
    chapters = chapters[chapters["summary"].str.strip().str.len() > 50]

    chapters["book_position"] = chapters["book_slug"].map(
        {slug: i + 1 for i, slug in enumerate(BOOK_ORDER)}
    )
    unknown = chapters[chapters["book_position"].isna()]["book_slug"].unique()
    if len(unknown):
        log_data_issue(
            SCRIPT, "narrative_tone",
            f"chapters found under unrecognised book slugs: {', '.join(map(str, unknown))}",
            "those chapters were dropped; add the slug to BOOK_ORDER to include them",
        )
    chapters = chapters.dropna(subset=["book_position"])
    chapters["book_position"] = chapters["book_position"].astype(int)
    chapters["book_label"] = chapters["book_slug"].map(SHORT_TITLES)

    # PotterDB carries chapter summaries for the first book only. The other 182
    # chapter records exist but their summary field is empty, which was found by
    # running this and getting 17 chapters back instead of 199. It is a source
    # limitation, not a filter bug, and it caps what this module can claim.
    books_with_text = chapters["book_position"].nunique()
    if books_with_text < len(BOOK_ORDER):
        log_data_issue(
            SCRIPT, "narrative_tone",
            f"chapter summaries exist for only {books_with_text} of {len(BOOK_ORDER)} books; "
            f"{len(chapters)} chapters carry usable text",
            "the tone arc across the series cannot be measured. The analysis is limited to the "
            "book that has text, which is the one season one adapts, and says so.",
            severity="error",
        )

    return chapters.sort_values(["book_position", "order"]).reset_index(drop=True)


def score_tone(chapters: pd.DataFrame) -> pd.DataFrame:
    """VADER compound sentiment per chapter summary.

    The compound score runs from -1 to +1. On encyclopedic summaries it is
    measuring the tone of the described events, not an opinion about them, which
    is the right reading here: a chapter where someone dies scores negative
    because the summary contains words about dying.
    """
    analyzer = SentimentIntensityAnalyzer()
    scores = chapters["summary"].map(lambda text: analyzer.polarity_scores(str(text)))

    chapters = chapters.copy()
    chapters["tone_compound"] = [s["compound"] for s in scores]
    chapters["tone_positive"] = [s["pos"] for s in scores]
    chapters["tone_negative"] = [s["neg"] for s in scores]
    chapters["summary_words"] = chapters["summary"].str.split().str.len()
    chapters["chapter_index"] = range(1, len(chapters) + 1)
    return chapters


def character_presence(chapters: pd.DataFrame) -> pd.DataFrame:
    """Approximate character presence per book, by name matching in summaries.

    Matching is on the character's common first name or surname as it appears in
    the article title, not on the PotterDB canonical full name, because a
    summary says "Hermione" and never "Hermione Jean Granger". Word boundaries
    are enforced so that "Ron" does not match inside "Ronan".
    """
    characters = read_processed("characters.csv")
    mapped = characters[characters["total_weekly_views"].notna()].copy()

    rows = []
    for character in mapped.itertuples():
        article = str(character.article)
        display = (
            article.replace("_", " ")
            .replace(" (character)", "")
            .replace(" (Harry Potter)", "")
        )
        # Match on any word of the display name that is distinctive enough. A
        # two-letter token would match everywhere, so short tokens are skipped.
        tokens = [t for t in display.split() if len(t) >= 4]
        if not tokens:
            tokens = [display]
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(t) for t in tokens) + r")\b", re.IGNORECASE
        )

        for book_position in sorted(chapters["book_position"].unique()):
            book_chapters = chapters[chapters["book_position"] == book_position]
            hits = book_chapters["summary"].str.contains(pattern, regex=True).sum()
            rows.append({
                "character": display,
                "article": article,
                "book_position": int(book_position),
                "book_label": SHORT_TITLES[BOOK_ORDER[book_position - 1]],
                "chapters_mentioned": int(hits),
                "chapters_in_book": len(book_chapters),
                "share_of_chapters": round(hits / len(book_chapters), 3),
                "total_weekly_views": character.total_weekly_views,
            })

    return pd.DataFrame(rows)


def plot_tone(chapters: pd.DataFrame, by_book: pd.DataFrame, headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 5.8))

    ax.plot(
        chapters["chapter_index"], chapters["tone_compound"],
        color=PALETTE["grid"], linewidth=1.0, zorder=1,
    )

    # A rolling mean makes the arc readable; the raw series is noisy per chapter.
    rolling = chapters["tone_compound"].rolling(9, center=True, min_periods=3).mean()
    ax.plot(chapters["chapter_index"], rolling, color=PALETTE["accent"], linewidth=2.4, zorder=3)

    ax.axhline(0, color=PALETTE["ink"], linewidth=1.0, linestyle="--", zorder=2)

    # Book boundaries, so the arc can be read against the series structure.
    boundaries = chapters.groupby("book_position")["chapter_index"].agg(["min", "max"])
    for position, row in boundaries.iterrows():
        if position > 1:
            ax.axvline(row["min"] - 0.5, color=PALETTE["grid"], linewidth=1.2, zorder=0)
        mean_tone = float(by_book.loc[by_book["book_position"] == position, "mean_tone"].iloc[0])
        ax.text(
            (row["min"] + row["max"]) / 2, ax.get_ylim()[1] * 0.94, str(position),
            ha="center", va="top", fontsize=10, color=PALETTE["muted"],
        )
        ax.plot(
            [row["min"], row["max"]], [mean_tone, mean_tone],
            color=PALETTE["support"], linewidth=2.6, solid_capstyle="butt", zorder=4,
        )

    ax.set_xlabel("chapter, in reading order across the seven books")
    ax.set_ylabel("VADER compound tone, -1 to +1")
    title_block(ax, headline, subtitle, subtitle_wrap=112)
    return save_figure(
        fig, "narrative_tone_by_book.png",
        "VADER sentiment over PotterDB chapter summaries; book means in teal",
    )


def plot_presence(presence: pd.DataFrame, headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(11, 6.2))

    book_one = presence[presence["book_position"] == 1].copy()
    book_one = book_one.sort_values("total_weekly_views", ascending=False)

    colours = [
        PALETTE["accent"] if share > 0 else PALETTE["muted"]
        for share in book_one["share_of_chapters"]
    ]
    ax.barh(
        book_one["character"], book_one["total_weekly_views"] / 1e6,
        color=colours, height=0.68,
    )

    for i, row in enumerate(book_one.itertuples()):
        label = (
            f"{row.share_of_chapters:.0%} of chapters"
            if row.chapters_mentioned else "not in book 1"
        )
        ax.text(
            row.total_weekly_views / 1e6 + 0.15, i, label,
            va="center", fontsize=8.5,
            color=PALETTE["ink"] if row.chapters_mentioned else PALETTE["muted"],
        )

    ax.invert_yaxis()
    ax.set_xlabel("total weekly pageviews 2015 to 2026, millions")
    ax.set_xlim(0, book_one["total_weekly_views"].max() / 1e6 * 1.28)
    title_block(ax, headline, subtitle, subtitle_wrap=112)
    return save_figure(
        fig, "character_presence_vs_attention.png",
        "Wikipedia pageviews and PotterDB chapter summaries; presence is approximate name matching",
    )


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        chapters = load_chapters()
        chapters = score_tone(chapters)
        run.rows_in = len(chapters)

        logger.info(
            "%d chapters across %d books, median summary %d words",
            len(chapters), chapters["book_position"].nunique(),
            int(chapters["summary_words"].median()),
        )

        by_book = (
            chapters.groupby(["book_position", "book_label"], as_index=False)
            .agg(
                chapters=("tone_compound", "count"),
                mean_tone=("tone_compound", "mean"),
                sd_tone=("tone_compound", "std"),
                darkest_chapter_tone=("tone_compound", "min"),
            )
            .sort_values("book_position")
        )
        by_book["mean_tone"] = by_book["mean_tone"].round(3)
        by_book["sd_tone"] = by_book["sd_tone"].round(3)
        logger.info("tone by book:\n%s", by_book.to_string(index=False))

        tone_table = save_table(
            "narrative_tone_by_chapter.csv",
            chapters[[
                "book_position", "book_label", "order", "title", "chapter_index",
                "tone_compound", "tone_positive", "tone_negative", "summary_words",
            ]],
            note="VADER compound tone per chapter summary, reading order",
        )
        save_table("narrative_tone_by_book.csv", by_book)

        presence = character_presence(chapters)
        presence_table = save_table(
            "character_presence_by_book.csv", presence,
            note="approximate: name matching against chapter summaries, a floor not a measurement",
        )

        book_one = presence[presence["book_position"] == 1]
        absent = book_one[book_one["chapters_mentioned"] == 0].sort_values(
            "total_weekly_views", ascending=False
        )
        present = book_one[book_one["chapters_mentioned"] > 0]

        book_one_tone = float(by_book.loc[by_book["book_position"] == 1, "mean_tone"].iloc[0])
        darkest = by_book.loc[by_book["mean_tone"].idxmin()]
        lightest = by_book.loc[by_book["mean_tone"].idxmax()]

        logger.info(
            "book 1 mean tone %.3f (lightest is book %d at %.3f, darkest book %d at %.3f)",
            book_one_tone, int(lightest["book_position"]), lightest["mean_tone"],
            int(darkest["book_position"]), darkest["mean_tone"],
        )
        logger.info(
            "of %d mapped characters, %d appear in book 1 and %d do not",
            len(book_one), len(present), len(absent),
        )
        if len(absent):
            logger.info(
                "highest-attention characters absent from book 1:\n%s",
                absent[["character", "total_weekly_views"]].head(5).to_string(index=False),
            )

        # A known false negative, checked by hand. Neville Longbottom is in book
        # one, but none of the seventeen available summaries names him. Naming it
        # is better than letting a reader discover the method is fallible by
        # spotting an error nobody flagged.
        known_false_negatives = ["Neville Longbottom"]
        flagged = [c for c in known_false_negatives if c in set(absent["character"])]

        tone_headline = (
            f"Within book one, tone swings from {chapters['tone_compound'].max():+.2f} to "
            f"{chapters['tone_compound'].min():+.2f} across its {len(chapters)} chapters"
        )
        tone_subtitle = (
            f"VADER compound tone per chapter summary, in order. Grey is the raw series, red a "
            f"nine-chapter rolling mean, teal the book mean of {book_one_tone:+.2f}. Summaries "
            f"exist for this book only, so no cross-book arc can be measured."
        )
        tone_figure = plot_tone(chapters, by_book, tone_headline, tone_subtitle)

        presence_headline = (
            f"{len(absent)} of the {len(book_one)} best-known characters are never named in "
            f"book one's summaries"
        )
        presence_subtitle = (
            "Bars are total attention 2015 to 2026; red means the character is named in "
            "Philosopher's Stone chapter summaries, grey means they are not. Season one adapts "
            "that book, so grey is attention a season one range is less able to convert."
        )
        presence_figure = plot_presence(presence, presence_headline, presence_subtitle)

        absent_views = float(absent["total_weekly_views"].sum()) if len(absent) else 0.0
        total_views = float(book_one["total_weekly_views"].sum())
        absent_names = ", ".join(absent["character"].head(3)) if len(absent) else "none"

        false_negative_note = (
            f" That list is not perfectly reliable: {flagged[0]} is in book one but is named in "
            f"none of the seventeen summaries, so the method misses him."
            if flagged else ""
        )

        finding = (
            f"Season one adapts Philosopher's Stone, and that constrains a season one buy in a way "
            f"attention data alone does not show. Of the {len(book_one)} main characters with "
            f"measured attention, {len(absent)} are never named in that book's chapter summaries, "
            f"and they carry {absent_views / total_views:.0%} of the cast's total attention "
            f"between them, led by {absent_names}.{false_negative_note} Tone within the book runs "
            f"positive on average at {book_one_tone:+.2f} with the darkest chapter at "
            f"{chapters['tone_compound'].min():+.2f}, so a season one range should skew to the "
            f"lighter, younger end of the line rather than to the darker characters that dominate "
            f"current search attention."
        )

        write_finding(
            "3.1 Narrative tone and season one: which characters the first season can sell",
            finding,
            evidence=(
                f"VADER lexicon sentiment over {len(chapters)} PotterDB chapter summaries, plus "
                f"character presence from case-insensitive word-boundary name matching in those "
                f"summaries, joined to measured Wikipedia attention per character."
            ),
            sample=(
                f"{len(chapters)} chapters, all from book one, median "
                f"{int(chapters['summary_words'].median())} words per summary. "
                f"{len(book_one)} characters, being those with both a mapped Wikipedia article "
                f"and measured attention."
            ),
            uncertainty=(
                "The sample is the headline limitation. PotterDB carries chapter summaries for "
                "book one only: the other 182 chapter records exist with an empty summary field, "
                "so the tone arc across the series that this module set out to measure cannot be "
                "measured at all, and only the book season one adapts has any text. "
                "Seventeen short summaries are also a thin basis for character presence, and the "
                "method has a demonstrated false negative in Neville Longbottom, who is in the "
                "book but is named in none of them. Presence is therefore a floor rather than a "
                "measurement, and the absent list should be read as 'not prominent enough to reach "
                "a summary' rather than 'not in the book'. "
                "This is also not the analysis module 3.1 specifies, which needs fan review text "
                "scored over calendar time against an announcement timeline; that corpus was never "
                "collected for want of Reddit credentials. No trained classifier checks the "
                "lexicon either, because that needs labelled sentiment data this project does not "
                "have, and hand-labelling would mean inventing the ground truth then marking my "
                "own work. Module 5.4 demonstrates a trained classifier on data with real labels. "
                "VADER is tuned for social media rather than encyclopedic prose, so tone values "
                "are best read relatively."
            ),
            figure=relative(presence_figure),
            table=relative(presence_table),
        )

        run.rows_out = len(chapters) + len(presence)
        run.note = f"{len(absent)} of {len(book_one)} characters absent from book 1"
        logger.info("saved %s and %s", relative(tone_table), relative(tone_figure))

    logger.info("narrative tone analysis complete")


if __name__ == "__main__":
    main()
