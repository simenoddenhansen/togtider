"""
utils.py
────────
Re-export hub for Togforsinkelser-appen.

Denne filen importerer og re-eksporterer alle delte funksjoner og konstanter
fra de nye modulene (data_loader, components), slik at eksisterende
`from utils import ...`-setninger forblir gyldige.

Ny kode bør importere direkte fra data_loader eller components/.
"""

import os
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st

# ─── Re-eksporter fra data_loader ─────────────────────────────────

from data_loader import (
    OSLO_TZ,
    project_root,
    master_csv_path,
    stations_csv_path,
    get_mtime,
    load_delay_data,
    load_stations,
    filter_rail_only,
    get_unique_routes,
    get_route_traffic_counts,
)

# ─── Re-eksporter fra components ──────────────────────────────────

from components.kpi import styled_kpi
from components.footer import entur_footer
from components.sidebar import render_sidebar_filters, apply_time_filter

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
    except Exception:
        return None


# ─── Farge- og karthjelp ─────────────────────────────────────────

def delay_to_color(delay_sec, max_delay_val):
    """Konverterer forsinkelse i sekunder til [R, G, B, A] (grønn → gul → rød)."""
    if max_delay_val <= 0:
        return [44, 200, 50, 200]
    ratio = min(max(delay_sec / max_delay_val, 0.0), 1.0)
    if ratio < 0.5:
        r = int(255 * (ratio * 2))
        g = 200
        b = 50
    else:
        r = 255
        g = int(200 * (1 - (ratio - 0.5) * 2))
        b = 50
    return [r, g, b, 200]


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


# ─── Nedlasting ──────────────────────────────────────────────────

def download_csv_button(df, prefix="togforsinkelser"):
    """Rendrer en nedlastingsknapp for gitt DataFrame."""
    if df.empty:
        return
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    now_str = datetime.now(OSLO_TZ).strftime("%Y%m%d_%H%M")
    st.download_button(
        label="📥 Last ned filtrerte data (CSV)",
        data=csv_bytes,
        file_name=f"{prefix}_{now_str}.csv",
        mime="text/csv",
    )


# ─── Plotly-hjelpere ─────────────────────────────────────────────

PLOTLY_TEMPLATE = "plotly_dark"

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
