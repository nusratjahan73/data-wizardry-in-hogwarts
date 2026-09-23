"""Clean the Reddit corpus into a post table and a comment table.

Reads  : data/raw/reddit/{posts,comments}__*.json
Writes : data/cleaned/reddit/posts.csv, data/cleaned/reddit/comments.csv
Runtime: seconds to a minute, depending on corpus size.

Nothing here can undo a privacy mistake made during collection, so this script
assumes the collector did its job and checks that it did: if a raw file contains
an `author` field rather than an `author_hash`, the run stops. That is a
deliberate hard failure. Every other data problem in this project is logged and
worked around, but personal data reaching disk is the one thing that cannot be
handled by writing a note about it.

Text is kept here because the sentiment and segmentation modules need it, but it
is fan written commentary, not copyrighted work, and section 6 forbids storing
the novels or scripts in any form. Module 3 stores only derived features.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.utils.io import load_raw_json, raw_files, relative, save_cleaned
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "16_clean_reddit"
SOURCE = "reddit"
logger = get_logger(SCRIPT)

FORBIDDEN_FIELDS = {"author", "author_name", "username", "author_fullname", "email"}


def assert_no_personal_fields(records: list[dict], file_name: str) -> None:
    """Stop the run if a raw file carries an identifier it should never have."""
    if not records:
        return
    present = FORBIDDEN_FIELDS & set(records[0].keys())
    if present:
        raise RuntimeError(
            f"{file_name} contains the field(s) {sorted(present)}. Usernames must be "
            f"hashed at collection time. Delete the raw file, fix 08_reddit.py and "
            f"collect again. This is a hard stop, not a warning."
        )


def load_kind(kind: str) -> pd.DataFrame:
    files = raw_files(SOURCE, f"{kind}__*.json")
    frames = []
    for file_path in files:
        records = load_raw_json(file_path)
        assert_no_personal_fields(records, file_path.name)
        if records:
            frames.append(pd.DataFrame(records))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def add_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the calendar columns the seasonality and segmentation work needs."""
    created = pd.to_datetime(frame["created_utc"], errors="coerce", utc=True)
    frame["created_date"] = created.dt.date
    frame["created_year"] = created.dt.year.astype("Int64")
    frame["created_month"] = created.dt.to_period("M").astype(str)
    frame["created_week"] = created.dt.to_period("W").apply(
        lambda p: p.start_time.date() if pd.notna(p) else pd.NaT
    )
    return frame


def main() -> None:
    with RunTimer(SCRIPT, logger) as run:
        posts = load_kind("posts")
        comments = load_kind("comments")

        if posts.empty and comments.empty:
            log_data_issue(
                SCRIPT, SOURCE,
                "no raw Reddit files found, so there is no fan text corpus",
                "module 3.1 (sentiment), module 4 (segmentation) and module 7 (big data) "
                "have no input. Add Reddit credentials to .env and run 08_reddit.py.",
                severity="error",
            )
            logger.warning("no raw Reddit data to clean; three modules are blocked")
            run.rows_out = 0
            return

        rows_out = 0

        if not posts.empty:
            posts = add_time_features(posts)
            posts["title"] = posts["title"].fillna("")
            posts["selftext"] = posts["selftext"].fillna("")
            posts["text"] = (posts["title"] + " " + posts["selftext"]).str.strip()
            posts["text_length"] = posts["text"].str.len()
            posts["word_count"] = posts["text"].str.split().str.len()

            before = len(posts)
            posts = posts.drop_duplicates(subset=["id"])
            if before != len(posts):
                logger.info("dropped %d duplicate posts", before - len(posts))

            target = save_cleaned(
                SOURCE, "posts.csv", posts,
                subreddits=sorted(posts["subreddit"].dropna().unique().tolist()),
                first_post=str(posts["created_date"].min()),
                last_post=str(posts["created_date"].max()),
                privacy="author_hash only; no usernames stored",
            )
            rows_out += len(posts)
            logger.info(
                "posts: %d rows, %s to %s -> %s",
                len(posts), posts["created_date"].min(), posts["created_date"].max(), relative(target),
            )

        if not comments.empty:
            comments = add_time_features(comments)
            comments["body"] = comments["body"].fillna("")
            comments["word_count"] = comments["body"].str.split().str.len()

            # Removed and deleted comments carry no opinion, only a placeholder.
            placeholders = comments["body"].isin(["[removed]", "[deleted]", ""])
            if placeholders.any():
                logger.info("dropped %d removed or deleted comments", int(placeholders.sum()))
                comments = comments[~placeholders]

            comments = comments.drop_duplicates(subset=["id"])
            target = save_cleaned(
                SOURCE, "comments.csv", comments,
                first_comment=str(comments["created_date"].min()),
                last_comment=str(comments["created_date"].max()),
                privacy="author_hash only; no usernames stored",
            )
            rows_out += len(comments)
            logger.info("comments: %d rows -> %s", len(comments), relative(target))

        run.rows_out = rows_out

    logger.info("Reddit cleaning complete")


if __name__ == "__main__":
    main()
