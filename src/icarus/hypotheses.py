"""The hypothesis ledger: every idea this project has tested, and how it died.

The transferable core of the "AI investment laboratory" idea is not
finding trades — it's the memory: a permanent, honest record of which
hypotheses were tested, how, and what the data said. Rejections are the
most valuable rows (they are the ideas that would have cost money), so
they are never deleted, only appended to.

Statuses:
  adopted     — passed the pre-registered bar; live in the tool
  rejected    — tested and failed; kept as a tombstone
  monitoring  — promising but under-sampled; re-test as data grows
  untestable  — cannot be validated with available data; context-only
  proposed    — queued for a future Lab design
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

HYPOTHESES_PATH = Path("data/hypotheses.csv")
VALID_STATUSES = {"adopted", "rejected", "monitoring", "untestable", "proposed"}
COLUMNS = ["id", "date", "hypothesis", "test", "verdict", "status"]


def load_hypotheses(path: Path | str = HYPOTHESES_PATH) -> pd.DataFrame:
    """Read the ledger; empty frame (with columns) when missing."""
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(p, dtype=str).fillna("")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    bad = set(df["status"]) - VALID_STATUSES
    if bad:
        log.warning("hypotheses.csv has unknown statuses: %s", bad)
    return df[COLUMNS]


def ledger_summary(df: pd.DataFrame) -> dict[str, int]:
    """Counts per status — the tool's kill-rate at a glance."""
    if df.empty:
        return {}
    return df["status"].value_counts().to_dict()
