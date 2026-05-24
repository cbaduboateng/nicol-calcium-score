from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

from congress_signal.ingest import house_ptr


def _build_zip(tmp_path: Path, xml_body: str) -> Path:
    zip_path = tmp_path / "2024FD.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("2024FD.xml", xml_body)
    return zip_path


def test_parse_index_extracts_rows(tmp_path: Path):
    xml = """<FinancialDisclosure>
      <Member>
        <Prefix>Hon</Prefix>
        <Last>Defence</Last>
        <First>Alex</First>
        <BioguideID>A000001</BioguideID>
        <DocID>20012345</DocID>
        <FilingType>P</FilingType>
        <FilingDate>3/14/2024</FilingDate>
      </Member>
      <Member>
        <Last>Energy</Last>
        <First>Bea</First>
        <BioguideID>B000002</BioguideID>
        <DocID>20012346</DocID>
        <FilingType>A</FilingType>
        <FilingDate>5/1/2024</FilingDate>
      </Member>
    </FinancialDisclosure>"""
    zip_path = _build_zip(tmp_path, xml)
    rows = house_ptr.parse_index(zip_path)
    assert len(rows) == 2
    assert rows[0]["BioguideID"] == "A000001"
    assert rows[0]["FilingType"] == "P"


def test_ingest_year_falls_back_to_synthetic_on_download_failure(tmp_path: Path):
    with patch.object(house_ptr, "download_year", return_value=None):
        trades = list(house_ptr.ingest_year(2024, tmp_path))
    assert trades, "synthetic fallback should yield trades"


def test_parse_ptr_pdf_returns_empty_without_pdfplumber(tmp_path: Path):
    # Build minimal not-a-real PDF; the function should fail soft when
    # pdfplumber is absent or the PDF is invalid.
    trades = house_ptr.parse_ptr_pdf(b"not a pdf", actor_id="A", doc_id="X")
    assert trades == []


def test_latest_disclosure_year_lags_in_january():
    from datetime import date
    assert house_ptr.latest_disclosure_year(date(2025, 1, 15)) == 2024
    assert house_ptr.latest_disclosure_year(date(2025, 3, 1)) == 2025
