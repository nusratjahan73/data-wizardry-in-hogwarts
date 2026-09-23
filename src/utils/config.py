"""Single point of access to config.yaml and to the .env secrets.

Reads  : config.yaml at the repository root, .env if present.
Writes : nothing.
Runtime: instant.

No other module in this project is allowed to hard code a path, a date, a
threshold or a key name. Everything comes through here, so a reviewer can change
one file and rerun the whole project.
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
    """Return the repository root, found by walking up to the config file.

    Anchoring on the file rather than on the current working directory means a
    script behaves the same whether it is run from the root, from src/collect or
    from a notebook.
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
    """Load and cache config.yaml."""
    with (repo_root() / "config.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get(dotted_key: str, default: Any = "__raise__") -> Any:
    """Fetch a nested config value with a dotted path, e.g. get('dates.premiere').

    Raising by default is deliberate. A typo in a config key should stop the run
    loudly rather than silently substitute None into an analysis.
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
    """Resolve a configured path key to an absolute Path under the repo root.

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
    """Read a config date key as a datetime.date.

    PyYAML already parses unquoted ISO dates into date objects, but a quoted one
    arrives as a string, so accept both rather than depending on how it was typed.
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
    """Return a secret from .env or the real environment, or None if unset.

    Returning None rather than raising is what lets a collection script log a
    clear message naming the key and skip its source cleanly, which is the
    behaviour section 5 of the brief asks for.
    """
    _load_env()
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def require_secrets(*names: str) -> tuple[bool, list[str]]:
    """Check several secrets at once.

    Returns (True, []) when all are present, or (False, [missing names]) so the
    caller can log exactly which key is absent.
    """
    missing = [n for n in names if secret(n) is None]
    return (not missing), missing


def user_agent() -> str:
    """The identifying user agent sent with every outbound request."""
    return get("project.user_agent")


def random_seed() -> int:
    return int(get("project.random_seed"))
