"""Mobile / PWA polish for the Streamlit dashboard.

Streamlit's served HTML head is fixed, but we can:
- Set the favicon (which iOS uses as the home-screen icon) via
  `st.set_page_config(page_icon=...)`.
- Inject Apple-specific meta tags into <head> at runtime via a hidden
  components.iframe that runs a small JavaScript snippet on the parent
  window (Streamlit's iframe → window.parent.document).
- Apply custom CSS for better mobile readability (sticky tabs, larger tap
  targets, smaller side padding, smaller table fonts so columns fit).

After "Add to Home Screen" on iOS, the apple-mobile-web-app-* meta tags
make the launched instance look like a native app (no Safari chrome, custom
status-bar style, custom app title).
"""

from __future__ import annotations

APP_TITLE = "Icarus"
APP_ICON_EMOJI = "🪶"


# We use the favicon Streamlit hosts at /favicon.ico as the apple-touch-icon
# (so iOS pulls it automatically when "Add to Home Screen" is selected).
_PWA_HEAD_INJECTION = """
<script>
(function() {
  const parentDoc = window.parent && window.parent.document;
  if (!parentDoc) { return; }

  // Reload FAB: appended to <body> with inline styles, outside Streamlit's
  // layout, so no container overflow/transform can swallow it. Survives
  // reruns via the id guard.
  if (!parentDoc.getElementById('icarus-refresh-fab')) {
    const b = parentDoc.createElement('button');
    b.id = 'icarus-refresh-fab';
    b.textContent = '\u21bb';
    b.setAttribute('aria-label', 'Reload the app');
    b.style.cssText = [
      'position:fixed', 'bottom:20px', 'left:16px',
      'z-index:2147483647', 'width:46px', 'height:46px',
      'border-radius:50%', 'background:#181b19',
      'border:1px solid rgba(242,241,236,0.25)', 'color:#eda100',
      'font-size:22px', 'line-height:1', 'cursor:pointer',
      'box-shadow:0 4px 16px rgba(0,0,0,0.5)',
      'display:flex', 'align-items:center', 'justify-content:center',
    ].join(';');
    b.onclick = function () {
      parentDoc.location.href = parentDoc.location.pathname;
    };
    parentDoc.body.appendChild(b);
  }

  if (parentDoc.head.querySelector('meta[name="apple-mobile-web-app-title"]')) {
    return;
  }
  const meta = (name, content) => {
    const m = parentDoc.createElement('meta');
    m.setAttribute('name', name);
    m.setAttribute('content', content);
    parentDoc.head.appendChild(m);
  };
  meta('apple-mobile-web-app-capable', 'yes');
  meta('apple-mobile-web-app-title', 'Icarus');
  meta('apple-mobile-web-app-status-bar-style', 'black-translucent');
  meta('mobile-web-app-capable', 'yes');
  meta('theme-color', '#101312');
})();
</script>
"""

# Icarus design language.
#
# Direction: editorial and restrained — warm ink surfaces, one gold accent
# (the sun; Icarus flew at it), Fraunces for display type, Inter for data,
# tabular numerals everywhere a number appears. Status colours (buy green /
# sell red) are semantic only and always ship with a label, never colour
# alone. Colours validated against the dark surface with the dataviz
# palette validator (contrast >= 3:1).
_DESIGN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,530;9..144,640&family=Inter:wght@400;500;600&display=swap');

:root {
  --ink-bg: #101312;         /* app background */
  --ink-surface: #181b19;    /* cards, inputs */
  --ink-border: rgba(242,241,236,0.10);
  --ink-border-strong: rgba(242,241,236,0.18);
  --text-1: #f2f1ec;         /* primary ink */
  --text-2: #b9b8ae;         /* secondary */
  --text-3: #8a897f;         /* muted / captions */
  --gold: #eda100;           /* the accent — used sparingly */
  --gold-deep: #c98500;
  --pos: #1baf7a;            /* semantic only, never decoration */
  --neg: #e66767;
}

/* ---- Typography -------------------------------------------------------- */
html, body, [class*="st-"] {
  font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
  -webkit-font-smoothing: antialiased;
}
/* Streamlit renders its chevrons/icons as Material Symbols ligatures; the
   Inter override above must NOT catch them or the ligature text renders
   literally ("keyboard_arrow_right" over the expander label). */
[data-testid="stIconMaterial"],
[class*="material-symbols"],
span[data-testid="stExpanderToggleIcon"] {
  font-family: 'Material Symbols Rounded' !important;
}
/* T212-style: clean sans throughout; the serif lives ONLY on the app
   title, as a brand accent. */
