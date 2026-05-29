"""OGE 278 / 278-T executive-branch disclosure ingester.

PAS (Presidentially Appointed Senate-confirmed) and OGE-278T filings are
posted at:

https://extapps2.oge.gov/Web/278eFile.nsf/PAS+Index

The index pages list individuals and link to PDF disclosures. PDF parsing
requires `pdfplumber`; install via `pip install icarus[pdf]`.

This adapter:
1. Downloads the PAS index HTML, caches it
2. Lets you filter by name (e.g. "Trump, Donald J")
3. Downloads and caches the matching PDF
4. Returns the PDF path; PDF→Trade extraction lives in `parse_oge_pdf`

On any failure the iterator falls back to synthetic data.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..schema import AssetType, Direction, Owner, Trade

log = logging.getLogger(__name__)

PAS_INDEX_URL = "https://extapps2.oge.gov/Web/278eFile.nsf/PAS+Index"


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _get(url: str, timeout: float = 60.0) -> requests.Response:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp


def download_pas_index(cache_dir: Path) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "pas_index.html"
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return cache_file
    try:
        resp = _get(PAS_INDEX_URL)
    except Exception as exc:
        log.warning("OGE PAS index fetch failed (%s)", exc)
        return None
    cache_file.write_text(resp.text, encoding="utf-8", errors="replace")
    return cache_file


def find_filings(index_html: str, name_substring: str) -> list[tuple[str, str]]:
    """Return ``(display_name, pdf_url)`` pairs whose display name contains
    `name_substring`.

    OGE's Notes-rendered HTML is brittle; we look for anchors that link to
    `.pdf` and have visible text near them containing the name.
    """
    pattern = re.compile(
        r'<a [^>]*href="([^"]+\.pdf)"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )
    needle = name_substring.lower()
    results: list[tuple[str, str]] = []
    for m in pattern.finditer(index_html):
        href, text = m.group(1), m.group(2)
        if needle in text.lower():
            results.append((text.strip(), href))
    return results


def parse_oge_pdf(pdf_path: Path) -> list[Trade]:
    """Extract Trade rows from an OGE 278 PDF.

    Requires `pdfplumber`. Returns an empty list if not installed (so the
    pipeline keeps moving instead of crashing). Real implementations should
    write per-template parsers; this one targets the standard schedule A
    holdings + schedule B (transactions) tables.
    """
    try:
        import pdfplumber  # type: ignore[import-not-found]
    except BaseException as exc:  # noqa: BLE001 - native deps can panic, not raise
        log.warning(
            "pdfplumber unavailable (%s); cannot parse %s. "
            "Install with `pip install icarus[pdf]`",
            exc, pdf_path,
        )
        return []

    trades: list[Trade] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    header = [(c or "").lower() for c in table[0]]
                    if not any("transaction" in h for h in header):
                        continue
                    # Schedule B has columns roughly:
                    # # | Description (asset) | EIF | Type | Date | Amount | Comments
                    for row in table[1:]:
                        if len(row) < 6 or not row[1]:
                            continue
                        asset_desc = (row[1] or "").strip()
                        ticker_match = re.search(r"\(([A-Z\.]{1,6})\)", asset_desc)
                        if not ticker_match:
                            continue
                        ticker = ticker_match.group(1)
                        txn_type = (row[3] or "").lower()
                        if "purchase" in txn_type or "buy" in txn_type:
                            direction = Direction.BUY
                        elif "sale" in txn_type or "sell" in txn_type:
                            direction = Direction.SELL
                        else:
                            continue
                        date_str = (row[4] or "").strip()
                        try:
                            txn_date = date.fromisoformat(date_str)
                        except ValueError:
                            continue
                        # Amounts in OGE 278 use the same brackets as House PTRs.
                        amt = (row[5] or "").strip()
                        lo, hi = 0.0, 0.0
                        m = re.search(r"\$?([\d,]+)\s*-\s*\$?([\d,]+)", amt)
                        if m:
                            lo = float(m.group(1).replace(",", ""))
                            hi = float(m.group(2).replace(",", ""))
                        trades.append(Trade(
                            trade_id=f"oge-{pdf_path.stem}-{ticker}-{txn_date}",
                            actor_id=pdf_path.stem,
                            transaction_date=txn_date,
                            disclosure_date=txn_date,  # approximate
                            ticker=ticker,
                            asset_type=AssetType.STOCK,
                            direction=direction,
                            amount_min_usd=lo,
                            amount_max_usd=hi,
                            owner=Owner.SELF,
                            source="oge_278",
                        ))
    except Exception as exc:
        log.warning("Failed parsing %s (%s)", pdf_path, exc)
    return trades


def iter_individual_trades(
    name_substring: str,
    cache_dir: Path | str = "data/cache/oge",
) -> Iterator[Trade]:
    """Yield Trade rows from every OGE PDF matching `name_substring`.

    Falls back to synthetic on any failure.
    """
    cache_dir = Path(cache_dir)
    index = download_pas_index(cache_dir)
    if index is None:
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date.today())
        return

    matches = find_filings(index.read_text(encoding="utf-8"), name_substring)
    if not matches:
        log.info("No OGE filings matched %r; using synthetic", name_substring)
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date.today())
        return

    pdf_dir = cache_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for display, url in matches:
        slug = re.sub(r"[^a-z0-9]+", "-", display.lower()).strip("-")
        pdf_path = pdf_dir / f"{slug}.pdf"
        if not pdf_path.exists():
            try:
                resp = _get(url)
                pdf_path.write_bytes(resp.content)
            except Exception as exc:
                log.warning("Could not download %s (%s)", url, exc)
                continue
        yield from parse_oge_pdf(pdf_path)
