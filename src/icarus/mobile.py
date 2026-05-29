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
  if (!parentDoc || parentDoc.head.querySelector('meta[name="apple-mobile-web-app-title"]')) {
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
  meta('theme-color', '#0ea5e9');
})();
</script>
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
  background: var(--background-color, #0e1117);
  border-bottom: 1px solid rgba(250,250,250,0.1);
}

/* Larger tap targets for buttons and selectboxes on touch screens. */
@media (pointer: coarse) {
  button, .stSelectbox, .stSlider, .stCheckbox { min-height: 44px; }
  /* Wider tap zone for checkboxes specifically (the box itself is tiny). */
  label[data-testid="stCheckbox"] { padding: 0.35rem 0; }
}

/* The detail card on mobile reads better as a vertical stack. */
.icarus-card { padding: 0.5rem 0; }
.icarus-card h4 { margin: 0 0 0.25rem 0; }
.icarus-card .meta { color: rgba(250,250,250,0.65); font-size: 0.85em; margin-bottom: 0.5rem; }
.icarus-card .narrative p { margin: 0.4rem 0; }
</style>
"""


def inject(st) -> None:
    """Inject PWA meta tags + mobile CSS. Call once at top of dashboard."""
    import streamlit.components.v1 as components
    st.markdown(_MOBILE_CSS, unsafe_allow_html=True)
    components.html(_PWA_HEAD_INJECTION, height=0, width=0)
