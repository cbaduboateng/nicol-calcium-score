"""Static ticker reference data for dashboard enrichment.

This is a hand-curated table covering the universe of tickers the
asymmetric filter currently surfaces (defence primes, defence-tech
mid/small caps, plus a few utilities/consumer names that appear in the
synthetic tape). Production users should replace this with a live
yfinance / Finnhub / Polygon lookup, cached on disk.

Cap buckets use rough common conventions:
  - mega   : > $200B
  - large  : $10B - $200B
  - mid    : $2B  - $10B
  - small  : $300M - $2B
  - micro  : < $300M

`why_it_matters` is a one-sentence layperson hook explaining why a
congressional trade in this name is worth a second look.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TickerFact:
    ticker: str
    name: str
    exchange: str
    cap: str            # mega / large / mid / small / micro
    sector: str
    summary: str = ""        # one-paragraph plain-English description (optional)
    why_it_matters: str = "" # one sentence: why this name is signal-worthy


_FACTS: dict[str, TickerFact] = {
    "LMT": TickerFact(
        "LMT", "Lockheed Martin", "NYSE", "large", "Defence prime",
        "The largest US defence contractor. Builds the F-35 fighter jet, "
        "missile-defence systems, satellites and helicopters. About 70% of "
        "revenue comes from the US government.",
        "Trades around US defence-budget hearings, big foreign-military-sales "
        "decisions, or year-end Pentagon contract awards are worth attention.",
    ),
    "RTX": TickerFact(
        "RTX", "RTX Corporation (Raytheon)", "NYSE", "large", "Defence prime",
        "Formed by the Raytheon / United Technologies merger. Makes missiles "
        "(Patriot, Stinger, Tomahawk), Pratt & Whitney jet engines, and "
        "Collins Aerospace avionics.",
        "Foreign-military-sales news and missile-resupply contracts to allies "
        "are the usual catalysts.",
    ),
    "NOC": TickerFact(
        "NOC", "Northrop Grumman", "NYSE", "large", "Defence prime",
        "Builds the B-21 Raider stealth bomber, the Sentinel ICBM "
        "modernisation programme, and a large slice of US classified "
        "intelligence-systems work.",
        "Very exposed to classified-budget shifts — committee-only "
        "information moves the stock disproportionately.",
    ),
    "GD": TickerFact(
        "GD", "General Dynamics", "NYSE", "large", "Defence prime",
        "Makes the Abrams tank, Virginia-class submarines, Gulfstream "
        "business jets, and runs a large IT-services arm (GDIT) selling "
        "to federal agencies.",
        "Submarine and tank programme funding cycles are deterministic; "
        "Gulfstream demand is a non-defence cyclical kicker.",
    ),
    "HII": TickerFact(
        "HII", "Huntington Ingalls Industries", "NYSE", "mid", "Defence shipbuilder",
        "America's largest military shipbuilder. Builds Navy aircraft "
        "carriers and submarines at Newport News and Pascagoula.",
        "Single-customer (US Navy) and heavily exposed to multi-year ship "
        "construction contracts.",
    ),
    "LDOS": TickerFact(
        "LDOS", "Leidos", "NYSE", "mid", "Defence IT services",
        "Provides IT and engineering services to defence, intelligence and "
        "civilian-agency customers. Big in cyber, health-IT for the VA, and "
        "airport-screening systems.",
        "Recompetes on huge multi-year services contracts; wins or losses "
        "move the stock 5-10% in a day.",
    ),
    "BAH": TickerFact(
        "BAH", "Booz Allen Hamilton", "NYSE", "mid", "Defence consulting",
        "Management and technology consulting firm whose largest customer "
        "is the US intelligence community and DoD.",
        "Civilian-agency budget shifts and intelligence-community "
        "appropriations are direct drivers.",
    ),
    "CACI": TickerFact(
        "CACI", "CACI International", "NYSE", "mid", "Defence IT services",
        "IT, electronic warfare and intelligence services to US federal "
        "customers, particularly the intelligence community.",
        "Smaller and more catalyst-sensitive than the primes — a single "
        "classified contract can move it 8%+.",
    ),
    "SAIC": TickerFact(
        "SAIC", "Science Applications International Corp", "NASDAQ", "mid",
        "Defence IT services",
        "Technical services contractor focused on defence, intelligence and "
        "space; major NASA and Space Force engineering partner.",
        "Space-Force and NASA budget allocations drive earnings; small "
        "enough that contract wins matter.",
    ),
    "TXT": TickerFact(
        "TXT", "Textron", "NYSE", "mid", "Aerospace / defence",
        "Owns Bell helicopters, Cessna and Beechcraft business jets, and "
        "various military-vehicle programmes.",
        "Bell's FLRAA Future Long-Range Assault Aircraft programme is the "
        "big multi-decade defence catalyst.",
    ),
    "TDY": TickerFact(
        "TDY", "Teledyne Technologies", "NYSE", "mid", "Defence electronics",
        "Maker of imaging sensors, avionics, marine instruments and test "
        "equipment used heavily in defence and aerospace.",
        "Less government-concentrated than primes, more sensitive to "
        "specific subsystem contract awards.",
    ),
    "AXON": TickerFact(
        "AXON", "Axon Enterprise", "NASDAQ", "large", "Public-safety tech",
        "Makes Tasers, body cameras and the Evidence.com cloud platform "
        "used by most US police departments. Expanding into federal and "
        "military markets.",
        "Federal law-enforcement procurement is a recent growth lane — "
        "Congressional appropriations for DOJ, DHS, ATF directly translate "
        "to orders.",
    ),
    "PLTR": TickerFact(
        "PLTR", "Palantir Technologies", "NASDAQ", "mega", "Defence software",
        "Builds Gotham (intelligence-analyst software for defence and "
        "intelligence customers) and Foundry (commercial data platform). "
        "Major Army TITAN and Maven contracts.",
        "Highly exposed to classified-programme renewals; valuation premium "
        "means small news moves it sharply.",
    ),
    "KTOS": TickerFact(
        "KTOS", "Kratos Defense & Security", "NASDAQ", "small",
        "Defence small-cap",
        "Makes unmanned aerial systems (Valkyrie attritable drones), "
        "satellite communications and rocket systems. A 'small-prime' "
        "play on the future of warfare.",
        "Drone-and-autonomy budget growth is the structural story; single "
        "contract wins can move the stock 15%+.",
    ),
    "AVAV": TickerFact(
        "AVAV", "AeroVironment", "NASDAQ", "small", "Defence small-cap",
        "Makes the Switchblade loitering munition and Puma small UAS — "
        "key kit in the Ukraine war and US Army small-drone programmes.",
        "Munitions resupply orders and small-UAS programmes-of-record are "
        "the catalysts; very high asymmetric upside on individual wins.",
    ),
    "MRCY": TickerFact(
        "MRCY", "Mercury Systems", "NASDAQ", "small", "Defence electronics",
        "Trusted-electronics supplier providing secure processors, RF and "
        "signal-processing subsystems to defence prime contractors.",
        "A bet on classified subsystem content within larger prime "
        "programmes; small enough that prime customer wins flow through.",
    ),
    "T": TickerFact(
        "T", "AT&T", "NYSE", "large", "Telecom",
        "US wireless carrier (one of the big three) and fixed-line / "
        "fibre operator. Sells spectrum-licensed services and FirstNet, "
        "the dedicated public-safety LTE network.",
        "Regulated dividend-payer; congressional trades here often "
        "signal spectrum or telecom-policy intelligence.",
    ),
    "F": TickerFact(
        "F", "Ford Motor Company", "NYSE", "large", "Auto manufacturer",
        "The legacy US auto manufacturer; F-series pickups are the "
        "highest-volume vehicle in America. Ongoing EV transition and "
        "Ford Pro commercial business.",
        "EV subsidy / tariff policy and CAFE standards are the "
        "policy-sensitive catalysts.",
    ),
    "DUK": TickerFact(
        "DUK", "Duke Energy", "NYSE", "large", "Regulated utility",
        "Regulated electric utility serving the Carolinas, Florida, "
        "Indiana, Ohio and Kentucky. Big build-out of natural-gas and "
        "renewable generation.",
        "Energy-policy, tax-credit (IRA) and rate-case decisions drive "
        "long-run earnings; defensive but politically exposed.",
    ),
    "NEE": TickerFact(
        "NEE", "NextEra Energy", "NYSE", "large", "Utility / renewables",
        "Florida-regulated utility (Florida Power & Light) plus the "
        "largest US developer of wind and solar generation through "
        "NextEra Energy Resources.",
        "IRA tax-credit policy and interest-rate moves are the dominant "
        "drivers; small policy shifts cause big revaluations.",
    ),
}


# Minimal coverage for the long tail of common congressional-trade tickers.
# Just name / exchange / cap / sector — no narrative. The detail card will
# render only the meta line for these.
_MINIMAL: tuple[tuple[str, str, str, str, str], ...] = (
    # ---- mega-cap tech ----
    ("AAPL", "Apple", "NASDAQ", "mega", "Tech hardware"),
    ("MSFT", "Microsoft", "NASDAQ", "mega", "Tech software"),
    ("GOOGL", "Alphabet (Class A)", "NASDAQ", "mega", "Tech / advertising"),
    ("GOOG", "Alphabet (Class C)", "NASDAQ", "mega", "Tech / advertising"),
    ("AMZN", "Amazon", "NASDAQ", "mega", "E-commerce / cloud"),
    ("NVDA", "NVIDIA", "NASDAQ", "mega", "Semiconductors / AI"),
    ("META", "Meta Platforms", "NASDAQ", "mega", "Social media"),
    ("TSLA", "Tesla", "NASDAQ", "mega", "EVs / energy"),
    ("BRK.B", "Berkshire Hathaway", "NYSE", "mega", "Conglomerate"),
    # ---- large-cap tech ----
    ("NFLX", "Netflix", "NASDAQ", "large", "Streaming media"),
    ("ORCL", "Oracle", "NYSE", "large", "Enterprise software"),
    ("CRM", "Salesforce", "NYSE", "large", "Enterprise software"),
    ("ADBE", "Adobe", "NASDAQ", "large", "Creative software"),
    ("INTC", "Intel", "NASDAQ", "large", "Semiconductors"),
    ("AMD", "Advanced Micro Devices", "NASDAQ", "large", "Semiconductors"),
    ("QCOM", "Qualcomm", "NASDAQ", "large", "Semiconductors / wireless"),
    ("AVGO", "Broadcom", "NASDAQ", "mega", "Semiconductors / infra software"),
    ("TXN", "Texas Instruments", "NASDAQ", "large", "Analog semiconductors"),
    ("MU", "Micron Technology", "NASDAQ", "large", "Memory semiconductors"),
    ("AMAT", "Applied Materials", "NASDAQ", "large", "Semiconductor equipment"),
    ("LRCX", "Lam Research", "NASDAQ", "large", "Semiconductor equipment"),
    ("KLAC", "KLA Corporation", "NASDAQ", "large", "Semiconductor equipment"),
    ("ASML", "ASML Holding", "NASDAQ", "mega", "Semiconductor equipment"),
    ("IBM", "IBM", "NYSE", "large", "Enterprise IT"),
    ("CRWD", "CrowdStrike", "NASDAQ", "large", "Cybersecurity"),
    ("PANW", "Palo Alto Networks", "NASDAQ", "large", "Cybersecurity"),
    ("NOW", "ServiceNow", "NYSE", "large", "Enterprise SaaS"),
    ("SNOW", "Snowflake", "NYSE", "large", "Data cloud"),
    ("INTU", "Intuit", "NASDAQ", "large", "SMB software"),
    ("CSCO", "Cisco Systems", "NASDAQ", "large", "Networking hardware"),
    ("HPQ", "HP Inc", "NYSE", "large", "PCs / printers"),
    ("DELL", "Dell Technologies", "NYSE", "large", "PCs / enterprise IT"),
    # ---- pharma / biotech ----
    ("PFE", "Pfizer", "NYSE", "large", "Pharma"),
    ("MRK", "Merck & Co", "NYSE", "large", "Pharma"),
    ("JNJ", "Johnson & Johnson", "NYSE", "mega", "Pharma / consumer health"),
    ("LLY", "Eli Lilly", "NYSE", "mega", "Pharma (GLP-1, oncology)"),
    ("ABBV", "AbbVie", "NYSE", "mega", "Pharma"),
    ("BMY", "Bristol-Myers Squibb", "NYSE", "large", "Pharma"),
    ("AMGN", "Amgen", "NASDAQ", "large", "Biotech"),
    ("GILD", "Gilead Sciences", "NASDAQ", "large", "Biotech (HIV, oncology)"),
    ("MRNA", "Moderna", "NASDAQ", "mid", "Biotech / mRNA"),
    ("REGN", "Regeneron Pharmaceuticals", "NASDAQ", "large", "Biotech"),
    ("VRTX", "Vertex Pharmaceuticals", "NASDAQ", "large", "Biotech (CF, sickle cell)"),
    ("ABT", "Abbott Laboratories", "NYSE", "large", "Medical devices / diagnostics"),
    ("MDT", "Medtronic", "NYSE", "large", "Medical devices"),
    ("TMO", "Thermo Fisher Scientific", "NYSE", "large", "Lab equipment"),
    ("ISRG", "Intuitive Surgical", "NASDAQ", "large", "Surgical robotics"),
    ("DHR", "Danaher", "NYSE", "large", "Life sciences / diagnostics"),
    ("ZTS", "Zoetis", "NYSE", "large", "Animal health"),
    ("CVS", "CVS Health", "NYSE", "large", "Pharmacy / insurance"),
    ("UNH", "UnitedHealth Group", "NYSE", "mega", "Health insurance"),
    ("HUM", "Humana", "NYSE", "large", "Health insurance"),
    ("ELV", "Elevance Health", "NYSE", "large", "Health insurance"),
    ("CI", "Cigna Group", "NYSE", "large", "Health insurance"),
    # ---- financials ----
    ("JPM", "JPMorgan Chase", "NYSE", "mega", "Universal bank"),
    ("BAC", "Bank of America", "NYSE", "mega", "Universal bank"),
    ("WFC", "Wells Fargo", "NYSE", "large", "Universal bank"),
    ("C", "Citigroup", "NYSE", "large", "Universal bank"),
    ("GS", "Goldman Sachs", "NYSE", "large", "Investment bank"),
    ("MS", "Morgan Stanley", "NYSE", "large", "Investment bank / wealth mgmt"),
    ("SCHW", "Charles Schwab", "NYSE", "large", "Brokerage"),
    ("AXP", "American Express", "NYSE", "large", "Payment cards"),
    ("V", "Visa", "NYSE", "mega", "Payment network"),
    ("MA", "Mastercard", "NYSE", "mega", "Payment network"),
    ("BX", "Blackstone", "NYSE", "large", "Alternative asset manager"),
    ("BLK", "BlackRock", "NYSE", "large", "Asset manager"),
    ("COIN", "Coinbase Global", "NASDAQ", "large", "Crypto exchange"),
    ("USB", "U.S. Bancorp", "NYSE", "large", "Regional bank"),
    ("PNC", "PNC Financial", "NYSE", "large", "Regional bank"),
    ("PAYX", "Paychex", "NASDAQ", "large", "Payroll services"),
    # ---- industrials ----
    ("BA", "Boeing", "NYSE", "large", "Aerospace / defence"),
    ("CAT", "Caterpillar", "NYSE", "large", "Construction equipment"),
    ("GE", "GE Aerospace", "NYSE", "large", "Aerospace engines"),
    ("MMM", "3M", "NYSE", "large", "Diversified industrial"),
    ("HON", "Honeywell", "NASDAQ", "large", "Diversified industrial"),
    ("UNP", "Union Pacific", "NYSE", "large", "Rail freight"),
    ("UPS", "United Parcel Service", "NYSE", "large", "Logistics / parcel"),
    ("FDX", "FedEx", "NYSE", "large", "Logistics / parcel"),
    ("DE", "Deere & Company", "NYSE", "large", "Agricultural equipment"),
    ("EMR", "Emerson Electric", "NYSE", "large", "Industrial automation"),
    ("ETN", "Eaton", "NYSE", "large", "Power management"),
    # ---- consumer ----
    ("WMT", "Walmart", "NYSE", "mega", "Retail / grocery"),
    ("COST", "Costco Wholesale", "NASDAQ", "mega", "Membership retail"),
    ("HD", "Home Depot", "NYSE", "large", "Home improvement retail"),
    ("LOW", "Lowe's", "NYSE", "large", "Home improvement retail"),
    ("TGT", "Target", "NYSE", "large", "General merchandise retail"),
    ("MCD", "McDonald's", "NYSE", "large", "Quick-service restaurants"),
    ("SBUX", "Starbucks", "NASDAQ", "large", "Coffee retail"),
    ("KO", "Coca-Cola", "NYSE", "large", "Beverages"),
    ("PEP", "PepsiCo", "NASDAQ", "large", "Beverages / snacks"),
    ("NKE", "Nike", "NYSE", "large", "Athletic apparel"),
    ("DIS", "Walt Disney", "NYSE", "large", "Media / theme parks"),
    ("PG", "Procter & Gamble", "NYSE", "mega", "Consumer staples"),
    ("CL", "Colgate-Palmolive", "NYSE", "large", "Consumer staples"),
    ("KMB", "Kimberly-Clark", "NYSE", "large", "Consumer staples"),
    # ---- energy ----
    ("XOM", "ExxonMobil", "NYSE", "mega", "Integrated oil & gas"),
    ("CVX", "Chevron", "NYSE", "large", "Integrated oil & gas"),
    ("COP", "ConocoPhillips", "NYSE", "large", "E&P oil & gas"),
    ("EOG", "EOG Resources", "NYSE", "large", "E&P oil & gas"),
    ("SLB", "Schlumberger", "NYSE", "large", "Oilfield services"),
    ("OXY", "Occidental Petroleum", "NYSE", "large", "E&P oil & gas"),
    # ---- telecom ----
    ("VZ", "Verizon Communications", "NYSE", "large", "Telecom"),
    ("TMUS", "T-Mobile US", "NASDAQ", "large", "Telecom"),
    # ---- real estate / REITs ----
    ("AMT", "American Tower", "NYSE", "large", "Cell tower REIT"),
    ("CCI", "Crown Castle", "NYSE", "large", "Cell tower REIT"),
    ("EQIX", "Equinix", "NASDAQ", "large", "Data centre REIT"),
    ("PLD", "Prologis", "NYSE", "large", "Industrial REIT"),
    ("O", "Realty Income", "NYSE", "large", "Net-lease REIT"),
    # ---- transport / travel ----
    ("DAL", "Delta Air Lines", "NYSE", "large", "Airlines"),
    ("UAL", "United Airlines", "NASDAQ", "large", "Airlines"),
    ("AAL", "American Airlines", "NASDAQ", "mid", "Airlines"),
    ("LUV", "Southwest Airlines", "NYSE", "mid", "Airlines"),
    ("ABNB", "Airbnb", "NASDAQ", "large", "Short-term rentals"),
    ("BKNG", "Booking Holdings", "NASDAQ", "large", "Online travel"),
    ("UBER", "Uber Technologies", "NYSE", "large", "Ride-share / delivery"),
    # ---- misc widely-traded ----
    ("STT", "State Street", "NYSE", "large", "Custody bank"),
    ("F", "Ford Motor", "NYSE", "large", "Auto manufacturer"),
)

for _t, _n, _x, _c, _s in _MINIMAL:
    _FACTS.setdefault(_t, TickerFact(
        ticker=_t, name=_n, exchange=_x, cap=_c, sector=_s,
    ))


def lookup(ticker: str) -> TickerFact | None:
    return _FACTS.get((ticker or "").upper())


def known_tickers() -> set[str]:
    return set(_FACTS.keys())


def all_facts() -> list[TickerFact]:
    return list(_FACTS.values())
