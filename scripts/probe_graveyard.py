"""One-off probe: which of the persistently unpriced tickers are alive?

Runs on a GitHub Actions runner (this sandbox's egress policy blocks
Yahoo). For each ticker in the graveyard list it first tries the
current normalised symbol; on failure it tries curated candidate
symbols (renames, right-exchange listings, corrected OCR mangles).
Candidates were chosen from the watchlist's own name/description
columns, so a rescue is only ever the SAME economic entity the user
originally picked — never a different company that happens to share
the letters.

Writes data/cache/graveyard_probe.json for the pruning pass.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402

from icarus.symbols import normalize_symbol  # noqa: E402

OUT_PATH = Path("data/cache/graveyard_probe.json")

GRAVEYARD: list[str] = [
    "AIKI", "ALYI", "AMGO", "ANIC", "ANTE", "ASP", "ATHA", "ATIF", "AVGR",
    "AVON", "AY", "AZRE", "BBI", "BBOX", "BFIT", "BFT", "BIFF", "BIOL",
    "BIT:EMC", "BMIX", "BOWL", "BRNT", "CHRG", "CINE", "CLIS", "COOL",
    "CPG", "CSCW", "CSPX", "CVAC", "CWBR", "CWRK", "CYB", "CYRN", "CYTO",
    "DATA", "DEBS", "DOCRF", "DVRG", "EB", "EBNB", "ECAR", "EGEC", "ESGC",
    "ESYS", "ETR:DPW", "ETWO", "EXPI", "FFWD", "FLTA", "FRA:SEN", "FUV",
    "FVE", "GHSI", "GPS", "GTHX", "GVP", "GWS", "HEC", "HEMO", "HTRY",
    "HYVE", "IDEX", "INRG", "IPG", "ISR", "ISUN", "IUKD", "IWMD", "IWMO",
    "JP", "KMPH", "LNGA", "LOCK", "LOIL", "LON:AFC", "LON:CBX", "LON:CCL",
    "LON:HUM", "LON:SIS", "LON:SMRT", "LON:augm", "LSYN", "MANO", "MDGS",
    "METX", "MKGI", "MOGO", "MOON", "MPW", "NANO", "ND", "NPF", "NUCG",
    "NVIGF", "NYSE:BODY", "NYSE:EMBI", "OBSV", "OCN", "ODX", "ONVO",
    "ORPH", "ORTX", "OSMT", "OSTK", "OTCMKTS:KHOTF", "PCPL", "PCTI",
    "PEI", "PHSP", "PLL", "POAI", "PSTG", "PSTI", "PTVE", "PURP", "QRTEA",
    "RAPT", "RBTX", "RLGY", "RMGR", "RMO", "RNDR-USD", "RWLK", "SALT",
    "SAVA", "SCR", "SCWX", "SECO", "SEEL", "SFR", "SHCO", "SINO", "SLGG",
    "SMDS", "SOL", "STIC", "STSA", "SVA", "SWI", "SYN", "TKAT", "TRMR",
    "UROV", "USAT", "VERO", "VJET", "VMEO", "VMOM", "VVI", "XAN", "XSPX",
    "ZOM", "ZUO", "ZYXI",
]

# ticker -> ordered candidate Yahoo symbols to try when the primary fails.
# Each candidate is the same company/fund the watchlist row describes:
# a rename, the correct home-exchange listing, or a corrected symbol.
CANDIDATES: dict[str, list[str]] = {
    "AIKI": ["DVLT"],            # AIkido Pharma -> Datavault AI
    "ANIC": ["ANIC.L"],          # Agronomics (AIM)
    "ASP": ["ASP.AX"],           # Aspermont (ASX)
    "ATHA": ["ATHA.CN"],         # Athena Gold (CSE)
    "AVON": ["AVON.L"],          # Avon Technologies (LSE)
    "BBOX": ["BBOX.L"],          # Tritax Big Box (LSE)
    "BFIT": ["BFIT.AS"],         # Basic-Fit (Amsterdam)
    "BFT": ["PSFE"],             # Foley Trasimene SPAC -> Paysafe
    "BOWL": ["BOWL.L"],          # Hollywood Bowl Group (LSE)
    "BRNT": ["BRNT.L"],          # WisdomTree Brent Crude ETC
    "CHRG": ["CHRG.L", "VOLT.L"],  # WisdomTree Battery Solutions UCITS
    "CLIS": ["CLIS.TA"],         # Clal Insurance (Tel Aviv)
    "CPG": ["CPG.L"],            # Compass Group (LSE)
    "CSPX": ["CSPX.L"],          # iShares Core S&P 500 UCITS
    "CYB": ["CYB.TO"],           # Cymbria (Toronto)
    "CYTO": ["CYTO.V"],          # Cytophage (TSXV)
    "DATA": ["DATA.L"],          # GlobalData (AIM)
    "DEBS": ["LABD"],            # Direxion S&P Biotech Bear 3x
    "EBNB": ["BMBL"],            # Bumble (mangled symbol)
    "ECAR": ["ECAR.L"],          # iShares Electric Vehicles UCITS
    "ESYS": ["ESYS.L"],          # essensys (AIM)
    "ETR:DPW": ["DHL.DE"],       # Deutsche Post -> DHL Group
    "FFWD": ["FFWD.L"],          # Fast Forward Innovations (AIM)
    "GPS": ["GPS.CN"],           # Great Plains Metals (CSE)
    "GWS": ["GWO.TO"],           # Great-West Lifeco (Toronto)
    "HEC": ["TALK"],             # Hudson Executive SPAC -> Talkspace
    "HEMO": ["HEMO.L"],          # Hemogenyx (LSE)
    "INRG": ["INRG.L"],          # iShares Global Clean Energy UCITS
    "ISR": ["CATX"],             # IsoRay -> Perspective Therapeutics
    "ISUN": ["ISUN.L"],          # Invesco Solar Energy UCITS
    "IUKD": ["IUKD.L"],          # iShares UK Dividend UCITS
    "IWMD": ["IWMD.L"],          # iShares world ETF (GBP line)
    "IWMO": ["IWMO.L"],          # iShares MSCI World Momentum UCITS
    "KMPH": ["ZVRA"],            # KemPharm -> Zevra Therapeutics
    "LOCK": ["LOCK.L"],          # iShares Digital Security UCITS
    "LOIL": ["LOIL.L"],          # WisdomTree WTI Crude ETC
    "MANO": ["MANO.L"],          # Manolete Partners (AIM)
    "METX": ["METX.CN"],         # ME Therapeutics (CSE)
    "MKGI": ["NTRP"],            # Monaker Group -> NextTrip
    "MOON": ["MOON.L"],          # Moonpig Group (LSE)
    "NANO": ["NANO.L"],          # Nanoco Group (LSE)
    "ND": ["JWN"],               # Nordstrom (mangled symbol)
    "NPF": ["NPF.NZ"],           # Smart NZ Property ETF
    "NUCG": ["NUCG.L"],          # VanEck Uranium & Nuclear UCITS
    "NVIGF": ["NVDA"],           # NVIDIA (OTC line -> primary)
    "NYSE:BODY": ["BODI"],       # Beachbody -> BODi
    "NYSE:EMBI": ["ERJ"],        # Embraer ADR (mangled symbol)
    "OSTK": ["BYON"],            # Overstock -> Beyond
    "ODX": ["ODX.L"],            # Omega Diagnostics (AIM)
    "PHSP": ["PHSP.L", "PHAG.L"],  # WisdomTree Physical Silver
    "PLL": ["ELVR"],             # Piedmont Lithium -> Elevra Lithium
    "PSTI": ["PLUR"],            # Pluristem -> Pluri
    "PURP": ["PRPL"],            # Purple Innovation (mangled symbol)
    "QRTEA": ["QVCGA"],          # Qurate -> QVC Group
    "RBTX": ["RBTX.L"],          # iShares Automation & Robotics UCITS
    "RLGY": ["HOUS"],            # Realogy -> Anywhere Real Estate
    "RNDR-USD": ["RENDER-USD"],  # Render token migration
    "RWLK": ["LFWD"],            # ReWalk -> Lifeward
    "SINO": ["SGLY"],            # Sino-Global -> Singularity Future
    "SMDS": ["SMDS.L"],          # DS Smith (LSE)
    "SWI": ["0019.HK"],          # Swire Pacific A (Hong Kong)
    "TRMR": ["NEXN"],            # Tremor International -> Nexxen
    "USAT": ["CTLP"],            # USA Technologies -> Cantaloupe
    "VMOM": ["VMOM.L", "VFMO"],  # Vanguard momentum factor lines
    "VVI": ["PRSU"],             # Viad -> Pursuit Attractions
    "XAN": ["ACR"],              # Exantas -> ACRES Commercial Realty
    "XSPX": ["XSPX.L"],          # Xtrackers S&P 500 Swap UCITS
    "ZOM": ["GTM", "ZI"],        # ZoomInfo (renamed ticker)
}


def _probe(symbols: list[str], chunk: int = 25) -> dict[str, dict]:
    """Fetch 3 months of daily closes; return per-symbol last date/close."""
    hits: dict[str, dict] = {}
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        try:
            df = yf.download(batch, period="3mo", interval="1d",
                             progress=False, group_by="ticker",
                             threads=True, auto_adjust=True)
        except Exception as exc:  # noqa: BLE001
            print(f"chunk failed ({exc}); retrying singly")
            df = None
        for s in batch:
            closes = pd.Series(dtype=float)
            if df is not None:
                try:
                    closes = (df[s]["Close"] if len(batch) > 1
                              else df["Close"]).dropna()
                except Exception:  # noqa: BLE001
                    closes = pd.Series(dtype=float)
            if not closes.empty:
                hits[s] = {
                    "last_date": closes.index[-1].date().isoformat(),
                    "last_close": float(closes.iloc[-1]),
                    "n_sessions": int(len(closes)),
                }
        time.sleep(2)
    return hits


def main() -> int:
    primary = {t: normalize_symbol(t) for t in GRAVEYARD}
    hits = _probe(sorted(set(primary.values())))

    results: dict[str, dict] = {}
    need_candidates: list[str] = []
    for t in GRAVEYARD:
        sym = primary[t]
        if sym in hits:
            results[t] = {"status": "alive", "symbol": sym, **hits[sym]}
        else:
            need_candidates.append(t)

    cand_syms = sorted({s for t in need_candidates
                        for s in CANDIDATES.get(t, [])})
    cand_hits = _probe(cand_syms) if cand_syms else {}
    for t in need_candidates:
        rescued = next((s for s in CANDIDATES.get(t, []) if s in cand_hits),
                       None)
        if rescued:
            results[t] = {"status": "rescued", "symbol": rescued,
                          **cand_hits[rescued]}
        else:
            results[t] = {"status": "dead", "symbol": primary[t],
                          "tried": [primary[t]] + CANDIDATES.get(t, [])}

    counts = {"alive": 0, "rescued": 0, "dead": 0}
    for r in results.values():
        counts[r["status"]] += 1
    print(f"alive={counts['alive']} rescued={counts['rescued']} "
          f"dead={counts['dead']}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, indent=1, sort_keys=True))
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
