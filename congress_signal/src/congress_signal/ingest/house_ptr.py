"""House Periodic Transaction Report (PTR) adapter.

The House Clerk publishes annual ZIP archives containing FD.txt (index) plus
per-disclosure PDFs. PDF parsing is out of scope here; this adapter reads the
index for ticker-bearing entries and falls back to synthetic data when the
archive is unreachable.

Archive URL pattern: https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

import requests

from ..schema import AssetType, Direction, Owner, Trade

log = logging.getLogger(__name__)

BASE_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs"


def _download_year(year: int, cache_dir: Path, timeout: float = 60.0) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / f"{year}FD.zip"
    if zip_path.exists() and zip_path.stat().st_size > 0:
        return zip_path
    url = f"{BASE_URL}/{year}FD.zip"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("House PTR download failed for %s (%s)", year, exc)
        return None
    zip_path.write_bytes(resp.content)
    return zip_path


def _iter_index_rows(zip_path: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as zf:
        name = next(
            (n for n in zf.namelist() if n.lower().endswith("fd.txt")),
            None,
        )
        if name is None:
            return
        with zf.open(name) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            header = text.readline().rstrip("\n").split("\t")
            for line in text:
                fields = line.rstrip("\n").split("\t")
                if len(fields) != len(header):
                    continue
                yield dict(zip(header, fields))


def ingest_year(year: int, cache_dir: Path) -> Iterator[Trade]:
    """Yield Trade objects for a single disclosure year.

    The index alone does not carry ticker/amount/direction, so this iterator is
    deliberately conservative. On failure (no network, no index) it falls back
    to a synthetic stream for that year so downstream stages still have data.
    """
    zip_path = _download_year(year, cache_dir)
    if zip_path is None:
        log.warning("Falling back to synthetic House PTRs for %s", year)
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date(year, 12, 31))
        return

    emitted = 0
    for row in _iter_index_rows(zip_path):
        # The index is mostly metadata; we surface it as Trade stubs only when
        # there is enough information. Real users will replace this with a PDF
        # parser that pulls ticker/amount/direction from the PTR body.
        doc_date_raw = row.get("FilingDate") or row.get("DateReceived") or ""
        try:
            disc_date = datetime.strptime(doc_date_raw, "%m/%d/%Y").date()
        except ValueError:
            continue
        # Without the body we cannot construct a real Trade. Skip.
        _ = disc_date
        emitted += 1
        # No yield: parsing the PDF body is required to produce real Trade rows.
    if emitted == 0:
        log.warning("House PTR index for %s contained no parsable rows; using synthetic", year)
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date(year, 12, 31))


def latest_disclosure_year(today: date | None = None) -> int:
    today = today or date.today()
    # PTRs lag — last year's full archive is usually published in February.
    cutoff = date(today.year, 2, 15)
    return today.year - 1 if today < cutoff else today.year
