"""Giving every script one place to read config.yaml and the .env secrets.

Reading: config.yaml in my project folder, and .env if it is there.
Writing: nothing.
Runtime: instant.

I do not hard code a path, a date, a threshold or a key name in any other file.
Everything comes through here, so a reviewer can change one file and rerun the
whole project.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def repo_root() -> Path:
    """Returning my project folder, found by walking up until I see config.yaml.

    I look for the file and not the current working directory, so a script behaves
    the same when I run it from the project folder, from src/collect or from a
    notebook.
    """
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "config.yaml").is_file():
            return parent
    raise FileNotFoundError(
        "config.yaml not found in any parent directory of src/utils/config.py. "
        "Run scripts from inside the repository."
    )


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Loading config.yaml once and keeping it in memory."""
    with (repo_root() / "config.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get(dotted_key: str, default: Any = "__raise__") -> Any:
    """Fetching a nested config value with a dotted path, e.g. get('dates.premiere').

    I raise an error by default on purpose. A typo in a config key should stop the
    run loudly, and not quietly put None into my analysis.
    """
    node: Any = load_config()
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            if default == "__raise__":
                raise KeyError(f"config key not found: {dotted_key}")
            return default
        node = node[part]
    return node


def path(key: str, *extra: str, create: bool = False) -> Path:
    """Turning a path key from config into a full Path under my project folder.

    >>> path("figures", "seasonality.png")
    .../images/figures/seasonality.png
    """
    configured = get(f"paths.{key}")
    resolved = repo_root() / configured
    for part in extra:
        resolved = resolved / part
    if create:
        target = resolved if not resolved.suffix else resolved.parent
        target.mkdir(parents=True, exist_ok=True)
    return resolved


def as_date(dotted_key: str) -> date:
    """Reading a config date key as a datetime.date.

    PyYAML already turns an unquoted ISO date into a date object, but a quoted one
    comes in as a string. I accept both, so it does not matter how I typed it.
    """
    value = get(dotted_key)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


@lru_cache(maxsize=1)
def _load_env() -> None:
    load_dotenv(repo_root() / ".env")


def secret(name: str) -> str | None:
    """Returning a secret from .env or the real environment, or None if it is not set.

    I return None and do not raise an error. That lets a collection script log a
    clear message naming the missing key and skip its source cleanly, so one
    missing key does not stop the other sources.
    """
    _load_env()
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def require_secrets(*names: str) -> tuple[bool, list[str]]:
    """Checking several secrets at once.

    I return (True, []) when all are present, or (False, [missing names]) so the
    caller can log exactly which key is missing.
    """
    missing = [n for n in names if secret(n) is None]
    return (not missing), missing


def user_agent() -> str:
    """Returning the user agent that identifies my project on every outbound request."""
    return get("project.user_agent")


def random_seed() -> int:
    return int(get("project.random_seed"))
