"""Sharing my logging, run timing and the data issues register across all scripts.

Reading: config.yaml for the logs path.
Writing: logs/<script_name>.log, logs/run_history.csv, logs/data_issues.md.
Runtime: instant.

I want every script to log a timestamp, the script name and the row counts in
and out. Doing that in one place keeps the log format the same across forty odd
scripts, and that makes my logs easy to read.
"""

from __future__ import annotations

import csv
import logging
import re
import sys
import time
from datetime import UTC, datetime

from .config import path

_ISSUES_HEADER = """# Data issues register

Every source failure, shape change or short return recorded during a build.
Appended to automatically by `log_data_issue`. Never edit a past entry: add a
new one saying what changed.

| when (UTC) | script | source | severity | what happened | what was done instead |
| --- | --- | --- | --- | --- | --- |
"""


def get_logger(name: str) -> logging.Logger:
    """Returning a logger that writes to both the console and logs/<name>.log."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(name)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_dir = path("logs", create=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    logger.propagate = False
    return logger


class RunTimer:
    """Logging the start, end, duration and row counts of a run, as a context manager.

    Usage:
        with RunTimer("01_potterdb", logger) as run:
            ...
            run.rows_out = 5410
    """

    def __init__(self, script_name: str, logger: logging.Logger) -> None:
        self.script_name = script_name
        self.logger = logger
        self.rows_in: int | None = None
        self.rows_out: int | None = None
        self.note: str = ""
        self._start = 0.0

    def __enter__(self) -> RunTimer:
        self._start = time.perf_counter()
        self.logger.info("START %s", self.script_name)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = time.perf_counter() - self._start
        status = "FAILED" if exc_type else "OK"
        self.logger.info(
            "END %s | status=%s | rows_in=%s | rows_out=%s | seconds=%.1f",
            self.script_name,
            status,
            self.rows_in,
            self.rows_out,
            elapsed,
        )
        if exc_type:
            self.logger.error("%s raised %s: %s", self.script_name, exc_type.__name__, exc)
        _append_run_history(self, status, elapsed)
        return False  # Letting every exception pass through, never hiding one.


def _append_run_history(run: RunTimer, status: str, elapsed: float) -> None:
    history = path("logs", "run_history.csv", create=True)
    is_new = not history.exists()
    with history.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(
                ["run_at_utc", "script", "status", "rows_in", "rows_out", "seconds", "note"]
            )
        writer.writerow(
            [
                datetime.now(UTC).isoformat(timespec="seconds"),
                run.script_name,
                status,
                run.rows_in if run.rows_in is not None else "",
                run.rows_out if run.rows_out is not None else "",
                f"{elapsed:.1f}",
                run.note,
            ]
        )


def log_data_issue(
    script: str,
    source: str,
    what_happened: str,
    what_was_done: str,
    severity: str = "warning",
) -> None:
    """Adding a row to logs/data_issues.md.

    I call this whenever a source fails, returns less than expected or changes shape.
    A gap I wrote down is a limitation. A gap I did not write down looks like a mistake.
    """
    issues = path("logs", "data_issues.md", create=True)
    if not issues.exists():
        issues.write_text(_ISSUES_HEADER, encoding="utf-8")

    def clean(text: str) -> str:
        return text.replace("|", "/").replace("\n", " ").strip()

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    row = (
        f"| {stamp} | {clean(script)} | {clean(source)} | {clean(severity)} | "
        f"{clean(what_happened)} | {clean(what_was_done)} |\n"
    )
    with issues.open("a", encoding="utf-8") as fh:
        fh.write(row)


def log_build_note(module: str, produced: str, skipped: str = "none") -> None:
    """Adding a note to docs/build_log.md.

    This is part of how I define done. I count a module as finished only when a
    note exists saying what was produced and what was skipped.
    """
    build_log = path("docs", "build_log.md", create=True)
    if not build_log.exists():
        build_log.write_text(
            "# Build log\n\n"
            "One entry per completed module, appended by the scripts themselves.\n\n",
            encoding="utf-8",
        )
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    with build_log.open("a", encoding="utf-8") as fh:
        fh.write(f"## {module}\n\n- **When:** {stamp}\n- **Produced:** {produced}\n- **Skipped:** {skipped}\n\n")


def write_finding(
    analysis: str,
    finding: str,
    evidence: str,
    sample: str,
    uncertainty: str,
    figure: str = "",
    table: str = "",
) -> None:
    """Adding one finding to docs/findings.md, replacing any earlier version.

    My rule is that a finding is at most three sentences and always states its sample
    size and its uncertainty. I made those separate fields, so a finding cannot be
    written without them. I rewrite the whole file on each call, keyed on the analysis
    name, so rerunning an analysis updates its finding and does not add a second copy.
    """
    findings_path = path("docs", "findings.md", create=True)

    header = (
        "# Findings\n\n"
        "One entry per analysis, written by the analysis script itself. Each states "
        "the finding, the evidence behind it, the sample it rests on and how "
        "uncertain it is. Rerunning an analysis replaces its entry rather than "
        "adding a second one.\n\n"
    )

    def section_key(title: str) -> str:
        """Returning the stable part of a finding's title, the number at its start.

        When I keyed on the whole title, renaming an analysis left the old version
        behind. That happened once and put two versions of one finding that
        disagreed in the file together. The number does not change when the
        wording does.
        """
        match = re.match(r"^\s*(\d+(?:\.\d+)*[a-z]?)", title)
        return match.group(1) if match else title.strip()

    existing: dict[str, str] = {}
    if findings_path.exists():
        text = findings_path.read_text(encoding="utf-8")
        for block in text.split("\n## ")[1:]:
            title = block.split("\n", 1)[0].strip()
            existing[section_key(title)] = "## " + block.rstrip() + "\n"

    lines = [f"## {analysis}", "", finding, "", f"- **Evidence:** {evidence}", f"- **Sample:** {sample}", f"- **Uncertainty:** {uncertainty}"]
    if figure:
        lines.append(f"- **Figure:** `{figure}`")
    if table:
        lines.append(f"- **Table:** `{table}`")
    lines.append("")
    existing[section_key(analysis)] = "\n".join(lines) + "\n"

    findings_path.write_text(header + "\n".join(existing.values()), encoding="utf-8")
