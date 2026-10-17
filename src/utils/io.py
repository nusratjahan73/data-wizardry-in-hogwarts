"""Saving, loading and stamping files, with my folder rules enforced in code.

Reading: config.yaml for the folder layout.
Writing: whatever the caller asks for, plus a .meta.json beside every saved file.
Runtime: instant.

Every kind of file in my project has exactly one correct folder. I did not want
to trust forty scripts to remember that, so the save helpers below refuse to
write outside the folder that matches the kind of thing being saved. A rule that
is only written in a document gets broken. A rule that raises an exception does not.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import path, repo_root


class PlacementError(RuntimeError):
    """Signalling that a script tried to write a file outside its allowed folder."""


def _assert_inside(target: Path, allowed_root: Path, kind: str) -> None:
    target = target.resolve()
    allowed_root = allowed_root.resolve()
    if allowed_root not in target.parents:
        raise PlacementError(
            f"refusing to write {kind} to {target}. "
            f"My folder layout puts {kind} under {allowed_root}."
        )


def _json_default(obj: Any) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def write_metadata(target: Path, **fields: Any) -> Path:
    """Writing a small sidecar file that records when and from where a file was made.

    I want every saved file to carry its collection date, in its name or in a
    metadata file beside it. I prefer a sidecar to a dated file name because it
    also holds the source URL and the row count, and that helps me spot a stale
    pull later.
    """
    meta_path = target.with_suffix(target.suffix + ".meta.json")
    payload = {
        "file": target.name,
        "collected_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "size_bytes": target.stat().st_size if target.exists() else None,
        **fields,
    }
    meta_path.write_text(
        json.dumps(payload, indent=2, default=_json_default), encoding="utf-8"
    )
    return meta_path


def save_raw(source: str, filename: str, content: Any, source_url: str = "", **meta: Any) -> Path:
    """Saving an untouched source pull under data/raw/<source>/.

    `content` can be a parsed JSON object, a string, or bytes. I write it in the
    shape it arrived in. Collection never converts the format, because that is the
    job of cleaning. Keeping them apart lets me compare a raw file with its source.
    """
    target = path("data_raw", source, filename)
    _assert_inside(target, path("data_raw"), "downloaded data")
    target.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(content, bytes):
        target.write_bytes(content)
    elif isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_text(
            json.dumps(content, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
        )

    write_metadata(target, source=source, source_url=source_url, **meta)
    return target


def save_cleaned(source: str, filename: str, frame: pd.DataFrame, **meta: Any) -> Path:
    """Saving a cleaned table under data/cleaned/<source>/, with the same layout as the raw folder."""
    target = path("data_cleaned", source, filename)
    _assert_inside(target, path("data_cleaned"), "cleaned data")
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False, encoding="utf-8")
    write_metadata(target, source=source, rows=len(frame), columns=list(frame.columns), **meta)
    return target


def save_processed(filename: str, frame: pd.DataFrame, **meta: Any) -> Path:
    """Saving a joined table that is ready for analysis under data/processed/.

    I use no source subfolders here on purpose. A processed table combines sources
    and belongs to none of them. This is the only folder my analysis scripts may read.
    """
    target = path("data_processed", filename)
    _assert_inside(target, path("data_processed"), "processed tables")
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False, encoding="utf-8")
    write_metadata(target, rows=len(frame), columns=list(frame.columns), **meta)
    return target


def save_table(filename: str, frame: pd.DataFrame, **meta: Any) -> Path:
    """Saving a summary table of numbers that goes with a figure, under outputs/tables/."""
    target = path("outputs_tables", filename)
    _assert_inside(target, path("outputs_tables"), "summary tables")
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False, encoding="utf-8")
    write_metadata(target, rows=len(frame), columns=list(frame.columns), **meta)
    return target


def figure_path(filename: str) -> Path:
    """Returning the one allowed place for a generated chart, under images/figures/.

    My chart scripts call this and do not build a path themselves, so every
    picture in my project stays under images/.
    """
    target = path("figures", filename)
    _assert_inside(target, path("images"), "images")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def read_processed(filename: str, **kwargs: Any) -> pd.DataFrame:
    """Reading a processed table. This is the only read my analysis scripts are allowed."""
    target = path("data_processed", filename)
    if not target.exists():
        raise FileNotFoundError(
            f"{target} does not exist. Run the collect and clean scripts in "
            f"filename order first, then the build script for processed tables."
        )
    return pd.read_csv(target, **kwargs)


def read_cleaned(source: str, filename: str, **kwargs: Any) -> pd.DataFrame:
    """Reading a cleaned table. Only my processed table builder should use this."""
    target = path("data_cleaned", source, filename)
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist. Run the cleaning script for {source} first.")
    return pd.read_csv(target, **kwargs)


def read_external(filename: str, **kwargs: Any) -> pd.DataFrame:
    """Reading a file I entered by hand from data/external/."""
    target = path("data_external", filename)
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist. I enter this file by hand, so add it first.")
    return pd.read_csv(target, **kwargs)


def raw_files(source: str, pattern: str = "*.json") -> list[Path]:
    """Listing the raw pulls for one source, leaving out the metadata sidecars."""
    folder = path("data_raw", source)
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob(pattern) if not p.name.endswith(".meta.json"))


def load_raw_json(target: Path) -> Any:
    return json.loads(target.read_text(encoding="utf-8"))


def relative(target: Path) -> str:
    """Returning a path relative to my project folder, so my log lines are easy to read.

    I always write it with forward slashes. These strings end up in docs/findings.md
    and in my report, which are read on other machines. A Windows backslash path in
    a Markdown document is ugly, and some renderers treat it as an escape.
    """
    try:
        relative_path = target.resolve().relative_to(repo_root())
    except ValueError:
        return str(target)
    return relative_path.as_posix()
