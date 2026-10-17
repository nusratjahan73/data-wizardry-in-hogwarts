"""Sending polite HTTP requests: named, rate limited, retried, and honest when they fail.

Reading: config.yaml for the user agent and the rate limit of each source.
Writing: nothing directly. The scripts that call this save the responses.
Runtime: depends on the caller.

Every outbound request in my project goes through here. That lets my ethics module
say three things honestly: every request identifies my project, I never call a
source faster than its published limit, and when a source refuses me I accept it
and do not retry around it.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .config import user_agent

# Listing the status codes worth retrying. 429 means rate limiting, and the 5xx
# codes mean the server is having a bad moment. A 403 or a 404 is a real answer,
# not a hiccup, so I never retry those.
RETRYABLE = {429, 500, 502, 503, 504}


class RateLimiter:
    """Spacing out my calls to one host with a simple wall clock wait.

    A token bucket would allow short bursts, and a published limit like
    "900 per hour" is not asking for bursts. Even spacing is slower, but it is
    the behaviour I can defend in my ethics write up.
    """

    def __init__(self, min_seconds_between_calls: float) -> None:
        self.min_gap = float(min_seconds_between_calls)
        self._last_call = 0.0

    def wait(self) -> None:
        if self.min_gap <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_gap:
            time.sleep(self.min_gap - elapsed)
        self._last_call = time.monotonic()


class ApiError(RuntimeError):
    """Signalling that a request failed in a way the caller should record and skip."""

    def __init__(self, url: str, status: int | None, detail: str) -> None:
        self.url = url
        self.status = status
        self.detail = detail
        super().__init__(f"{url} -> status={status} {detail}")


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
    max_attempts: int = 4,
    timeout: int = 60,
    logger=None,
) -> Any:
    """Getting a URL and returning the parsed JSON, retrying only short lived failures.

    I raise ApiError when the attempts run out or the failure is permanent. The
    collection script that called me can then log the issue and move to the next
    source, and not die in the middle of a build.
    """
    all_headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    if headers:
        all_headers.update(headers)

    last_detail = ""
    last_status: int | None = None

    for attempt in range(1, max_attempts + 1):
        if limiter:
            limiter.wait()
        try:
            response = requests.get(url, params=params, headers=all_headers, timeout=timeout)
        except requests.RequestException as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
            last_status = None
        else:
            last_status = response.status_code
            if response.ok:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ApiError(url, response.status_code, f"response was not JSON: {exc}") from exc

            last_detail = response.text[:200]
            if response.status_code not in RETRYABLE:
                raise ApiError(url, response.status_code, last_detail)

            # Following the server's Retry-After wait first, before I fall back to my own backoff.
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait_for = int(retry_after)
                if logger:
                    logger.warning("server asked for %ss before retry: %s", wait_for, url)
                time.sleep(wait_for)
                continue

        if attempt < max_attempts:
            backoff = 2.0**attempt
            if logger:
                logger.warning(
                    "attempt %d/%d failed (%s), retrying in %.0fs: %s",
                    attempt,
                    max_attempts,
                    last_status,
                    backoff,
                    url,
                )
            time.sleep(backoff)

    raise ApiError(url, last_status, f"gave up after {max_attempts} attempts: {last_detail}")


def get_text(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
    timeout: int = 120,
) -> str:
    """Getting a URL and returning the body as text, for CSV and XML endpoints."""
    all_headers = {"User-Agent": user_agent()}
    if headers:
        all_headers.update(headers)
    if limiter:
        limiter.wait()
    try:
        response = requests.get(url, params=params, headers=all_headers, timeout=timeout)
    except requests.RequestException as exc:
        raise ApiError(url, None, f"{type(exc).__name__}: {exc}") from exc
    if not response.ok:
        raise ApiError(url, response.status_code, response.text[:200])
    return response.text


def download_binary(
    url: str,
    destination,
    headers: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
    timeout: int = 300,
) -> int:
    """Streaming a binary file to disk and returning the number of bytes written."""
    all_headers = {"User-Agent": user_agent()}
    if headers:
        all_headers.update(headers)
    if limiter:
        limiter.wait()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, headers=all_headers, timeout=timeout, stream=True) as response:
            if not response.ok:
                raise ApiError(url, response.status_code, response.text[:200])
            written = 0
            with destination.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
                    written += len(chunk)
        return written
    except requests.RequestException as exc:
        raise ApiError(url, None, f"{type(exc).__name__}: {exc}") from exc
