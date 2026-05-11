"""
utils.py
────────
Delte hjelpefunksjoner og konstanter for visualisering, Entur API-kall og
kolonnenavn. Dataregisteret ligger i data_loader.py og UI-byggesteiner i
components/.
"""

import requests
import streamlit as st


# ─── Entur API-konfigurasjon ──────────────────────────────────────

API_URL = "https://api.entur.io/journey-planner/v3/graphql"
API_HEADERS = {
    "ET-Client-Name": "simenoddenhansen-togtider_dev",
    "Content-Type": "application/json",
}


# ─── Entur API ────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def fetch_route_geometry(line_id):
    """Henter stoppested-koordinater for en linje fra Entur API."""
    query = """
    query ($lineId: ID!) {
      line(id: $lineId) {
        id
        name
        transportMode
        journeyPatterns {
          quays {
            id
            name
            latitude
            longitude
          }
        }
      }
    }
    """
    try:
        r = requests.post(
            API_URL,
            json={"query": query, "variables": {"lineId": line_id}},
            headers=API_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        line = data.get("data", {}).get("line")
        if not line:
            return None

        best_pattern = None
        best_count = 0
        for jp in line.get("journeyPatterns", []):
            quays = jp.get("quays", [])
            valid = [q for q in quays if q.get("latitude") and q.get("longitude")]
            if len(valid) > best_count:
                best_count = len(valid)
                best_pattern = valid

        if not best_pattern or best_count < 2:
            return None

        return {
            "name": line.get("name", ""),
            "mode": line.get("transportMode", ""),
            "stops": best_pattern,
        }
    except requests.RequestException:
        return None


# ─── Farge- og karthjelp ─────────────────────────────────────────

# Absolutte grenser (i sekunder) for fargekoding av snittforsinkelse per
# stasjon på kartet. Disse er faste — uavhengig av valgt tidsperiode.
MAP_DELAY_GREEN_MAX_SEC = 120    # under 2 min      → grønn
MAP_DELAY_YELLOW_MAX_SEC = 300   # 2–5 min          → gul
                                 # 5 min eller mer  → rød

# RGBA-farger som matcher diagrammenes grønn/gul/rød (#2ecc71/#f1c40f/#e74c3c).
_MAP_COLOR_GREEN = [46, 204, 113, 200]
_MAP_COLOR_YELLOW = [241, 196, 15, 200]
_MAP_COLOR_RED = [231, 76, 60, 200]

# Forklaringstekst til kartets fargekode (brukes flere steder).
MAP_DELAY_LEGEND = (
    "🟢 Grønn = liten forsinkelse (under 2 min) · "
    "🟡 Gul = moderat (2–5 min) · "
    "🔴 Rød = stor forsinkelse (5 min eller mer)"
)


def delay_to_color(delay_sec):
    """Fargekode [R, G, B, A] for snittforsinkelse, med absolutte grenser.

    Grønn < 2 min · Gul 2–5 min · Rød ≥ 5 min.
    """
    try:
        sec = float(delay_sec)
    except (TypeError, ValueError):
        sec = 0.0
    if sec < MAP_DELAY_GREEN_MAX_SEC:
        return list(_MAP_COLOR_GREEN)
    if sec < MAP_DELAY_YELLOW_MAX_SEC:
        return list(_MAP_COLOR_YELLOW)
    return list(_MAP_COLOR_RED)


def compute_zoom(lat_spread, lng_spread):
    """Estimerer pydeck zoom-nivå basert på geografisk spredning."""
    spread = max(lat_spread, lng_spread)
    if spread > 10:
        return 4
    elif spread > 5:
        return 5
    elif spread > 2:
        return 6
    elif spread > 1:
        return 7
    elif spread > 0.5:
        return 8
    elif spread > 0.1:
        return 10
    else:
        return 12


# ─── Kolonnevisning ──────────────────────────────────────────────

DISPLAY_COLUMNS = [
    "stationName", "destination", "lineName", "lineCode",
    "transportMode", "scheduledDeparture", "delaySeconds", "isDelayed",
    "delaySource",
]

COLUMN_LABELS = {
    "stationName": "Stasjon",
    "destination": "Destinasjon",
    "lineName": "Linje",
    "lineCode": "Kode",
    "transportMode": "Type",
    "scheduledDeparture": "Planlagt avgang",
    "delaySeconds": "Forsinkelse (s)",
    "isDelayed": "Forsinket",
    "delaySource": "Datakilde",
    "realtime": "Sanntid",
}


# ─── Plotly-hjelpere ─────────────────────────────────────────────

PLOTLY_TEMPLATE = "plotly_dark"
# Hover (tooltips) er på, men brukeren kan ikke endre visningen:
# ingen verktøylinje, ingen zoom/pan/dobbeltklikk. Husk dragmode=False
# i layout på hver figur for å låse dra-zoom i selve plottet.
PLOTLY_STATIC_CONFIG = {
    "displayModeBar": False,
    "staticPlot": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showAxisDragHandles": False,
    "showAxisRangeEntryBoxes": False,
    "responsive": True,
}

# Grønn → gul → rød fargeskala for forsinkelsesdiagrammer
DELAY_COLOR_SCALE = [
    [0.0, "#2ecc71"],   # Grønn — i rute
    [0.3, "#f1c40f"],   # Gul — mindre forsinkelse
    [0.6, "#e67e22"],   # Oransje — moderat
    [1.0, "#e74c3c"],   # Rød — alvorlig
]

# Aksentfarge for primærdiagrammer (matcher tema-primaryColor)
ACCENT_COLOR = "#4fc3f7"

# Norske ukedagsnavn i riktig rekkefølge (mandag først)
WEEKDAY_NAMES = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]

# Fargeblindevennlig fargeskala for heatmap
HEATMAP_COLOR_SCALE = "Viridis"
