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

import json
import logging
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


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


# Long-tail coverage. Each entry is either:
#   - a 5-tuple (ticker, name, exchange, cap, sector) when we have no narrative yet
#   - a 7-tuple (..., summary, why_it_matters) for the names that are common
#     in congressional trades and merit a proper lay-person explanation
_EXTRA: tuple[tuple, ...] = (
    # ---- mega-cap tech ----
    ("AAPL", "Apple", "NASDAQ", "mega", "Tech hardware",
     "The iPhone is the most profitable consumer-hardware franchise in history; Mac, iPad, AirPods, Watch and a fast-growing Services arm (App Store, iCloud, Pay) round it out. About a fifth of revenue is Greater China.",
     "China supply-chain risk, App Store antitrust (Epic v Apple, EU DMA), and engineering-talent immigration policy are the recurring policy axes."),
    ("MSFT", "Microsoft", "NASDAQ", "mega", "Tech software",
     "Two businesses bundled: Office / Windows (still printing cash) and Azure cloud (the #2 hyperscaler, ~25% share). Plus a ~$13B stake in OpenAI that powers Copilot products across the stack.",
     "Activision merger review set antitrust precedents; DoD JWCC cloud-share allocations and AI export-control / EU AI Act rules are the live policy fronts."),
    ("NVDA", "NVIDIA", "NASDAQ", "mega", "Semiconductors / AI",
     "Dominates AI compute — their H100 / B200 GPUs power roughly 90% of AI training in the world. Also datacentre networking (via Mellanox), automotive and gaming graphics.",
     "US export controls to China and CHIPS Act allocations are the dominant policy levers; any committee-level signal here is direct macro-AI exposure."),
    ("GOOGL", "Alphabet (Class A)", "NASDAQ", "mega", "Tech / advertising",
     "Search and YouTube ads are the cash cow; Google Cloud is the #3 hyperscaler. Plus Waymo (robotaxis), DeepMind / Gemini, Android and a portfolio of moonshots.",
     "The DOJ won the search-monopoly case in 2024; remedies are pending. Antitrust is the dominant catalyst, plus AI policy and ad-tech regulation."),
    ("GOOG", "Alphabet (Class C)", "NASDAQ", "mega", "Tech / advertising",
     "Same underlying business as GOOGL; this is the non-voting share class. Liquidity profile differs slightly.",
     "Same policy exposure as GOOGL."),
    ("AMZN", "Amazon", "NASDAQ", "mega", "E-commerce / cloud",
     "Retail e-commerce + AWS (the largest hyperscaler at ~30% share) + ads (third-largest US ad business). AWS is the profit engine; retail is mostly gross-margin-thin scale.",
     "FTC antitrust suit on retail practices is unresolved; AWS depends on federal cloud contract share; labour rules on warehouse / driver classification are recurring."),
    ("NVDA", "NVIDIA", "NASDAQ", "mega", "Semiconductors / AI"),  # placeholder, overwritten above
    ("META", "Meta Platforms", "NASDAQ", "mega", "Social media",
     "Instagram, Facebook, WhatsApp and Threads collectively reach ~4B people. Reality Labs (Quest VR/AR) is a multi-billion-a-year loss. Heavy AI / Llama investment.",
     "Section 230 reform, FTC privacy actions, EU Digital Services Act fines, and any TikTok ban that redirects ad budgets all move the stock."),
    ("TSLA", "Tesla", "NASDAQ", "mega", "EVs / energy",
     "The world's most-valuable automaker, but the bull case is increasingly 'AI / robotics' (Full Self-Driving, Optimus humanoid, Dojo training compute) rather than pure car-making. EV market share is losing to BYD and legacy OEMs.",
     "EV tax credits (IRA), tariffs on Chinese EVs, and autonomous-vehicle regulation are the policy axes; Musk's politics now influence the stock more than fundamentals."),
    ("BRK.B", "Berkshire Hathaway", "NYSE", "mega", "Conglomerate",
     "Buffett's holding company — insurance (GEICO + reinsurance), railroads (BNSF), energy (BHE) and a ~$300B equity portfolio (top holdings: AAPL, BAC, KO, AXP, CVX).",
     "Less policy-sensitive than peers; biggest swings come from Buffett disposing of major positions (e.g. Apple cuts in 2024)."),
    # ---- large-cap tech / semi ----
    ("NFLX", "Netflix", "NASDAQ", "large", "Streaming media",
     "Subscription streaming with ~280M paid members, an ad-supported tier, and a crackdown on password sharing. Spends ~$17B/yr on content.",
     "EU 'fair-share' telecom levies, content quotas, and US streaming regulation are the policy angles."),
    ("ORCL", "Oracle", "NYSE", "large", "Enterprise software",
     "Enterprise databases (Oracle Database, MySQL), Oracle Cloud Infrastructure (OCI), and ERP / HCM SaaS. OCI is the fastest-growing major cloud for AI workloads (OpenAI, xAI deals).",
     "TikTok data-hosting partnership, DoD cloud contracts via JWCC, and AI training-data regulation."),
    ("CRM", "Salesforce", "NYSE", "large", "Enterprise software",
     "The dominant CRM (Customer Relationship Management) SaaS, plus Tableau (data viz), Slack, MuleSoft and Marketing Cloud. Big push into 'Agentforce' AI agents.",
     "Antitrust scrutiny on roll-up acquisitions, AI agent regulation, federal IT contract awards."),
    ("ADBE", "Adobe", "NASDAQ", "large", "Creative software",
     "Creative Cloud (Photoshop, Premiere, Illustrator), Document Cloud (PDF) and Experience Cloud (marketing analytics).",
     "The blocked 2023 Figma acquisition set antitrust precedent for creative-software roll-ups; AI-generated-content rules (Firefly) are next."),
    ("INTC", "Intel", "NASDAQ", "large", "Semiconductors",
     "The original American chipmaker — CPUs (Core, Xeon), a struggling foundry-services business, and Mobileye (auto). Receiving massive CHIPS Act subsidies for new fabs in Arizona, Ohio and Israel.",
     "CHIPS Act allocations are the dominant near-term driver; congressional decisions on fab funding move the stock directly."),
    ("AMD", "Advanced Micro Devices", "NASDAQ", "large", "Semiconductors",
     "CPU + GPU competitor to Intel and NVIDIA. EPYC server CPUs are taking share; MI300 AI GPUs are NVIDIA's only credible challenger.",
     "Same CHIPS Act dynamics as INTC; export controls to China have affected MI300 sales."),
    ("QCOM", "Qualcomm", "NASDAQ", "large", "Semiconductors / wireless",
     "Mobile chipsets (Snapdragon) and the IP-licensing business that prints money on every cellphone. Pushing into automotive and edge AI.",
     "Export controls to Huawei, 5G / 6G policy, and the long-running licensing disputes with Apple."),
    ("AVGO", "Broadcom", "NASDAQ", "mega", "Semiconductors / infra software",
     "Networking and storage chips, plus a major infrastructure-software empire (post-VMware acquisition). Custom AI accelerators for Google are a strategic edge.",
     "CHIPS Act exposure plus VMware antitrust-integration risk."),
    ("TXN", "Texas Instruments", "NASDAQ", "large", "Analog semiconductors"),
    ("MU", "Micron Technology", "NASDAQ", "large", "Memory semiconductors",
     "One of three global memory makers (with Samsung and SK Hynix). DRAM and NAND flash for everything from phones to AI servers.",
     "Export controls to China and CHIPS Act subsidies for the Idaho fab; memory pricing is highly cyclical."),
    ("AMAT", "Applied Materials", "NASDAQ", "large", "Semiconductor equipment",
     "Makes the equipment fabs use to deposit, etch and inspect silicon wafers — picks-and-shovels play on the entire semi capex cycle.",
     "Commerce Department export controls on selling advanced tools to Chinese fabs are the dominant risk."),
    ("LRCX", "Lam Research", "NASDAQ", "large", "Semiconductor equipment",
     "Etch and deposition equipment, especially for memory and advanced logic. Pure-play semi equipment picks-and-shovels.",
     "The single largest exposure to US semiconductor export controls — Commerce Department rules on sales to Chinese fabs can move the stock 5%+ in a day."),
    ("KLAC", "KLA Corporation", "NASDAQ", "large", "Semiconductor equipment",
     "Semiconductor process-control and inspection equipment. Smaller than AMAT / LRCX but consistently higher margin.",
     "Export-control exposure to China."),
    ("ASML", "ASML Holding", "NASDAQ", "mega", "Semiconductor equipment",
     "Dutch monopolist on EUV lithography — the machines needed to make sub-7nm chips. The strategic chokepoint of the global semiconductor supply chain.",
     "The Netherlands has restricted EUV sales to China under US pressure; arguably the single most policy-sensitive ticker in the entire semi complex."),
    ("IBM", "IBM", "NYSE", "large", "Enterprise IT",
     "Hybrid cloud (Red Hat), enterprise consulting, AI (watsonx), and mainframes still throwing off cash. Spun off the infrastructure-services arm (Kyndryl) in 2021.",
     "Federal IT recompetes and AI procurement rules; less policy-sensitive than peers."),
    ("CRWD", "CrowdStrike", "NASDAQ", "large", "Cybersecurity",
     "The leading endpoint cybersecurity platform (Falcon), used by ~60% of the Fortune 100 with heavy federal / DoD penetration. Recovered from the July 2024 global outage.",
     "Federal cybersecurity policy (CISA spending) and Section 702 surveillance reauthorisation."),
    ("PANW", "Palo Alto Networks", "NASDAQ", "large", "Cybersecurity",
     "Cybersecurity — network firewalls (Prisma), Secure Access Service Edge (SASE), and security operations (Cortex). Similar federal exposure to CrowdStrike.",
     "Federal cyber-budget cycle and the platform-consolidation thesis."),
    ("NOW", "ServiceNow", "NYSE", "large", "Enterprise SaaS",
     "IT service-management SaaS — workflow automation across enterprise IT, HR and customer service. Heavy federal and state government adoption.",
     "Federal IT modernisation budgets; macro IT-spend cyclicality."),
    ("SNOW", "Snowflake", "NYSE", "large", "Data cloud"),
    ("INTU", "Intuit", "NASDAQ", "large", "SMB software",
     "TurboTax, QuickBooks, Credit Karma, Mailchimp. The cash cow is small-business accounting; consumer-tax is the political flashpoint.",
     "IRS Direct File (free government filing) is an existential threat to TurboTax; tax-code complexity is the moat."),
    ("CSCO", "Cisco Systems", "NASDAQ", "large", "Networking hardware",
     "Enterprise networking — switches, routers, plus the recently-acquired Splunk for security analytics.",
     "Federal IT recompetes; tariffs on Chinese / South-east Asian manufacturing."),
    ("HPQ", "HP Inc", "NYSE", "large", "PCs / printers"),
    ("DELL", "Dell Technologies", "NYSE", "large", "PCs / enterprise IT"),
    # ---- pharma / biotech ----
    ("PFE", "Pfizer", "NYSE", "large", "Pharma",
     "Comirnaty (COVID-19), Paxlovid, Eliquis (with BMY), Prevnar 20. The post-COVID revenue cliff and the search for new growth drugs are the story.",
     "FDA approval timing, Medicare drug-price negotiation under IRA, biosimilar competition timing."),
    ("MRK", "Merck & Co", "NYSE", "large", "Pharma",
     "Keytruda is the world's best-selling cancer drug (and faces a 2028 patent cliff). Plus Gardasil HPV vaccine and a deep oncology and ADC pipeline.",
     "IRA Medicare price-negotiation specifically targets Keytruda after patent expiry; FDA timing on follow-on assets is the critical near-term driver."),
    ("JNJ", "Johnson & Johnson", "NYSE", "mega", "Pharma / consumer health",
     "Post-2023 Kenvue spin-off, it's pharma (Stelara, Darzalex, Tremfya) plus medical devices (Ethicon, DePuy). Diversified, defensive cash machine.",
     "Talc litigation remains a recurring overhang; IRA price negotiation hits Stelara directly; CMS reimbursement on devices."),
    ("LLY", "Eli Lilly", "NYSE", "mega", "Pharma (GLP-1, oncology)",
     "Maker of Mounjaro and Zepbound — the GLP-1 weight-loss / diabetes drugs that have re-rated the entire pharma sector. Also Verzenio (breast cancer) and Kisunla (Alzheimer's).",
     "GLP-1 supply visibility, Medicare coverage decisions on obesity drugs, and IRA Medicare price-negotiation timing."),
    ("ABBV", "AbbVie", "NYSE", "mega", "Pharma",
     "Humira generation is winding down; current growth drivers are Skyrizi and Rinvoq (immunology), plus Botox aesthetics.",
     "IRA price negotiation, biosimilar competition for Humira, integration of Allergan."),
    ("BMY", "Bristol-Myers Squibb", "NYSE", "large", "Pharma",
     "Eliquis (anticoagulant, co-marketed with PFE), Opdivo (oncology), and a deep oncology / cell-therapy pipeline.",
     "Eliquis is one of the first 10 drugs subject to Medicare price negotiation under IRA — material near-term catalyst."),
    ("AMGN", "Amgen", "NASDAQ", "large", "Biotech",
     "Enbrel, Repatha, Otezla — plus the Horizon acquisition (rare-disease portfolio). Working on MariTide (GLP-1) as the growth story.",
     "Same IRA dynamics as peers; MariTide trial readouts are catalyst-rich."),
    ("GILD", "Gilead Sciences", "NASDAQ", "large", "Biotech (HIV, oncology)",
     "Biktarvy (HIV) is the cash franchise. Trodelvy (oncology, from the Immunomedics acquisition) is the growth call.",
     "IRA negotiation on HIV drugs, HHS PrEP coverage policy."),
    ("MRNA", "Moderna", "NASDAQ", "mid", "Biotech / mRNA",
     "mRNA platform — COVID vaccine, RSV vaccine, plus a large pipeline (flu, individualised cancer vaccines with MRK). Cash-burning post-COVID.",
     "FDA approvals on flu and cancer assets, BARDA government vaccine procurement."),
    ("REGN", "Regeneron Pharmaceuticals", "NASDAQ", "large", "Biotech"),
    ("VRTX", "Vertex Pharmaceuticals", "NASDAQ", "large", "Biotech (CF, sickle cell)",
     "Cystic fibrosis franchise (Trikafta) is the cash cow. Casgevy (sickle-cell gene therapy, with CRSP) and Journavx (non-opioid pain) are the growth story.",
     "FDA approvals, Medicare / Medicaid pricing on rare-disease drugs."),
    ("ABT", "Abbott Laboratories", "NYSE", "large", "Medical devices / diagnostics",
     "Medical devices (structural heart) and diagnostics (FreeStyle Libre CGM, COVID tests). Diversified, mature.",
     "CMS reimbursement, FDA inspections, formula-recall liability tail."),
    ("MDT", "Medtronic", "NYSE", "large", "Medical devices",
     "Pacemakers, surgical robotics (Hugo), insulin pumps, structural-heart valves.",
     "CMS reimbursement decisions; FDA inspections; surgical-robot competition from ISRG."),
    ("TMO", "Thermo Fisher Scientific", "NYSE", "large", "Lab equipment",
     "Lab equipment, life-sciences reagents, and clinical-research services (PPD).",
     "NIH funding levels, FDA inspection capacity."),
    ("ISRG", "Intuitive Surgical", "NASDAQ", "large", "Surgical robotics",
     "The da Vinci surgical-robot maker. Razor-and-blade model: sell the robot, then earn on instruments per procedure.",
     "CMS reimbursement coding for robotic-assisted procedures."),
    ("DHR", "Danaher", "NYSE", "large", "Life sciences / diagnostics",
     "Life-sciences instruments and diagnostics conglomerate — Beckman Coulter, Cepheid (PCR), Leica, Sciex. Spun off dental and water (Envista, Veralto).",
     "NIH / CDC budget exposure, FDA inspection capacity, pandemic-preparedness budgets."),
    ("ZTS", "Zoetis", "NYSE", "large", "Animal health"),
    ("CVS", "CVS Health", "NYSE", "large", "Pharmacy / insurance",
     "Pharmacies + Aetna health insurance + Caremark PBM. The vertically-integrated drug-supply giant.",
     "PBM transparency legislation, Medicare Advantage rate cuts, pharmacy reimbursement reform."),
    ("UNH", "UnitedHealth Group", "NYSE", "mega", "Health insurance",
     "Largest US health insurer (UnitedHealthcare) + Optum (PBM, provider services, tech). The vertically-integrated health giant.",
     "Medicare Advantage star-rating rules drive the stock; PBM antitrust is the looming political risk."),
    ("HUM", "Humana", "NYSE", "large", "Health insurance",
     "Health insurer, almost entirely Medicare Advantage — a near-pure-play on MA policy.",
     "MA risk-adjustment rule changes and star-rating cuts hit it disproportionately."),
    ("ELV", "Elevance Health", "NYSE", "large", "Health insurance",
     "Anthem rebranded — health insurer with a strong commercial and Medicaid book.",
     "ACA marketplaces, Medicaid redetermination, MA dynamics."),
    ("CI", "Cigna Group", "NYSE", "large", "Health insurance"),
    # ---- financials ----
    ("JPM", "JPMorgan Chase", "NYSE", "mega", "Universal bank",
     "Largest US bank — investment banking, retail, commercial, asset management. Dimon is the de-facto industry spokesman.",
     "Basel III/IV bank-capital rules, CFPB enforcement, interest-rate path."),
    ("BAC", "Bank of America", "NYSE", "mega", "Universal bank",
     "Second-largest US bank; heavy retail deposits and wealth management (Merrill Lynch).",
     "Interest-rate sensitivity, CFPB enforcement, commercial-real-estate exposure."),
    ("WFC", "Wells Fargo", "NYSE", "large", "Universal bank",
     "Major retail bank; finally out from under the 2018 Fed asset cap that crimped growth for years.",
     "Regulatory consent orders, mortgage-market regulation."),
    ("C", "Citigroup", "NYSE", "large", "Universal bank"),
    ("GS", "Goldman Sachs", "NYSE", "large", "Investment bank",
     "Investment bank + trading + asset management. Marcus consumer-bank experiment shut down.",
     "M&A regulatory regime, Basel capital rules, IPO market revival."),
    ("MS", "Morgan Stanley", "NYSE", "large", "Investment bank / wealth mgmt",
     "Investment bank plus the dominant US wealth-management franchise (E*TRADE acquisition).",
     "Wealth-management regulation, M&A volume."),
    ("SCHW", "Charles Schwab", "NYSE", "large", "Brokerage",
     "Largest US retail brokerage post-TD Ameritrade merger. The 'cash-sweep' business is interest-rate sensitive.",
     "Payment-for-order-flow rules (SEC), interest-rate path."),
    ("AXP", "American Express", "NYSE", "large", "Payment cards"),
    ("V", "Visa", "NYSE", "mega", "Payment network",
     "Runs the largest global card-payment network. Toll-taker on most card transactions.",
     "CFPB / DOJ scrutiny on interchange fees; the Credit Card Competition Act recurs every Congress."),
    ("MA", "Mastercard", "NYSE", "mega", "Payment network",
     "Same business as Visa, slightly smaller; international mix is higher.",
     "Same interchange-fee dynamics as V."),
    ("BX", "Blackstone", "NYSE", "large", "Alternative asset manager",
     "Largest alternative asset manager — real estate, private credit, private equity.",
     "SEC private-funds rules, carried-interest tax treatment."),
    ("BLK", "BlackRock", "NYSE", "large", "Asset manager",
     "World's largest asset manager (~$10T AUM). Issuer of iShares ETFs.",
     "ESG backlash from red states (state-pension divestitures); SEC market-structure rules."),
    ("COIN", "Coinbase Global", "NASDAQ", "large", "Crypto exchange",
     "Largest US crypto exchange. The single-stock proxy for US crypto regulation.",
     "SEC enforcement against the exchange; stablecoin legislation; FIT 21 / SAB 121 outcomes."),
    ("USB", "U.S. Bancorp", "NYSE", "large", "Regional bank"),
    ("PNC", "PNC Financial", "NYSE", "large", "Regional bank"),
    ("PAYX", "Paychex", "NASDAQ", "large", "Payroll services",
     "Payroll and HR services for small and mid-market US businesses; one of two scale players (with ADP). Heavy cash-return story.",
     "SMB labour regulation, Employee Retention Credit (ERC) program changes, e-filing mandates."),
    # ---- industrials ----
    ("BA", "Boeing", "NYSE", "large", "Aerospace / defence",
     "Commercial aircraft (737 MAX, 787, 777X) + defence (F-15, F/A-18, KC-46, Air Force One). Plagued by quality and safety issues since the 737-MAX crashes.",
     "FAA approvals (737 MAX-7 / -10 still pending), DoD contract overruns, Spirit AeroSystems re-acquisition."),
    ("CAT", "Caterpillar", "NYSE", "large", "Construction equipment",
     "Construction and mining equipment globally. Cyclical with commodity prices and infrastructure spending.",
     "Infrastructure Investment and Jobs Act project starts, mining permits, tariffs on China."),
    ("GE", "GE Aerospace", "NYSE", "large", "Aerospace engines",
     "Jet engines (CFM with Safran, GE9X). Post 2024 spin-offs of GE Vernova (energy) and GE HealthCare.",
     "Air Force NGAP engine contract, commercial-aviation cycle, sanctions-driven aftermarket."),
    ("MMM", "3M", "NYSE", "large", "Diversified industrial",
     "Diversified industrial — adhesives, electronics, abrasives, masks. Settled massive PFAS and combat-arms-earplugs litigation in 2023-24.",
     "Ongoing PFAS regulation and EPA designations."),
    ("HON", "Honeywell", "NASDAQ", "large", "Diversified industrial",
     "Aerospace components, building automation, performance materials, warehouse robotics. Activist-led break-up underway.",
     "Defence-aerospace contracts; building-efficiency / decarbonisation regulation."),
    ("UNP", "Union Pacific", "NYSE", "large", "Rail freight"),
    ("UPS", "United Parcel Service", "NYSE", "large", "Logistics / parcel",
     "US parcel logistics duopolist with FedEx. Heavy Teamsters union exposure.",
     "E-commerce volumes, USPS regulatory boundary, fuel/diesel taxes, Teamsters bargaining."),
    ("FDX", "FedEx", "NYSE", "large", "Logistics / parcel",
     "US and international parcel and air freight; the other half of the logistics duopoly with UPS.",
     "E-commerce volumes, USPS regulatory boundary, fuel/diesel taxes, drone-delivery rule-making."),
    ("DE", "Deere & Company", "NYSE", "large", "Agricultural equipment",
     "Agricultural and construction equipment, precision-ag technology, financing arm.",
     "Farm-bill subsidies, right-to-repair regulation, China tariffs."),
    ("EMR", "Emerson Electric", "NYSE", "large", "Industrial automation"),
    ("ETN", "Eaton", "NYSE", "large", "Power management"),
    # ---- consumer ----
    ("WMT", "Walmart", "NYSE", "mega", "Retail / grocery",
     "Largest US retailer. Pushing aggressively into healthcare (Walmart Health clinics) and a fast-growing advertising business.",
     "Minimum-wage legislation, antitrust scrutiny on healthcare M&A, China sourcing tariffs."),
    ("COST", "Costco Wholesale", "NASDAQ", "mega", "Membership retail",
     "Membership warehouse retail. Famously low-margin, high-loyalty, consumer-friendly pricing.",
     "Less direct policy than peers; immigration policy affects the bulk-buyer base."),
    ("HD", "Home Depot", "NYSE", "large", "Home improvement retail",
     "Home improvement retailer, #1 in the US. Heavy pro-contractor exposure on top of the DIY consumer.",
     "Housing-market activity, mortgage rates, immigration policy (labour pool), tariffs on Chinese tools."),
    ("LOW", "Lowe's", "NYSE", "large", "Home improvement retail",
     "Home improvement #2, more DIY-consumer than HD.",
     "Same dynamics as HD."),
    ("TGT", "Target", "NYSE", "large", "General merchandise retail",
     "General-merchandise retailer, second to Walmart in US share. Recovering from Pride-month boycotts and shoplifting losses.",
     "Tariffs on Chinese imports, shoplifting / Organized Retail Crime legislation."),
    ("MCD", "McDonald's", "NYSE", "large", "Quick-service restaurants",
     "World's largest quick-service restaurant chain.",
     "California FAST Act minimum-wage law, franchise regulation, weight-loss-drug effects on consumer spend."),
    ("SBUX", "Starbucks", "NASDAQ", "large", "Coffee retail",
     "Global coffee retailer. Brian Niccol-led turnaround in progress after a rough 2024.",
     "Unionisation policy (NLRB rulings), minimum-wage legislation."),
    ("KO", "Coca-Cola", "NYSE", "large", "Beverages",
     "Largest non-alcoholic beverage maker globally.",
     "Sugar-tax legislation (limited to specific cities/states), plastic-packaging regulation."),
    ("PEP", "PepsiCo", "NASDAQ", "large", "Beverages / snacks",
     "Beverages plus Frito-Lay snacks (Frito is the bigger profit driver).",
     "Same dynamics as KO plus snack-food sodium / sugar / calorie regulation."),
    ("NKE", "Nike", "NYSE", "large", "Athletic apparel",
     "Athletic apparel and footwear, ~30% revenue from Greater China.",
     "China tariffs and consumer sentiment, Xinjiang forced-labour rules."),
    ("DIS", "Walt Disney", "NYSE", "large", "Media / theme parks",
     "Movie studios (Marvel, Lucasfilm, Pixar, 20th Century), streaming (Disney+, Hulu, ESPN+), theme parks, ESPN. Under activist-investor pressure to break up.",
     "Florida regulatory tensions (special district), streaming-content quotas (EU), antitrust on Hulu / ESPN deals."),
    ("PG", "Procter & Gamble", "NYSE", "mega", "Consumer staples"),
    ("CL", "Colgate-Palmolive", "NYSE", "large", "Consumer staples"),
    ("KMB", "Kimberly-Clark", "NYSE", "large", "Consumer staples"),
    # ---- energy ----
    ("XOM", "ExxonMobil", "NYSE", "mega", "Integrated oil & gas",
     "Largest US oil major — integrated production, refining, chemicals. Permian-heavy, low-cost producer post the Pioneer acquisition.",
     "Methane fees (IRA), drilling permits, EPA emissions rules, FTC review of the Pioneer deal."),
    ("CVX", "Chevron", "NYSE", "large", "Integrated oil & gas",
     "Second-largest US oil major. Mid-stream the Hess acquisition (Exxon arbitration risk on Guyana).",
     "Same as XOM minus the Pioneer-specific."),
    ("COP", "ConocoPhillips", "NYSE", "large", "E&P oil & gas",
     "Pure-play E&P; Permian focus plus the Alaska Willow project.",
     "Willow drilling permits, methane regulation."),
    ("EOG", "EOG Resources", "NYSE", "large", "E&P oil & gas"),
    ("SLB", "Schlumberger", "NYSE", "large", "Oilfield services"),
    ("OXY", "Occidental Petroleum", "NYSE", "large", "E&P oil & gas",
     "Permian + Buffett-backed; large carbon-capture push via 1PointFive.",
     "45Q carbon-capture tax credit, methane rule, Anadarko legacy."),
    # ---- telecom ----
    ("VZ", "Verizon Communications", "NYSE", "large", "Telecom",
     "US wireless carrier (one of three) plus FirstNet (dedicated public-safety LTE).",
     "FCC spectrum auctions, net-neutrality rules, FirstNet contracts."),
    ("TMUS", "T-Mobile US", "NASDAQ", "large", "Telecom",
     "US wireless carrier, having absorbed Sprint. Most aggressive 5G build-out.",
     "FCC spectrum auctions, antitrust review of fibre acquisitions."),
    # ---- real estate / REITs ----
    ("AMT", "American Tower", "NYSE", "large", "Cell tower REIT",
     "Cell-tower landlord. Customers are wireless carriers paying long-term lease rents.",
     "Wireless infrastructure rules, 5G / 6G policy, FAA tower-approval policy."),
    ("CCI", "Crown Castle", "NYSE", "large", "Cell tower REIT",
     "Cell-tower landlord; activist-pushed sale of the fibre arm in progress.",
     "Same dynamics as AMT."),
    ("EQIX", "Equinix", "NASDAQ", "large", "Data centre REIT",
     "Global data-centre operator; primary beneficiary of the AI build-out alongside DLR.",
     "AI compute demand, energy / power-grid regulation, local zoning approvals."),
    ("PLD", "Prologis", "NYSE", "large", "Industrial REIT"),
    ("O", "Realty Income", "NYSE", "large", "Net-lease REIT"),
    # ---- transport / travel ----
    ("DAL", "Delta Air Lines", "NYSE", "large", "Airlines"),
    ("UAL", "United Airlines", "NASDAQ", "large", "Airlines"),
    ("AAL", "American Airlines", "NASDAQ", "mid", "Airlines"),
    ("LUV", "Southwest Airlines", "NYSE", "mid", "Airlines"),
    ("ABNB", "Airbnb", "NASDAQ", "large", "Short-term rentals",
     "Short-term-rental marketplace; subject to wildly variable city-level regulation.",
     "Municipal STR bans (NYC, Barcelona, Amsterdam), hotel-tax compliance."),
    ("BKNG", "Booking Holdings", "NASDAQ", "large", "Online travel"),
    ("UBER", "Uber Technologies", "NYSE", "large", "Ride-share / delivery",
     "Ride-share, delivery (Uber Eats), and freight.",
     "Classification of gig workers (California Prop 22, US Labor Department rules), city-level ride-share regulation."),
    # ---- misc widely-traded ----
    ("STT", "State Street", "NYSE", "large", "Custody bank",
     "Custody bank — holds ~$40T of institutional assets. Plus SPDR ETFs.",
     "Same passive-investing controversies as BLK."),
    ("F", "Ford Motor", "NYSE", "large", "Auto manufacturer",
     "Legacy US automaker; F-150 is the highest-volume vehicle in America. Ongoing EV transition and Ford Pro commercial business.",
     "EV subsidy / tariff policy, CAFE standards, UAW contracts."),
    ("ANET", "Arista Networks", "NYSE", "large", "Networking hardware (cloud)",
     "Networking hardware optimised for hyperscale data centres. Meta and Microsoft are the largest customers.",
     "AI build-out demand; CHIPS Act-adjacent; less direct policy than NVDA but rides the same wave."),
    ("LULU", "Lululemon Athletica", "NASDAQ", "large", "Athletic apparel",
     "Premium athletic apparel. Hot brand for a decade, US growth has cooled; China is the next leg.",
     "China tariffs and consumer sentiment, anti-counterfeiting."),
    ("PTC", "PTC Inc", "NASDAQ", "mid", "Industrial software / CAD",
     "Industrial software — CAD (Creo), product-lifecycle management (Windchill), IoT for factories (ThingWorx).",
     "CHIPS Act and reshoring policy boost industrial-software demand; ITAR compliance for defence customers."),
    ("WDAY", "Workday", "NASDAQ", "large", "HR / finance SaaS"),
    ("DDOG", "Datadog", "NASDAQ", "large", "Observability SaaS"),
    ("MDB", "MongoDB", "NASDAQ", "large", "Database software"),
    ("ZS", "Zscaler", "NASDAQ", "large", "Cloud security"),
    ("OKTA", "Okta", "NASDAQ", "large", "Identity SaaS"),
    ("TEAM", "Atlassian", "NASDAQ", "large", "Developer SaaS"),
    ("SHOP", "Shopify", "NYSE", "large", "E-commerce platform"),
    ("PYPL", "PayPal Holdings", "NASDAQ", "large", "Digital payments"),
    ("SQ", "Block (Square)", "NYSE", "large", "Payments / Bitcoin"),
    ("ROKU", "Roku", "NASDAQ", "mid", "Streaming hardware / ads"),
    ("SPOT", "Spotify Technology", "NYSE", "large", "Music streaming"),
    ("BABA", "Alibaba", "NYSE", "large", "China e-commerce"),
    ("PDD", "PDD Holdings (Temu)", "NASDAQ", "large", "China e-commerce"),
    ("TSM", "Taiwan Semiconductor", "NYSE", "mega", "Foundry semiconductors",
     "World's largest semiconductor foundry — fabricates chips designed by NVDA, AAPL, AMD, QCOM and most others. Critical chokepoint of global supply chain.",
     "China-Taiwan geopolitics is the dominant tail-risk; CHIPS Act subsidies for new fabs in Arizona, Japan and Germany."),
    # ---- additions covering names that have surfaced in real candidates ----
    ("KR", "Kroger", "NYSE", "large", "Retail / grocery",
     "One of the two largest US grocery chains — runs Kroger, Fred Meyer, King Soopers, Ralphs, Harris Teeter. The Albertsons merger was blocked by the FTC in 2024.",
     "Grocery antitrust, food-inflation politics, SNAP benefits policy."),
    ("WAT", "Waters Corporation", "NYSE", "large", "Lab equipment",
     "Maker of liquid chromatography (LC), mass spectrometry (MS) and thermal-analysis instruments for life-sciences and industrial labs.",
     "NIH / pharma R&D budgets and FDA bioanalytical-method requirements drive demand."),
    ("CHRW", "C.H. Robinson Worldwide", "NASDAQ", "mid", "Logistics / freight broker",
     "Largest non-asset-based logistics broker in North America — truckload, LTL, intermodal.",
     "Trucking-cycle volumes and classification of independent contractors (AB5 / federal labour rules)."),
    ("NDAQ", "Nasdaq Inc", "NASDAQ", "large", "Exchange / market tech",
     "Operates the Nasdaq stock market plus a growing market-technology and anti-financial-crime SaaS business.",
     "SEC market-structure rules, payment-for-order-flow, SPAC regulation."),
    ("FULT", "Fulton Financial", "NASDAQ", "mid", "Regional bank",
     "Mid-Atlantic regional bank, mostly Pennsylvania-centred.",
     "Regional-bank dynamics — commercial real estate exposure, deposit competition, regulatory consent orders."),
    ("FTAI", "FTAI Aviation", "NASDAQ", "mid", "Aviation leasing",
     "Aircraft engine leasing and aerospace asset trading; CFM56 engine module-swap programme is the core franchise.",
     "Aviation maintenance cycle, FAA airworthiness directives, Strategic Capital Initiative for engine repair."),
    # ---- exchanges ----
    ("ICE", "Intercontinental Exchange", "NYSE", "large", "Exchange / market tech",
     "Owns NYSE plus a large derivatives-clearing and mortgage-services business.",
     "SEC and CFTC market-structure rules, mortgage-rate policy."),
    ("CME", "CME Group", "NASDAQ", "large", "Exchange / derivatives",
     "Largest US derivatives exchange — futures and options on rates, equities, FX, energy, agri.",
     "CFTC regulation, position-limit rules, interest-rate volatility."),
    # ---- insurance ----
    ("CB", "Chubb", "NYSE", "large", "P&C insurance"),
    ("TRV", "Travelers", "NYSE", "large", "P&C insurance"),
    ("ALL", "Allstate", "NYSE", "large", "P&C insurance"),
    ("MET", "MetLife", "NYSE", "large", "Life insurance"),
    ("PRU", "Prudential Financial", "NYSE", "large", "Life insurance"),
    ("AIG", "American International Group", "NYSE", "large", "P&C insurance"),
    ("MMC", "Marsh McLennan", "NYSE", "large", "Insurance brokerage / consulting"),
    ("AON", "Aon", "NYSE", "large", "Insurance brokerage / consulting"),
    # ---- off-price retail / dollar stores ----
    ("TJX", "TJX Companies", "NYSE", "large", "Off-price retail"),
    ("ROST", "Ross Stores", "NASDAQ", "large", "Off-price retail"),
    ("DG", "Dollar General", "NYSE", "large", "Discount retail"),
    ("DLTR", "Dollar Tree", "NASDAQ", "large", "Discount retail"),
    # ---- restaurants ----
    ("CMG", "Chipotle Mexican Grill", "NYSE", "large", "Quick-service restaurants"),
    ("QSR", "Restaurant Brands International", "NYSE", "large", "Quick-service restaurants"),
    ("DPZ", "Domino's Pizza", "NYSE", "large", "Quick-service restaurants"),
    ("DRI", "Darden Restaurants", "NYSE", "large", "Casual dining"),
    # ---- packaged food ----
    ("KHC", "Kraft Heinz", "NASDAQ", "large", "Packaged food"),
    ("MDLZ", "Mondelez International", "NASDAQ", "large", "Snacks / packaged food"),
    ("GIS", "General Mills", "NYSE", "large", "Packaged food"),
    # ---- defence small / mid ----
    ("TDG", "TransDigm Group", "NYSE", "large", "Aerospace components",
     "Niche aerospace components — bolts, ignitions, valves — sold into commercial and military OEM with monopoly pricing on legacy parts.",
     "Defence-budget mix, DoD sole-source-pricing scrutiny, aviation maintenance cycle."),
    ("HEI", "HEICO", "NYSE", "large", "Aerospace components",
     "FAA-Parts Manufacturer Approval (PMA) replacement-parts and military-electronics roll-up; the founder-family compounder story.",
     "FAA PMA approvals; defence-aerospace mix."),
    # ---- data centre / industrial REIT ----
    ("DLR", "Digital Realty Trust", "NYSE", "large", "Data centre REIT",
     "Global data-centre REIT; primary AI build-out beneficiary alongside EQIX.",
     "AI compute demand, power-grid regulation, local zoning."),
    ("VICI", "VICI Properties", "NYSE", "large", "Gaming / experiential REIT"),
    ("SPG", "Simon Property Group", "NYSE", "large", "Retail mall REIT"),
)

