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
    summary: str        # one-paragraph plain-English description
    why_it_matters: str # one sentence: why this name is signal-worthy


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


def lookup(ticker: str) -> TickerFact | None:
    return _FACTS.get((ticker or "").upper())


def known_tickers() -> set[str]:
    return set(_FACTS.keys())


def all_facts() -> list[TickerFact]:
    return list(_FACTS.values())
