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

    /* Sidebar: litt strammere på mobil */
    section[data-testid="stSidebar"] > div {
        padding-top: 1rem !important;
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
