"""Collecting public fan discussion from Reddit, with usernames hashed at the source.

Reading: config.yaml (sources.reddit, ethics), Reddit credentials from .env.
Writing: data/raw/reddit/posts__<subreddit>.json
         data/raw/reddit/comments__<subreddit>.json
Runtime: five to fifteen minutes once credentials are present.

This is the text behind three of my modules: sentiment over time (3.1), audience segmentation (4)
and the big data comparison (7). Without credentials none of them can run on real text, so I say
that clearly in logs/data_issues.md.

I apply two privacy rules from my module 8 here and not later, because a privacy rule applied after
collection has already been broken once.

Usernames never reach disk. I replace each author with a salted SHA-256 hash at the moment of
collection. The salt lives in .env and not in the repository, so nobody reading this code can
reverse the hashes. I only use the hash to group posts by the same person for segmentation, and I
never report it.

I never scrape. If credentials are missing I stop, because Reddit publishes an API and asks that
automated access go through it.

Getting credentials: create a "script" type application at reddit.com/prefs/apps. It is free and
takes about a minute. Copy the client id and secret into .env, set REDDIT_USER_AGENT to something
that names the project and a contact, and set REDDIT_HASH_SALT to any long random string.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.utils.config import get, require_secrets, secret
from src.utils.io import save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "08_reddit"
SOURCE = "reddit"
logger = get_logger(SCRIPT)

REQUIRED_KEYS = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT", "REDDIT_HASH_SALT"]


def hash_author(author: str | None, salt: str) -> str:
    """Returning a salted hash of a username, or 'deleted' when there is no author.

    I add a salt because a plain SHA-256 of a username is easy to reverse with a
    list of known usernames. That would still be personal data, only disguised.
    """
    if not author:
        return "deleted"
    return hashlib.sha256(f"{salt}{author}".encode()).hexdigest()[:16]


def post_record(submission, salt: str) -> dict:
    """Flattening one submission and keeping only the fields my analysis needs.

    I pick the fields one by one and do not dump the whole object. This is for
    privacy as much as tidiness: nothing outside this list can leak into my data.
    """
    return {
        "id": submission.id,
        "subreddit": str(submission.subreddit),
        "created_utc": datetime.fromtimestamp(
            submission.created_utc, tz=UTC
        ).isoformat(timespec="seconds"),
        "title": submission.title,
        "selftext": submission.selftext,
        "score": submission.score,
        "upvote_ratio": submission.upvote_ratio,
        "num_comments": submission.num_comments,
        "over_18": submission.over_18,
        "link_flair_text": submission.link_flair_text,
        "is_self": submission.is_self,
        "author_hash": hash_author(
            str(submission.author) if submission.author else None, salt
        ),
        # Keeping account age as a segmentation feature, but not the account itself.
        # I only store the age in days at the time of the post.
        "author_account_age_days": account_age_days(submission),
    }


def account_age_days(submission) -> int | None:
    """Getting the age of the posting account in days, or None if I cannot read it.

    Deleted and suspended accounts raise an error, and looking up the author on
    every post would double my API calls. So I only try my best here, and my
    cleaning step treats None as an unknown band.
    """
    try:
        author = submission.author
        if author is None:
            return None
        created = getattr(author, "created_utc", None)
        if created is None:
            return None
        delta = datetime.fromtimestamp(submission.created_utc, tz=UTC) - (
            datetime.fromtimestamp(created, tz=UTC)
        )
        return max(delta.days, 0)
    except Exception:
        return None


def comment_record(comment, salt: str) -> dict:
    return {
        "id": comment.id,
        "submission_id": comment.submission.id,
        "subreddit": str(comment.subreddit),
        "created_utc": datetime.fromtimestamp(
            comment.created_utc, tz=UTC
        ).isoformat(timespec="seconds"),
        "body": comment.body,
        "score": comment.score,
        "author_hash": hash_author(str(comment.author) if comment.author else None, salt),
    }


def collect_subreddit(reddit, name: str, limit: int, salt: str) -> tuple[int, int]:
    """Collecting the top posts and their top level comments for one subreddit.

    I chose `top` over `all` on purpose. `new` would only give me a snapshot of
    this week, and my analysis needs a series that reaches back years.
    """
    posts: list[dict] = []
    comments: list[dict] = []

    try:
        subreddit = reddit.subreddit(name)
        for submission in subreddit.top(time_filter="all", limit=limit):
            posts.append(post_record(submission, salt))

            # Keeping only the top level comments. Expanding every thread would mean
            # about ten times more calls for text that says much the same.
            submission.comments.replace_more(limit=0)
            for comment in submission.comments[:25]:
                comments.append(comment_record(comment, salt))
    except Exception as exc:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{name}",
            f"collection failed part way: {type(exc).__name__}: {exc}",
            f"kept the {len(posts)} posts already collected and continued to the next subreddit",
            severity="error",
        )

    if posts:
        save_raw(
            SOURCE, f"posts__{name}.json", posts,
            source_url=f"https://www.reddit.com/r/{name}/top",
            subreddit=name, records=len(posts),
            privacy="usernames replaced with a salted hash at collection time",
        )
    if comments:
        save_raw(
            SOURCE, f"comments__{name}.json", comments,
            source_url=f"https://www.reddit.com/r/{name}/top",
            subreddit=name, records=len(comments),
            privacy="usernames replaced with a salted hash at collection time",
        )

    logger.info("r/%-16s %5d posts, %6d comments", name, len(posts), len(comments))
    return len(posts), len(comments)


def main() -> None:
    have_keys, missing = require_secrets(*REQUIRED_KEYS)

    with RunTimer(SCRIPT, logger) as run:
        if not have_keys:
            log_data_issue(
                SCRIPT,
                SOURCE,
                f"missing credentials in .env: {', '.join(missing)}",
                "no fan text was collected. Module 3.1 (sentiment), module 4 "
                "(segmentation) and module 7 (big data) have no corpus and are "
                "blocked until credentials are added. No scraping fallback was "
                "used, because Reddit asks that automated access go through its API.",
                severity="error",
            )
            logger.error("missing Reddit credentials: %s. Skipping cleanly.", ", ".join(missing))
            run.rows_out = 0
            run.note = "skipped, no credentials"
            return

        try:
            import praw
        except ImportError:
            log_data_issue(
                SCRIPT, SOURCE, "praw is not installed",
                "install it from requirements.txt and rerun this script alone",
                severity="error",
            )
            run.rows_out = 0
            return

        reddit = praw.Reddit(
            client_id=secret("REDDIT_CLIENT_ID"),
            client_secret=secret("REDDIT_CLIENT_SECRET"),
            user_agent=secret("REDDIT_USER_AGENT"),
            check_for_async=False,
        )
        reddit.read_only = True

        salt = secret(get("ethics.hash_salt_env_var"))
        subreddits = get("sources.reddit.subreddits")
        limit = int(get("sources.reddit.post_limit_per_subreddit"))

        total_posts = 0
        total_comments = 0
        for name in subreddits:
            posts, comments = collect_subreddit(reddit, name, limit, salt)
            total_posts += posts
            total_comments += comments

        run.rows_out = total_posts + total_comments
        run.note = f"{total_posts} posts and {total_comments} comments across {len(subreddits)} subreddits"
        logger.info("Reddit collection complete: %d posts, %d comments", total_posts, total_comments)


if __name__ == "__main__":
    main()