for _entry in _EXTRA:
    if len(_entry) == 5:
        _t, _n, _x, _c, _s = _entry
        _FACTS.setdefault(_t, TickerFact(
            ticker=_t, name=_n, exchange=_x, cap=_c, sector=_s,
        ))
    elif len(_entry) == 7:
        _t, _n, _x, _c, _s, _summary, _why = _entry
        _FACTS.setdefault(_t, TickerFact(
            ticker=_t, name=_n, exchange=_x, cap=_c, sector=_s,
            summary=_summary, why_it_matters=_why,
        ))


# Map fine-grained sector strings (~80 unique values across the facts table)
# down to ~15 top-level buckets that work as a multiselect filter on the
# dashboard.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Defence",            ("defence",)),
    ("Aerospace / defence", ("aerospace",)),
    ("Semiconductors",     ("semiconductor", "foundry")),
    ("Tech / software",    ("software", "saas", "data cloud", "enterprise it",
                            "cybersecurity", "e-commerce platform", "music streaming")),
    ("Tech / hardware",    ("tech hardware", "networking", "pcs", "evs", "streaming hardware")),
    ("Internet / media",   ("advertising", "social media", "streaming media", "media / theme",
                            "online travel", "short-term rentals", "ride-share")),
    ("Pharma",             ("pharma",)),
    ("Biotech",            ("biotech",)),
    ("Medical devices",    ("medical device", "surgical", "lab equipment",
                            "life sciences / diagnostics", "animal health",
                            "public-safety tech")),
    ("Health insurance",   ("health insurance", "pharmacy / insurance")),
    ("Financials",         ("bank", "brokerage", "payment", "asset manager",
                            "alternative asset", "payroll", "crypto")),
    ("Industrial",         ("industrial", "construction equipment", "agricultural equipment",
                            "rail freight", "power management", "aerospace engines")),
    ("Logistics & transport", ("logistics", "airlines", "e-commerce / cloud")),
    ("Consumer",           ("retail", "restaurants", "coffee", "beverages",
                            "athletic apparel", "consumer staples", "auto manufacturer")),
    ("Energy",             ("oil", "oilfield", "integrated oil")),
    ("Utilities",          ("utility", "regulated utility")),
    ("Telecom",            ("telecom",)),
    ("Real estate",        ("reit",)),
)


