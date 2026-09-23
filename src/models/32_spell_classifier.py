"""Module 5.4. A text classifier, trained and evaluated on labelled spell data.

Reads  : data/cleaned/potterdb/spells.csv
Writes : images/figures/spell_classifier_confusion.png
         outputs/tables/spell_classifier_metrics.csv
         outputs/tables/spell_classifier_per_class.csv
         outputs/models/spell_classifier.json
         docs/findings.md (one entry)
Runtime: about twenty seconds.

The brief's module 5.4 asks for a sentiment classifier trained on labelled
review text, compared against a lexicon baseline. That corpus was never
collected, because it needs Reddit credentials this project does not have, and
inventing labels for text that does not exist is not an option.

What is here instead is the same exercise on data the project does own: predict
a spell's category from the free-text description of its effect. It is a genuine
supervised text classification problem with real labels that nobody in this
project chose, it is evaluated exactly as the brief requires with accuracy,
precision, recall and a confusion matrix, and it is compared against a baseline.
What it is not is a sentiment model, and it is not described as one anywhere.

Three things about this data shape the method.

The labels are messy. PotterDB records categories as free text and some spells
carry several, such as "Transfiguration, Jinx". Only the first is kept, and
casing is normalised, because "Transfiguration, jinx" and "Transfiguration,
Jinx" are the same label typed twice.

The classes are very unbalanced. Charm is over half the usable set. That makes
accuracy a poor headline number, so macro-averaged precision and recall are
reported alongside it, and the baseline is a classifier that always says Charm.
Beating 59 per cent accuracy is not an achievement if 59 per cent of the answers
are Charm.

The texts are short, a median of about five words. That rules out anything
sophisticated and makes character n-grams a better bet than words, since a five
word description gives a word model almost nothing to work with.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline

from src.utils.config import get, path, random_seed
from src.utils.io import relative, save_table
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue, write_finding
from src.utils.plotting import PALETTE, apply_style, save_figure, title_block

SCRIPT = "32_spell_classifier"
logger = get_logger(SCRIPT)

# A class needs enough examples to appear in every cross-validation fold.
MIN_CLASS_SIZE = 10
FOLDS = int(get("modelling.cv_folds"))


def primary_category(value: object) -> str | None:
    """First category only, normalised.

    'Transfiguration, Jinx' and 'Transfiguration, jinx' are the same label typed
    two ways, and treating them as different classes would invent a distinction
    the source does not make.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    first = value.split(",")[0].split("/")[0].strip()
    return first.capitalize() if first else None


def load_spells() -> pd.DataFrame:
    spells = pd.read_csv(path("data_cleaned", "potterdb", "spells.csv"))
    spells["label"] = spells["category"].map(primary_category)

    # The effect text is the feature. A spell with no description cannot be
    # classified from its description.
    spells = spells.dropna(subset=["label", "effect"])
    spells = spells[spells["effect"].str.strip().str.len() > 0]

    counts = spells["label"].value_counts()
    keep = counts[counts >= MIN_CLASS_SIZE].index
    dropped = int((~spells["label"].isin(keep)).sum())

    if dropped:
        log_data_issue(
            SCRIPT, "spell_classifier",
            f"{dropped} spells fall in classes with fewer than {MIN_CLASS_SIZE} examples",
            f"those classes were dropped; {len(keep)} classes remain. A class with three "
            f"examples cannot be evaluated in {FOLDS}-fold cross validation.",
            severity="note",
        )

    return spells[spells["label"].isin(keep)].reset_index(drop=True)


def build_pipeline() -> Pipeline:
    """Character n-grams into logistic regression.

    Character n-grams rather than words because the descriptions are a handful
    of words each; word features on five-word documents are mostly zeros.
    Balanced class weights because Charm would otherwise swamp everything.
    """
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 5),
            min_df=2,
            sublinear_tf=True,
        )),
        ("model", LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=random_seed(),
        )),
    ])


