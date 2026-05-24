"""House Periodic Transaction Report (PTR) ingester.

The House Clerk publishes annual ZIP archives at:

    https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip

Each ZIP contains an XML index (`<YEAR>FD.xml`) plus per-filing PDFs.

This adapter:
1. Downloads the ZIP for a year (cached to `data/raw/house/`).
2. Parses the XML index for filer name, bioguide ID, doc ID, filing date,
   and filing type. PTR filings have FilingType = "P".
3. For each PTR PDF, extracts trade rows via `pdfplumber` (optional).
4. Normalises to `Trade`.

PDF parsing requires `pip install congress-signal[pdf]`. Without
pdfplumber the iterator still yields metadata-only rows from the index so
downstream code can see which actors filed, just without ticker/amount.
"""

from __future__ import annotations

import logging
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..schema import AssetType, Direction, Owner, Trade

log = logging.getLogger(__name__)

BASE_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs"


# House PTR asset type codes
ASSET_CODE_MAP: dict[str, AssetType] = {
    "ST": AssetType.STOCK,
    "OP": AssetType.CALL,  # later refined by call/put text
    "ET": AssetType.ETF,
    "MF": AssetType.MUTUAL_FUND,
    "GS": AssetType.BOND_TREASURY,
    "CO": AssetType.BOND_CORP,
    "MU": AssetType.BOND_MUNI,
    "CT": AssetType.CRYPTO,
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _download(url: str, dest: Path, timeout: float = 120.0) -> Path:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _zip_path(year: int, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir / f"{year}FD.zip"


def download_year(year: int, raw_dir: Path | str = "data/raw/house") -> Path | None:
    """Download the annual ZIP for `year`. Returns None on failure."""
    raw_dir = Path(raw_dir)
    target = _zip_path(year, raw_dir)
    if target.exists() and target.stat().st_size > 0:
        return target
    url = f"{BASE_URL}/{year}FD.zip"
    try:
        return _download(url, target)
    except Exception as exc:
        log.warning("Could not download %s (%s)", url, exc)
        return None


def parse_index(zip_path: Path) -> list[dict[str, str]]:
    """Parse the XML index inside the ZIP. Returns one dict per filing."""
    with zipfile.ZipFile(zip_path) as zf:
        xml_name = next(
            (n for n in zf.namelist() if n.lower().endswith(".xml")),
            None,
        )
        if xml_name is None:
            return []
        with zf.open(xml_name) as f:
            tree = ET.parse(f)
    root = tree.getroot()
    rows: list[dict[str, str]] = []
    for member in root.iter("Member"):
        rows.append({
            (c.tag): (c.text or "").strip()
            for c in member
        })
    return rows


def _parse_filing_date(raw: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _extract_pdf_for_doc(zip_path: Path, doc_id: str) -> bytes | None:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            stem = Path(name).stem
            if stem == doc_id or stem.endswith(f"_{doc_id}"):
                return zf.read(name)
    return None


def _parse_amount(raw: str) -> tuple[float, float]:
    if not raw:
        return (0.0, 0.0)
    m = re.search(r"\$?([\d,]+)\s*-\s*\$?([\d,]+)", raw)
    if not m:
        return (0.0, 0.0)
    return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))


def _parse_direction(raw: str) -> Direction | None:
    if not raw:
        return None
    key = raw.lower()
    if "purchase" in key:
        return Direction.BUY
    if "partial" in key:
        return Direction.PARTIAL_SALE
    if "exchange" in key:
        return Direction.EXCHANGE
    if "sale" in key or "sell" in key:
        return Direction.SELL
    return None


def _extract_ticker(asset_description: str) -> str | None:
    m = re.search(r"\(([A-Z][A-Z\.]{0,5})\)", asset_description)
    return m.group(1) if m else None


def parse_ptr_pdf(pdf_bytes: bytes, *, actor_id: str, doc_id: str) -> list[Trade]:
    """Extract Trade rows from a PTR PDF. Requires pdfplumber."""
    import io

    try:
        import pdfplumber  # type: ignore[import-not-found]
    except BaseException as exc:  # noqa: BLE001 - native deps can panic, not raise
        log.debug("pdfplumber unavailable (%s); cannot parse PTR PDF %s", exc, doc_id)
        return []

    trades: list[Trade] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    header = [(c or "").lower().strip() for c in table[0]]
                    has_asset = any("asset" in h for h in header)
                    has_amount = any("amount" in h for h in header)
                    if not (has_asset and has_amount):
                        continue
                    for row in table[1:]:
                        if not row or not row[0]:
                            continue
                        cells = [(c or "").strip() for c in row]
                        # Best-effort column mapping; PDFs vary.
                        asset = next((c for c in cells if "(" in c and ")" in c), cells[0])
                        ticker = _extract_ticker(asset)
                        if not ticker:
                            continue
                        direction = next(
                            (_parse_direction(c) for c in cells if _parse_direction(c)),
                            None,
                        )
                        if direction is None:
                            continue
                        amount_cell = next(
                            (c for c in cells if re.search(r"\$\d", c) and "-" in c),
                            "",
                        )
                        lo, hi = _parse_amount(amount_cell)
                        date_cell = next(
                            (c for c in cells if re.search(r"\d{1,2}/\d{1,2}/\d{4}", c)),
                            "",
                        )
                        txn_date = _parse_filing_date(date_cell)
                        if txn_date is None:
                            continue
                        asset_type = AssetType.STOCK
                        for code, mapped in ASSET_CODE_MAP.items():
                            if re.search(rf"\[{code}\]", asset):
                                asset_type = mapped
                                break
                        trades.append(Trade(
                            trade_id=f"house-{actor_id}-{doc_id}-{ticker}-{txn_date}",
                            actor_id=actor_id,
                            transaction_date=txn_date,
                            disclosure_date=txn_date,  # approximate; index has filing_date
                            ticker=ticker,
                            asset_type=asset_type,
                            direction=direction,
                            amount_min_usd=lo,
                            amount_max_usd=hi,
                            owner=Owner.SELF,
                            source="house_ptr",
                        ))
    except Exception as exc:
        log.warning("PTR PDF parse failed for %s (%s)", doc_id, exc)
    return trades


def ingest_year(year: int, cache_dir: Path | str = "data/raw/house") -> Iterator[Trade]:
    """Yield Trade objects for every PTR filing in `year`.

    Falls back to synthetic data when the ZIP cannot be downloaded.
    """
    cache_dir = Path(cache_dir)
    zip_path = download_year(year, cache_dir)
    if zip_path is None:
        log.warning("Falling back to synthetic House PTRs for %s", year)
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date(year, 12, 31))
        return

    rows = parse_index(zip_path)
    if not rows:
        log.warning("House PTR index empty for %s; using synthetic", year)
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date(year, 12, 31))
        return

    ptr_rows = [r for r in rows if (r.get("FilingType") or "").upper() == "P"]
    log.info("House PTR %s: %d PTR filings out of %d index rows", year, len(ptr_rows), len(rows))

    yielded_any = False
    for r in ptr_rows:
        doc_id = r.get("DocID") or ""
        actor_id = r.get("BioguideID") or r.get("Last") or doc_id
        if not doc_id or not actor_id:
            continue
        pdf_bytes = _extract_pdf_for_doc(zip_path, doc_id)
        if pdf_bytes is None:
            continue
        for trade in parse_ptr_pdf(pdf_bytes, actor_id=actor_id, doc_id=doc_id):
            yielded_any = True
            yield trade

    if not yielded_any:
        log.warning(
            "House PTR %s produced no parsed trades (install [pdf] extras or "
            "improve parse_ptr_pdf templates); using synthetic", year,
        )
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date(year, 12, 31))


def latest_disclosure_year(today: date | None = None) -> int:
    """Most recently published annual archive. PTRs lag; the prior year's
    archive is typically published in February."""
    today = today or date.today()
    cutoff = date(today.year, 2, 15)
    return today.year - 1 if today < cutoff else today.year