def top_level_category(sector: str | None) -> str:
    """Return a top-level grouping label suitable for a multiselect filter."""
    if not isinstance(sector, str) or not sector:
        return "Other"
    s = sector.lower()
    for label, needles in _CATEGORY_RULES:
        if any(n in s for n in needles):
            return label
    return "Other"


# ---------------------------------------------------------------------------
# Lazy yfinance fallback + on-disk cache
# ---------------------------------------------------------------------------

_CACHE_PATH = Path("data/cache/ticker_facts_cache.json")
_RUNTIME_CACHE: dict[str, TickerFact | None] = {}
_DISK_CACHE_LOADED = False

# yfinance returns Yahoo's internal exchange codes; map them to common names.
_EXCHANGE_MAP: dict[str, str] = {
    "NMS": "NASDAQ", "NCM": "NASDAQ", "NGS": "NASDAQ",
    "NAS": "NASDAQ", "NGM": "NASDAQ", "NSI": "NASDAQ",
    "NYQ": "NYSE", "NYE": "NYSE",
    "ASE": "AMEX", "PCX": "NYSE Arca",
    "PNK": "OTC", "OEM": "OTC", "OTC": "OTC",
    "BATS": "BATS", "CBT": "CBOE",
}


def _cap_bucket(market_cap: float | int | None) -> str:
    """Map a market-cap value to a size bucket compatible with `_FACTS`."""
    if not market_cap:
        return "unknown"
    try:
        cap = float(market_cap)
    except (TypeError, ValueError):
        return "unknown"
    if cap >= 200_000_000_000:
        return "mega"
    if cap >= 10_000_000_000:
        return "large"
    if cap >= 2_000_000_000:
        return "mid"
    if cap >= 300_000_000:
        return "small"
    return "micro"