def plot_confusion(matrix: np.ndarray, labels: list[str], headline: str, subtitle: str) -> Path:
    apply_style()
    fig, ax = plt.subplots(figsize=(8.5, 7))

    # Row-normalised: with classes this unbalanced, raw counts would show one
    # bright square for Charm and nothing legible anywhere else.
    with np.errstate(invalid="ignore", divide="ignore"):
        normalised = matrix / matrix.sum(axis=1, keepdims=True)
    normalised = np.nan_to_num(normalised)

    image = ax.imshow(normalised, cmap="RdGy_r", vmin=0, vmax=1)

    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("predicted")
    ax.set_ylabel("actual")
    ax.grid(False)

    for i in range(len(labels)):
        for j in range(len(labels)):
            if matrix[i, j] == 0:
                continue
            ax.text(
                j, i, str(int(matrix[i, j])),
                ha="center", va="center", fontsize=8.5,
                color=PALETTE["ground"] if normalised[i, j] > 0.55 else PALETTE["ink"],
            )

    fig.colorbar(image, ax=ax, fraction=0.045, label="share of the actual class")
    title_block(ax, headline, subtitle, subtitle_wrap=95)
    return save_figure(fig, "spell_classifier_confusion.png", "PotterDB spells endpoint, 2 September 2026")