h1 {
  font-family: 'Fraunces', Georgia, serif !important;
  font-weight: 530 !important;
  letter-spacing: 0.01em;
  font-size: 2.0rem !important;
  color: var(--text-1) !important;
}
h2, h3, h4 {
  font-family: 'Inter', -apple-system, sans-serif !important;
  font-weight: 600 !important;
  letter-spacing: -0.01em;
  color: var(--text-1) !important;
}
h2 { font-size: 1.35rem !important; }
h3 { font-size: 1.1rem !important; margin-top: 0.75rem !important; }

/* Numbers line up in columns everywhere they appear. */
[data-testid="stMetricValue"], [data-testid="stDataFrame"],
[data-testid="stTable"], code {
  font-variant-numeric: tabular-nums;
}

/* Captions: quiet, slightly spaced, never shouting. */
[data-testid="stCaptionContainer"] {
  color: var(--text-3) !important;
  line-height: 1.5;
}

/* ---- Cards (st.container(border=True)) --------------------------------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
  border: 1px solid var(--ink-border) !important;
  border-radius: 14px !important;
  background: var(--ink-surface);
  padding: 0.35rem 0.5rem;
  transition: border-color 120ms ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
  border-color: var(--ink-border-strong) !important;
}

/* ---- Metric tiles ------------------------------------------------------ */
div[data-testid="stMetric"] {
  background: var(--ink-surface);
  border: 1px solid var(--ink-border);
  border-radius: 12px;
  padding: 0.65rem 0.85rem;
}
div[data-testid="stMetric"] label p {
  font-size: 0.72rem !important;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-3) !important;
  font-weight: 600 !important;
}
div[data-testid="stMetricValue"] {
  font-weight: 600;
  color: var(--text-1);
}

/* ---- Tabs: quiet pills, gold for the active one ------------------------ */
div[data-baseweb="tab-list"] {
  gap: 0.25rem;
  padding: 0.35rem 0;
}
button[data-baseweb="tab"] {
  border-radius: 999px !important;
  padding: 0.35rem 0.95rem !important;
  background: transparent !important;
  color: var(--text-2) !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  background: var(--ink-surface) !important;
  color: var(--gold) !important;
  border: 1px solid var(--ink-border-strong) !important;
}
div[data-baseweb="tab-highlight"] { display: none; }
div[data-baseweb="tab-border"] { background: var(--ink-border) !important; }

/* ---- Inputs & buttons -------------------------------------------------- */
.stButton button, .stDownloadButton button {
  border-radius: 10px !important;
  border: 1px solid var(--ink-border-strong) !important;
  font-weight: 500 !important;
}
.stButton button:hover {
  border-color: var(--gold-deep) !important;
  color: var(--gold) !important;
}
[data-testid="stTextInput"] input, [data-baseweb="select"] > div {
  border-radius: 10px !important;
}

/* ---- Expanders & dividers ---------------------------------------------- */
div[data-testid="stExpander"] {
  border: 1px solid var(--ink-border) !important;
  border-radius: 12px !important;
}
div[data-testid="stExpander"] summary {
  color: var(--text-2) !important;
  font-weight: 500;
}
hr {
  border-color: var(--ink-border) !important;
  margin: 1.1rem 0 !important;
}

/* ---- Dataframes -------------------------------------------------------- */
div[data-testid="stDataFrame"] {
  border: 1px solid var(--ink-border);
  border-radius: 12px;
  overflow: hidden;
}

/* ---- Alerts: keep them quiet, tint only the edge ----------------------- */
div[data-testid="stAlert"] {
  border-radius: 12px;
  border-left: 3px solid var(--gold-deep);
}

/* Hide Streamlit's footer chrome; keep the header (Manage app lives there). */
footer { visibility: hidden; }
</style>
"""

# Tightens padding on phones and improves tab readability.
_MOBILE_CSS = """
<style>
/* Reduce side padding on phones so tables/cards use the full viewport. */
@media (max-width: 640px) {
  section.main > div.block-container {
    padding-left: 0.5rem !important;
    padding-right: 0.5rem !important;
    padding-top: 0.75rem !important;
  }
  /* Slightly smaller body type so tables don't overflow horizontally. */
  html, body, [class*="st-"] {
    font-size: 13.5px !important;
  }
  h1 { font-size: 1.35rem !important; line-height: 1.25; }
  h2, h3 { font-size: 1.1rem !important; line-height: 1.3; }
  h4 { font-size: 1rem !important; }
  /* Tighter caption / paragraph spacing — phones reward density. */
  .stCaption, .stMarkdown p { margin-bottom: 0.4rem; }

  /* Streamlit st.columns() are flex rows by default and squish on phones.
     Force them to stack vertically below 640px so each filter / slider /
     metric gets the full screen width. */
  div[data-testid="stHorizontalBlock"] {
    flex-direction: column !important;
    gap: 0.5rem !important;
  }
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    width: 100% !important;
    flex: 1 1 100% !important;
    min-width: 0 !important;
  }

  /* Dataframes get a tiny font + tight padding so more columns fit before
     horizontal scrolling kicks in. */
  div[data-testid="stDataFrame"] {
    font-size: 12.5px !important;
  }
  div[data-testid="stDataFrame"] table {
    font-size: 12.5px !important;
  }

  /* Tighten metric cards: phone screens don't have room for the giant
     default font on metric values. */
  div[data-testid="stMetric"] label { font-size: 0.8rem !important; }
  div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    font-size: 1.4rem !important;
  }

  /* Native-looking sticky tabs with horizontal scroll for the 5-tab row. */
  div[data-baseweb="tab-list"] {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
  }
  div[data-baseweb="tab-list"] button { flex-shrink: 0; }

  /* Expander headers a bit chunkier — easier to tap. */
  div[data-testid="stExpander"] summary {
    padding: 0.55rem 0.5rem !important;
  }
}