def _load_disk_cache_once() -> None:
    """Load `_CACHE_PATH` into `_RUNTIME_CACHE` exactly once per process."""
    global _DISK_CACHE_LOADED
    if _DISK_CACHE_LOADED:
        return
    _DISK_CACHE_LOADED = True
    if not _CACHE_PATH.exists():
        return
    try:
        with _CACHE_PATH.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Could not read ticker_facts cache (%s)", exc)
        return
    for ticker, entry in payload.items():
        if entry is None:
            _RUNTIME_CACHE[ticker] = None
        else:
            try:
                _RUNTIME_CACHE[ticker] = TickerFact(**entry)
            except TypeError:
                # Schema drift: drop the cached entry rather than crash.
                continue


def _persist_runtime_to_disk() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {}
        for t, fact in _RUNTIME_CACHE.items():
            payload[t] = None if fact is None else {
                "ticker": fact.ticker, "name": fact.name,
                "exchange": fact.exchange, "cap": fact.cap,
                "sector": fact.sector, "summary": fact.summary,
                "why_it_matters": fact.why_it_matters,
            }
        tmp = _CACHE_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        tmp.replace(_CACHE_PATH)
    except Exception as exc:  # noqa: BLE001
        _log.debug("Could not persist ticker_facts cache (%s)", exc)


