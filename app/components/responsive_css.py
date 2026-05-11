"""
responsive_css.py — Delt responsiv CSS for alle sider.
─────────────────────────────────────────────────────────
Injiserer CSS media queries for mobil, nettbrett og desktop.
Kall inject_responsive_css() øverst på hver side etter set_page_config().
"""

import streamlit as st


def inject_responsive_css():
    """Injiserer responsiv CSS som fungerer på alle skjermstørrelser."""
    st.markdown("""
<style>
/* ══════════════════════════════════════════════════════════
   Responsiv CSS for Togforsinkelser-appen
   ══════════════════════════════════════════════════════════ */

/* Skjul Streamlits venstremeny / auto-sidenavigasjon helt — appen bruker egen
   toppnav. Den primære avskruingen skjer i .streamlit/config.toml
   (client.showSidebarNavigation = false); dette er en ekstra sikring i tilfelle
   navigasjonen eller «åpne sidemeny»-pilen likevel dukker opp. Flere
   data-testid-er listes fordi navnene varierer mellom Streamlit-versjoner. */
[data-testid="stSidebar"],
[data-testid="stSidebarNav"],
[data-testid="stSidebarNavItems"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"] {
    display: none !important;
}

.block-container {
    padding-top: 1.2rem !important;
}

.top-nav-shell {
    border-bottom: 1px solid rgba(255, 255, 255, 0.14);
    margin: -0.4rem 0 1.4rem 0;
    padding: 0 0 0.8rem 0;
}

.top-nav-brand {
    align-items: center;
    color: #f8fafc;
    display: flex;
    font-size: 1.05rem;
    font-weight: 800;
    min-height: 2.5rem;
}

.top-nav-active {
    color: rgba(248, 250, 252, 0.52);
    font-size: 0.78rem;
    margin-top: 0.2rem;
}

div[data-testid="stPageLink"] a {
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 8px;
    min-height: 2.5rem;
}

.filter-bar {
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    margin: 0.8rem 0 1.2rem 0;
    padding: 0.85rem 0.95rem 0.2rem 0.95rem;
}

.filter-bar-title {
    color: rgba(248, 250, 252, 0.68);
    font-size: 0.86rem;
    font-weight: 700;
    margin-bottom: 0.35rem;
    text-transform: uppercase;
}

/* ── Mobiloptimering (< 768px) ─────────────────────────── */
@media (max-width: 768px) {
    /* Reduser padding på sidene for å utnytte plassen */
    .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* KPI-kort: lesbare tall og etiketter på smal skjerm */
    [data-testid="stMetric"] {
        overflow-wrap: break-word;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.3rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }

    /* Plotly-grafer: sørg for at de ikke overflower */
    .js-plotly-plot, .plotly {
        max-width: 100% !important;
        overflow-x: auto !important;
    }

    /* Datatabeller: horisontal scroll i stedet for overflow */
    [data-testid="stDataFrame"] {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }

    /* Tittel og overskrifter: tilpasset mobilskjerm */
    h1 {
        font-size: 1.6rem !important;
        line-height: 1.3 !important;
    }
    h2 {
        font-size: 1.2rem !important;
    }
    h3 {
        font-size: 1.05rem !important;
    }

    /* Info/warning-bokser: litt kompaktere */
    [data-testid="stAlert"] {
        font-size: 0.85rem !important;
        padding: 0.5rem 0.75rem !important;
    }

    /* Download-knapp: full bredde på mobil */
    .stDownloadButton > button {
        width: 100% !important;
    }

    .top-nav-brand {
        font-size: 0.95rem;
    }
}

/* ── Nettbrett (768px – 1024px) ────────────────────────── */
@media (min-width: 769px) and (max-width: 1024px) {
    .block-container {
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
    }
}

/* ── Generelt: sørg for at alt passer innenfor bredden ── */
.stPlotlyChart {
    max-width: 100%;
    overflow-x: auto;
}

/* PyDeck-kart: responsiv container */
[data-testid="stDeckGlWidget"] {
    max-width: 100%;
}
</style>
""", unsafe_allow_html=True)