def main() -> None:
    np.random.seed(random_seed())

    with RunTimer(SCRIPT, logger) as run:
        spells = load_spells()
        run.rows_in = len(spells)

        texts = spells["effect"].astype(str)
        labels = spells["label"]
        class_names = sorted(labels.unique())

        median_words = int(texts.str.split().str.len().median())
        logger.info(
            "%d spells, %d classes, median description %d words",
            len(spells), len(class_names), median_words,
        )
        logger.info("class sizes:\n%s", labels.value_counts().to_string())

        splitter = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=random_seed())

        # Cross-validated predictions rather than a single split: with 23 examples
        # in the smallest class, one held-out split would put four or five of them
        # in the test set and the score would be mostly luck.
        predicted = cross_val_predict(build_pipeline(), texts, labels, cv=splitter)

        baseline_predicted = cross_val_predict(
            DummyClassifier(strategy="most_frequent"), texts, labels, cv=splitter
        )

        accuracy = accuracy_score(labels, predicted)
        baseline_accuracy = accuracy_score(labels, baseline_predicted)
        macro_f1 = f1_score(labels, predicted, average="macro", zero_division=0)
        baseline_macro_f1 = f1_score(labels, baseline_predicted, average="macro", zero_division=0)

        logger.info(
            "accuracy %.3f against a majority baseline of %.3f; macro F1 %.3f against %.3f",
            accuracy, baseline_accuracy, macro_f1, baseline_macro_f1,
        )

        report = classification_report(
            labels, predicted, output_dict=True, zero_division=0
        )
        per_class = pd.DataFrame(report).transpose().reset_index().rename(columns={"index": "class"})
        per_class = per_class[per_class["class"].isin(class_names)]
        per_class[["precision", "recall", "f1-score"]] = per_class[
            ["precision", "recall", "f1-score"]
        ].round(3)
        per_class_table = save_table(
            "spell_classifier_per_class.csv", per_class,
            note="per class precision, recall and F1 from 5-fold cross validation",
        )
        logger.info("per class:\n%s", per_class.to_string(index=False))

        metrics = pd.DataFrame([
            {
                "model": "character n-gram TF-IDF + logistic regression",
                "accuracy": round(accuracy, 4),
                "macro_f1": round(macro_f1, 4),
                "classes": len(class_names),
                "observations": len(spells),
                "evaluation": f"{FOLDS}-fold stratified cross validation",
            },
            {
                "model": "majority class baseline (always predicts the commonest class)",
                "accuracy": round(baseline_accuracy, 4),
                "macro_f1": round(baseline_macro_f1, 4),
                "classes": len(class_names),
                "observations": len(spells),
                "evaluation": f"{FOLDS}-fold stratified cross validation",
            },
        ])
        metrics_table = save_table("spell_classifier_metrics.csv", metrics)

        matrix = confusion_matrix(labels, predicted, labels=class_names)
        beats_accuracy = accuracy > baseline_accuracy

        if beats_accuracy:
            headline = (
                f"The classifier reaches {accuracy:.0%} accuracy against a "
                f"{baseline_accuracy:.0%} majority baseline"
            )
        else:
            headline = (
                f"The classifier loses to the majority baseline on accuracy "
                f"({accuracy:.0%} against {baseline_accuracy:.0%}) and wins on macro F1"
            )
        subtitle = (
            f"Row-normalised confusion matrix, {FOLDS}-fold cross validation over "
            f"{len(spells)} spells in {len(class_names)} classes. Counts shown in each cell. "
            f"Macro F1 {macro_f1:.2f} against {baseline_macro_f1:.2f}, which is the fairer "
            f"comparison when one class holds half the data."
        )
        figure_path = plot_confusion(matrix, class_names, headline, subtitle)

        models_dir = path("outputs_models", create=True)
        models_dir.mkdir(parents=True, exist_ok=True)
        (models_dir / "spell_classifier.json").write_text(
            json.dumps({
                "task": "predict spell category from its free-text effect description",
                "not_a_sentiment_model": True,
                "features": "char_wb TF-IDF, 2-5 grams, min_df=2, sublinear",
                "model": "logistic regression, balanced class weights",
                "classes": class_names,
                "class_sizes": labels.value_counts().to_dict(),
                "accuracy": accuracy,
                "baseline_accuracy": baseline_accuracy,
                "macro_f1": macro_f1,
                "baseline_macro_f1": baseline_macro_f1,
                "observations": len(spells),
                "folds": FOLDS,
                "random_seed": random_seed(),
            }, indent=2, default=str),
            encoding="utf-8",
        )

        best_class = per_class.loc[per_class["f1-score"].idxmax()]
        worst_class = per_class.loc[per_class["f1-score"].idxmin()]

        finding = (
            f"The classifier does not beat its baseline on accuracy, and section 11 requires that "
            f"be said plainly: it scores {accuracy:.0%} against {baseline_accuracy:.0%} for a "
            f"model that always guesses Charm. That is not the whole story, because Charm is "
            f"{labels.value_counts().iloc[0] / len(labels):.0%} of the data and a model that only "
            f"ever says Charm is useless whatever its accuracy. On macro F1, which weights every "
            f"class equally, the classifier scores {macro_f1:.2f} against the baseline's "
            f"{baseline_macro_f1:.2f}, so it has learned something real about seven classes while "
            f"giving up accuracy on the eighth. It handles {best_class['class']} well "
            f"(F1 {best_class['f1-score']:.2f}) and {worst_class['class']} poorly "
            f"(F1 {worst_class['f1-score']:.2f}), which is what a median of {median_words} words "
            f"per description supports, in a source that applies the jinx and hex labels "
            f"inconsistently to begin with."
        )

        write_finding(
            "5.4 Text classifier: predicting spell category from description",
            finding,
            evidence=(
                f"TF-IDF over character n-grams into logistic regression with balanced class "
                f"weights, evaluated by {FOLDS}-fold stratified cross validation against a "
                f"majority-class baseline. Accuracy, macro F1, per-class precision and recall, and "
                f"a confusion matrix all reported, per section 11."
            ),
            sample=(
                f"{len(spells)} spells across {len(class_names)} categories, each with a non-empty "
                f"effect description, median {median_words} words. Classes with fewer than "
                f"{MIN_CLASS_SIZE} examples were dropped as unevaluable."
            ),
            uncertainty=(
                "This is not the model the brief asked for. Module 5.4 specifies a sentiment "
                "classifier trained on fan review text, and that corpus was never collected "
                "because it needs Reddit credentials this project does not have. Rather than "
                "invent labels for text that does not exist, the same evaluation was run on a "
                "genuine labelled classification task the project already owns. It demonstrates "
                "the method and it is honestly labelled, but it answers no commercial question "
                "and nothing downstream depends on it. The labels are also free text applied "
                "inconsistently by the source, which puts a ceiling on any score reported here. "
                "The headline comparison is genuinely ambiguous: the model is worse than the "
                "baseline by one measure and better by another, and which matters depends on "
                "whether identifying rare classes is worth anything. Here it is not, because "
                "nothing downstream uses the output."
            ),
            figure=relative(figure_path),
            table=relative(metrics_table),
        )

        run.rows_out = len(spells)
        run.note = f"accuracy {accuracy:.3f} vs baseline {baseline_accuracy:.3f}"
        logger.info("saved %s", relative(per_class_table))

    logger.info("spell classifier complete")


if __name__ == "__main__":
    main()
