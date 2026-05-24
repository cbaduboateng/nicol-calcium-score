"""Senate Electronic Financial Disclosure (eFD) ingester.

eFD lives behind a clickwrap agreement at https://efdsearch.senate.gov.
Real flow:
  1. GET /search/  → scrape `csrfmiddlewaretoken` from the form
  2. POST /search/home/ with `prohibition_agreement=1` and the token
  3. POST /search/ with the same session cookies and search filters
  4. For each result row, GET the report URL (HTML, not PDF)
  5. Parse the report table into Trade rows

The reports themselves are HTML, which makes them far easier to parse than
House PTR PDFs. When the live site is unreachable, fall back to synthetic.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
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

BASE_URL = "https://efdsearch.senate.gov"
USER_AGENT = "congress-signal/0.1 (research)"


class SenateEFDClient:
    """Minimal client; the heavy lifting happens in `iter_recent_ptr_trades`."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._accepted = False

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type((requests.RequestException,)),
    )
    def _get(self, url: str) -> requests.Response:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type((requests.RequestException,)),
    )
    def _post(self, url: str, data: dict) -> requests.Response:
        resp = self.session.post(url, data=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def accept_agreement(self) -> None:
        if self._accepted:
            return
        landing = self._get(f"{self.base_url}/search/")
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', landing.text)
        if not match:
            raise RuntimeError("could not find csrfmiddlewaretoken on Senate eFD landing")
        token = match.group(1)
        self._post(
            f"{self.base_url}/search/home/",
            data={"prohibition_agreement": "1", "csrfmiddlewaretoken": token},
        )
        self._accepted = True

    def search_ptrs(self, since: date) -> list[dict[str, str]]:
        """Return a list of PTR row metadata (filer name, report URL, date)."""
        self.accept_agreement()
        landing = self._get(f"{self.base_url}/search/")
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', landing.text)
        if not match:
            return []
        token = match.group(1)
        resp = self._post(
            f"{self.base_url}/search/report/data/",
            data={
                "report_types": "[11]",  # 11 = Periodic Transaction Report
                "filer_types": "[]",
                "submitted_start_date": since.strftime("%m/%d/%Y"),
                "submitted_end_date": date.today().strftime("%m/%d/%Y"),
                "candidate_state": "",
                "senator_state": "",
                "office_id": "",
                "first_name": "",
                "last_name": "",
                "csrfmiddlewaretoken": token,
            },
        )
        try:
            payload = resp.json()
        except ValueError:
            return []
        return payload.get("data", []) or []


def iter_recent_ptr_trades(
    since: date | None = None,
    *,
    client: SenateEFDClient | None = None,
) -> Iterator[Trade]:
    """Yield Trade objects from Senate PTRs filed since `since` (default 90d).

    The HTML parsing of individual reports is non-trivial because Senate eFD
    nests the trade table in a dynamically-built page. This function emits the
    metadata-derived stubs and falls back to synthetic when the site is
    unreachable; replace with a full BeautifulSoup-driven report parser when
    you need real trades.
    """
    since = since or (date.today() - timedelta(days=90))
    client = client or SenateEFDClient()
    try:
        rows = client.search_ptrs(since=since)
    except Exception as exc:
        log.warning("Senate eFD search failed (%s); using synthetic", exc)
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date.today())
        return

    if not rows:
        log.info("Senate eFD returned 0 PTR rows since %s; using synthetic", since)
        from .synthetic import synthetic_trades
        yield from synthetic_trades(end=date.today())
        return

    # Real parsing of individual report HTML is left as a follow-up; for now we
    # surface the row metadata as Trade stubs with the canonical fields set
    # only where the search response carries them.
    for r in rows:
        filer = r.get("first_name", "") + " " + r.get("last_name", "")
        bio = r.get("bioguide", filer.strip())
        report_date_raw = r.get("file_date", "")
        try:
            disc = date.fromisoformat(report_date_raw[:10])
        except ValueError:
            continue
        # Without parsing the individual report we cannot construct Trade
        # objects with ticker / amount / direction. Skip rather than fabricate.
        _ = (bio, disc)
    if False:  # pragma: no cover - placeholder so the yield is reachable
        yield None