/* Make tabs sticky at the top so they're reachable while scrolling. */
div[data-baseweb="tab-list"] {
  position: sticky;
  top: 0;
  z-index: 50;
  background: var(--ink-bg, #101312);
  border-bottom: 1px solid rgba(250,250,250,0.1);
}

/* Larger tap targets for buttons and selectboxes on touch screens. */
@media (pointer: coarse) {
  button, .stSelectbox, .stSlider, .stCheckbox { min-height: 44px; }
  /* Wider tap zone for checkboxes specifically (the box itself is tiny). */
  label[data-testid="stCheckbox"] { padding: 0.35rem 0; }
}

/* T212-style instrument rows: name | sparkline | price+chip, tappable */
.ilist { margin: 0.25rem 0 0.5rem 0; }
.irow {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 6px;
  border-bottom: 1px solid var(--ink-border);
  text-decoration: none !important;
  border-radius: 10px;
  transition: background 120ms ease;
}
.irow:hover { background: rgba(242,241,236,0.04); }
.irow-l { flex: 1 1 40%; min-width: 0; }
.irow-name {
  color: var(--text-1); font-weight: 600; font-size: 0.95rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.irow-sub {
  color: var(--text-3); font-size: 0.78rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.irow-spark { flex: 0 0 auto; line-height: 0; }
.irow-r { flex: 0 0 auto; text-align: right; }
.irow-px {
  color: var(--text-1); font-weight: 600; font-size: 0.95rem;
  font-variant-numeric: tabular-nums;
}
.irow .chip { font-size: 0.75rem; padding: 1px 8px; vertical-align: 0; }
.dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 6px; vertical-align: 1px;
}
.dot.buy { background: #2fcf96; }
.dot.appr { background: #eda100; }
.dot.hold { background: #8a897f; }
.dot.sell { background: #ef8585; }
.clear-sel {
  color: var(--text-3) !important; font-size: 0.85rem;
  text-decoration: none !important;
}
.clear-sel:hover { color: var(--gold) !important; }

/* Floating reload button — the PWA has no browser chrome, so this is
   the only always-visible way to refresh. Full navigation (not a
   Streamlit rerun) so it also revives stale sessions. */
.refresh-fab {
  position: fixed; bottom: 20px; left: 16px; z-index: 999;
  width: 46px; height: 46px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--ink-surface);
  border: 1px solid var(--ink-border-strong);
  color: var(--gold) !important;
  font-size: 21px; line-height: 1;
  text-decoration: none !important;
  box-shadow: 0 4px 16px rgba(0,0,0,0.45);
  transition: transform 120ms ease, border-color 120ms ease;
}
.refresh-fab:hover, .refresh-fab:active {
  border-color: var(--gold-deep);
  transform: rotate(45deg);
}

/* Price header + change chips (Trading212-style) */
.px-big {
  font-size: 1.7rem; font-weight: 600; color: var(--text-1);
  font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
}
.chip {
  display: inline-block; padding: 2px 10px; border-radius: 999px;
  font-size: 0.85rem; font-weight: 600; vertical-align: 3px;
  font-variant-numeric: tabular-nums;
}
.chip.up { background: rgba(27,175,122,0.16); color: #2fcf96; }
.chip.down { background: rgba(230,103,103,0.16); color: #ef8585; }

/* The detail card on mobile reads better as a vertical stack. */
.icarus-card { padding: 0.5rem 0; }
.icarus-card h4 { margin: 0 0 0.25rem 0; }
.icarus-card .meta { color: rgba(250,250,250,0.65); font-size: 0.85em; margin-bottom: 0.5rem; }
.icarus-card .narrative p { margin: 0.4rem 0; }
</style>
"""


def inject(st) -> None:
    """Inject PWA meta tags + design + mobile CSS. Call once at top of
    the dashboard. Design layer first so mobile rules can override it."""
    import streamlit.components.v1 as components
    st.markdown(_DESIGN_CSS, unsafe_allow_html=True)
    st.markdown(_MOBILE_CSS, unsafe_allow_html=True)
    components.html(_PWA_HEAD_INJECTION, height=0, width=0)
