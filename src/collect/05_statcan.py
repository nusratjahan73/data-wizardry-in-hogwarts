"""Collecting Canadian monthly retail trade sales and the consumer price index.

Reading: config.yaml (sources.statcan).
Writing: data/raw/statcan/csv/<product_id>.csv  (the table itself)
         data/raw/statcan/json/<product_id>_metadata.json  (dimensions and members)
Runtime: two to four minutes, mostly download and unzip.

My whole retail argument stands on this source. Without a Canadian monthly sales series I have no
measured seasonality, and my timing argument would have to rest on a stated assumption.

I use two routes, chosen per table. I pull the retail tables in bulk, because I read thirty NAICS
categories from each, so one request is simpler than thirty. I pull the CPI table as one series by
coordinate. Its bulk download is 162MB, with 30 geographies and 359 product groups, and I only use
Canada and All-items, which is 1,351 rows or 0.12 per cent of it. If the coordinate breaks because
Statistics Canada renumbers a member, I fall back to the bulk download.

I collect two retail tables. Table 20-10-0056 is active but starts in 2017, which is too short to
measure a seasonal pattern. Table 20-10-0008 covers 1991 to 2022 but was archived in December 2022.
Chaining them on the 2017 to 2022 overlap gives me a series long enough to decompose, and the
overlap lets me check the join. The chaining happens in my cleaning script, because collection never
changes the data.

This source returns two formats, so I use the subfolders data/raw/statcan/csv and
data/raw/statcan/json.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import requests

from src.utils.config import get, user_agent
from src.utils.http import ApiError, RateLimiter, get_json
from src.utils.io import relative, save_raw
from src.utils.logging_setup import RunTimer, get_logger, log_data_issue

SCRIPT = "05_statcan"
SOURCE = "statcan"
logger = get_logger(SCRIPT)


def fetch_metadata(base_url: str, product_id: int, limiter: RateLimiter) -> dict | None:
    """Pulling the cube metadata, which names every dimension member.

    I save this next to the data because the CSV only has member names as text.
    A reader who wants to know which codes exist, or whether a table is flagged
    archived, should not have to call the API again.
    """
    url = f"{base_url}/getCubeMetadata"
    limiter.wait()
    try:
        response = requests.post(
            url,
            json=[{"productId": product_id}],
            headers={"User-Agent": user_agent(), "Content-Type": "application/json"},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{product_id}",
            f"cube metadata request failed: {type(exc).__name__}: {exc}",
            "metadata skipped; the table download was still attempted",
        )
        return None

    if not payload or payload[0].get("status") != "SUCCESS":
        log_data_issue(
            SCRIPT,
            f"{SOURCE}.{product_id}",
            f"cube metadata returned status {payload[0].get('status') if payload else 'empty'}",
            "metadata skipped",
        )
        return None

    return payload[0]["object"]


def summarise_metadata(metadata: dict) -> dict:
    """Cutting the metadata down to the parts a reader would really look at."""
    return {
        "product_id": metadata.get("productId"),
        "title_en": metadata.get("cubeTitleEn"),
        "start_date": metadata.get("cubeStartDate"),
        "end_date": metadata.get("cubeEndDate"),
        "archived": metadata.get("archived"),
        "frequency_code": metadata.get("frequencyCode"),
        "dimensions": [
            {
                "name": dimension.get("dimensionNameEn"),
                "member_count": len(dimension.get("member", [])),
                "members": [
                    {
                        "id": member.get("memberId"),
                        "code": member.get("classificationCode"),
                        "name": member.get("memberNameEn"),
                    }
                    for member in dimension.get("member", [])
                ],
            }
            for dimension in metadata.get("dimension", [])
        ],
    }


def download_series(base_url: str, spec: dict, limiter: RateLimiter) -> int:
    """Fetching one series by coordinate, so I do not download the whole table.

    The CPI table is 162MB and I only use Canada and All-items, which is 1,351
    rows. Asking for that one cell returns about 300KB. I write it with the same
    columns as the bulk CSV, so 14_clean_statcan.py does not need to know which
    route I took. I return the row count, or 0 so the caller can use the bulk file.
    """
    product_id = int(spec["product_id"])
    body = [{
        "productId": product_id,
        "coordinate": spec["coordinate"],
        "latestN": int(spec.get("max_periods", 1500)),
    }]

    limiter.wait()
    try:
        response = requests.post(
            f"{base_url}/getDataFromCubePidCoordAndLatestNPeriods",
            json=body,
            headers={"User-Agent": user_agent(), "Content-Type": "application/json"},
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}",
            f"series request failed: {type(exc).__name__}: {exc}",
            "falling back to the full table download, which is larger but needs no coordinate",
        )
        return 0

    if not payload or payload[0].get("status") != "SUCCESS":
        status = payload[0].get("status") if payload else "empty response"
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}",
            f"series request returned status {status}, most likely a renumbered coordinate",
            "falling back to the full table download",
        )
        return 0

    points = payload[0]["object"].get("vectorDataPoint", [])
    if not points:
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}",
            "series request succeeded but returned no data points",
            "falling back to the full table download",
        )
        return 0

    rows = [
        {
            "REF_DATE": point["refPer"][:7],
            "GEO": spec.get("geography_member", ""),
            "Products and product groups": spec.get("product_member", ""),
            "VALUE": point.get("value"),
        }
        for point in points
    ]
    frame = pd.DataFrame(rows)

    target = save_raw(
        SOURCE,
        f"csv/{product_id}.csv",
        frame.to_csv(index=False),
        source_url=f"{base_url}/getDataFromCubePidCoordAndLatestNPeriods",
        product_id=product_id,
        rows=len(frame),
        coordinate=spec["coordinate"],
        vector_id=payload[0]["object"].get("vectorId"),
        note=(
            "one series fetched by coordinate rather than the whole table. The bulk "
            "download of this cube is 162MB and this project uses 0.12 per cent of it."
        ),
    )
    logger.info(
        "saved series %s (%s, %s), %d rows -> %s",
        product_id, spec.get("geography_member"), spec.get("product_member"),
        len(frame), relative(target),
    )
    return len(frame)


def download_table(base_url: str, product_id: int, limiter: RateLimiter) -> int:
    """Downloading and unzipping one full table into data/raw/statcan/csv.

    I return the number of data rows written, or 0 if it failed.
    """
    try:
        pointer = get_json(
            f"{base_url}/getFullTableDownloadCSV/{product_id}/en",
            limiter=limiter,
            logger=logger,
        )
    except ApiError as exc:
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}", f"download URL request failed: {exc}",
            "table skipped", severity="error",
        )
        return 0

    if pointer.get("status") != "SUCCESS" or not pointer.get("object"):
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}",
            f"download endpoint returned status {pointer.get('status')}",
            "table skipped", severity="error",
        )
        return 0

    zip_url = pointer["object"]
    limiter.wait()
    try:
        response = requests.get(zip_url, headers={"User-Agent": user_agent()}, timeout=600)
        response.raise_for_status()
    except requests.RequestException as exc:
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}", f"zip download failed: {exc}",
            "table skipped", severity="error",
        )
        return 0

    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except zipfile.BadZipFile as exc:
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}", f"downloaded file was not a valid zip: {exc}",
            "table skipped", severity="error",
        )
        return 0

    # Keeping only the data CSV from the archive, named <product_id>.csv. The archive
    # also holds a metadata CSV, but I skip it because I already save the richer JSON
    # metadata from the API, which is easier to read.
    data_names = [n for n in archive.namelist() if n.lower().endswith(".csv") and "MetaData" not in n]
    if not data_names:
        log_data_issue(
            SCRIPT, f"{SOURCE}.{product_id}", "zip contained no data CSV",
            "table skipped", severity="error",
        )
        return 0

    body = archive.read(data_names[0]).decode("utf-8-sig", errors="replace")
    row_count = max(body.count("\n") - 1, 0)

    target = save_raw(
        SOURCE,
        f"csv/{product_id}.csv",
        body,
        source_url=zip_url,
        product_id=product_id,
        rows=row_count,
        archive_member=data_names[0],
    )
    logger.info("saved table %s, %d rows -> %s", product_id, row_count, relative(target))
    return row_count


def main() -> None:
    base_url = get("sources.statcan.base_url")
    tables: dict[str, dict] = get("sources.statcan.tables")
    limiter = RateLimiter(2.0)

    with RunTimer(SCRIPT, logger) as run:
        total_rows = 0
        succeeded = 0

        for key, spec in tables.items():
            product_id = int(spec["product_id"])
            logger.info("collecting %s (%s, %s)", key, spec["table_number"], spec["status"])

            metadata = fetch_metadata(base_url, product_id, limiter)
            if metadata:
                summary = summarise_metadata(metadata)
                # Checking the archived flag, which is "1" for inactive tables and "2" for active ones.
                if str(summary.get("archived")) == "1":
                    log_data_issue(
                        SCRIPT,
                        f"{SOURCE}.{spec['table_number']}",
                        f"table is flagged archived, coverage ends {str(summary.get('end_date'))[:10]}",
                        "collected deliberately for history before 2017 and chained "
                        "with the active table on their overlap",
                        severity="note",
                    )
                save_raw(
                    SOURCE,
                    f"json/{product_id}_metadata.json",
                    summary,
                    source_url=f"{base_url}/getCubeMetadata",
                    product_id=product_id,
                )

            rows = 0
            if spec.get("mode") == "series":
                rows = download_series(base_url, spec, limiter)
            if not rows:
                rows = download_table(base_url, product_id, limiter)
            if rows:
                succeeded += 1
                total_rows += rows

        run.rows_out = total_rows
        run.note = f"{succeeded}/{len(tables)} tables downloaded"

        if succeeded == 0:
            log_data_issue(
                SCRIPT,
                SOURCE,
                "no StatCan table could be downloaded",
                "stage 2 gate fails; the retail argument must fall back to a stated "
                "assumption and say so prominently, as I planned for this case",
                severity="critical",
            )

    logger.info("StatCan collection complete: %d tables, %d rows", succeeded, total_rows)


if __name__ == "__main__":
    main()
