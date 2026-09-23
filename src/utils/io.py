"""Saving, loading and stamping files, with the placement rules enforced in code.

Reads  : config.yaml for the folder layout.
Writes : whatever the caller asks for, plus a .meta.json beside every saved file.
Runtime: instant.

Section 4 of the brief gives every file exactly one correct home. Rather than
trusting forty scripts to remember that, the save helpers below refuse to write
outside the folder that matches the kind of thing being saved. A rule that is
only written in a document gets broken; a rule that raises an exception does not.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import path, repo_root


class PlacementError(RuntimeError):
    """Raised when a script tries to write a file outside its allowed folder."""


def _assert_inside(target: Path, allowed_root: Path, kind: str) -> None:
    target = target.resolve()
    allowed_root = allowed_root.resolve()
    if allowed_root not in target.parents:
        raise PlacementError(
            f"refusing to write {kind} to {target}. "
            f"Section 4 of the brief puts {kind} under {allowed_root}."
        )


def _json_default(obj: Any) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def write_metadata(target: Path, **fields: Any) -> Path:
    """Write a small sidecar recording when and from where a file was produced.

    Section 4 asks that every saved file carries its collection date either in
    the name or in an accompanying metadata file. A sidecar is preferable to a
    dated filename because it also holds the source URL and the row count, which
    is what makes a stale pull recognisable later.
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
    """Save an untouched source pull under data/raw/<source>/.

    `content` may be a parsed JSON object, a string, or bytes. It is written in
    the shape it arrived in. Collection never converts format; that is cleaning's
    job, and keeping them apart is what makes a raw file comparable to its source.
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
    """Save a cleaned table under data/cleaned/<source>/, mirroring the raw folder."""
    target = path("data_cleaned", source, filename)
    _assert_inside(target, path("data_cleaned"), "cleaned data")
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False, encoding="utf-8")
    write_metadata(target, source=source, rows=len(frame), columns=list(frame.columns), **meta)
    return target


def save_processed(filename: str, frame: pd.DataFrame, **meta: Any) -> Path:
    """Save a joined, analysis ready table under data/processed/.

    No source subfolders here, on purpose: a processed table combines sources and
    belongs to none of them. This is the only folder analysis scripts may read.
    """
    target = path("data_processed", filename)
    _assert_inside(target, path("data_processed"), "processed tables")
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False, encoding="utf-8")
    write_metadata(target, rows=len(frame), columns=list(frame.columns), **meta)
    return target


def save_table(filename: str, frame: pd.DataFrame, **meta: Any) -> Path:
    """Save a numeric summary that accompanies a figure, under outputs/tables/."""
    target = path("outputs_tables", filename)
    _assert_inside(target, path("outputs_tables"), "summary tables")
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False, encoding="utf-8")
    write_metadata(target, rows=len(frame), columns=list(frame.columns), **meta)
    return target


def figure_path(filename: str) -> Path:
    """Return the one legal home for a generated chart, images/figures/.

    Chart scripts call this instead of building a path themselves, which is what
    keeps every picture in the project under images/.
    """
    target = path("figures", filename)
    _assert_inside(target, path("images"), "images")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def read_processed(filename: str, **kwargs: Any) -> pd.DataFrame:
    """Read a processed table. The only read an analysis script is allowed."""
    target = path("data_processed", filename)
    if not target.exists():
        raise FileNotFoundError(
            f"{target} does not exist. Run the collect and clean scripts in "
            f"filename order first, then the build script for processed tables."
        )
    return pd.read_csv(target, **kwargs)


def read_cleaned(source: str, filename: str, **kwargs: Any) -> pd.DataFrame:
    """Read a cleaned table. For the processed table builder only."""
    target = path("data_cleaned", source, filename)
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist. Run the cleaning script for {source} first.")
    return pd.read_csv(target, **kwargs)


def read_external(filename: str, **kwargs: Any) -> pd.DataFrame:
    """Read a hand entered file from data/external/."""
    target = path("data_external", filename)
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist. See section 6, hand entered sources.")
    return pd.read_csv(target, **kwargs)


def raw_files(source: str, pattern: str = "*.json") -> list[Path]:
    """List raw pulls for one source, excluding the metadata sidecars."""
    folder = path("data_raw", source)
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob(pattern) if not p.name.endswith(".meta.json"))


def load_raw_json(target: Path) -> Any:
    return json.loads(target.read_text(encoding="utf-8"))


def relative(target: Path) -> str:
    """Path relative to the repository root, for readable log lines.

    Always written with forward slashes. These strings end up in docs/findings.md
    and in the report, which are read on other machines, and a Windows backslash
    path in a Markdown document is both ugly and, in some renderers, an escape.
    """
    try:
        relative_path = target.resolve().relative_to(repo_root())
    except ValueError:
        return str(target)
    return relative_path.as_posix()