def _fetch_from_yfinance(ticker: str) -> TickerFact | None:
    """Fetch company metadata for `ticker` via yfinance. Returns None on
    any failure (rate-limit, delisted, missing fields). Always graceful."""
    try:
        import yfinance as yf  # local import: yfinance is optional at runtime
    except Exception as exc:  # noqa: BLE001
        _log.debug("yfinance not available (%s)", exc)
        return None
    try:
        info = yf.Ticker(ticker).get_info()
    except Exception as exc:  # noqa: BLE001
        _log.debug("yfinance get_info(%s) failed: %s", ticker, exc)
        return None
    if not info:
        return None
    name = info.get("longName") or info.get("shortName")
    if not name:
        return None
    raw_exchange = info.get("exchange") or info.get("fullExchangeName") or ""
    exchange = _EXCHANGE_MAP.get(raw_exchange.upper() if isinstance(raw_exchange, str) else "", raw_exchange or "?")
    cap = _cap_bucket(info.get("marketCap"))
    sector = info.get("industry") or info.get("sector") or "Other"
    return TickerFact(
        ticker=ticker.upper(),
        name=str(name),
        exchange=str(exchange),
        cap=cap,
        sector=str(sector),
    )


def lookup(ticker: str) -> TickerFact | None:
    """Tiered ticker-fact lookup.

    1. Curated static `_FACTS` dict (richest, no I/O).
    2. Disk-cached results from previous yfinance fetches.
    3. Live yfinance fetch (slow on first call per ticker; cached afterwards).

    Returns None when yfinance can't find the ticker either.
    """
    upper = (ticker or "").upper()
    if not upper:
        return None
    if upper in _FACTS:
        return _FACTS[upper]
    _load_disk_cache_once()
    if upper in _RUNTIME_CACHE:
        return _RUNTIME_CACHE[upper]
    fact = _fetch_from_yfinance(upper)
    _RUNTIME_CACHE[upper] = fact
    _persist_runtime_to_disk()
    return fact


def prewarm(tickers: list[str], max_workers: int = 4) -> int:
    """Pre-fetch yfinance info for any unknown tickers in `tickers`. Returns
    the number that were freshly fetched. Call once in the bootstrap so the
    dashboard never blocks on a per-ticker yfinance call."""
    _load_disk_cache_once()
    unknown: list[str] = []
    seen: set[str] = set()
    for t in tickers:
        upper = (t or "").upper()
        if not upper or upper in seen:
            continue
        seen.add(upper)
        if upper in _FACTS or upper in _RUNTIME_CACHE:
            continue
        unknown.append(upper)
    if not unknown:
        return 0
    _log.info(
        "Prewarming yfinance ticker_facts for %d unknown tickers", len(unknown),
    )

    def _fetch_one(t: str) -> None:
        try:
            _RUNTIME_CACHE[t] = _fetch_from_yfinance(t)
        except Exception as exc:  # noqa: BLE001
            _log.debug("prewarm fetch failed for %s: %s", t, exc)
            _RUNTIME_CACHE[t] = None

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_fetch_one, unknown))
    _persist_runtime_to_disk()
    return len(unknown)


def category_for_ticker(ticker: str) -> str:
    f = lookup(ticker)
    return top_level_category(f.sector) if f else "Other"


def known_tickers() -> set[str]:
    return set(_FACTS.keys())


def all_facts() -> list[TickerFact]:
    return list(_FACTS.values())
