"""
utils.py
────────
Shared helpers for the Togforsinkelser Streamlit app.

Contains data-loading functions, Entur API helpers, color-scale
utilities, map helpers, transport configuration and the Entur
credit footer — all in one place so individual pages stay DRY.
"""

import os
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st

# ─── Constants ────────────────────────────────────────────────────

OSLO_TZ = pytz.timezone("Europe/Oslo")

API_URL = "https://api.entur.io/journey-planner/v3/graphql"
API_HEADERS = {
    "ET-Client-Name": "simenoddenhansen-togtider_dev",
    "Content-Type": "application/json",
}

TRANSPORT_CONFIG = {
    "bus":   {"label": "🚌 Buss",           "color": "#2ca02c", "rgb": [44, 160, 44]},
    "coach": {"label": "🚌 Buss (ekspress)","color": "#2ca02c", "rgb": [44, 160, 44]},
    "rail":  {"label": "🚆 Tog",            "color": "#1f77b4", "rgb": [31, 119, 180]},
    "tram":  {"label": "🚋 Trikk",          "color": "#9467bd", "rgb": [148, 103, 189]},
    "metro": {"label": "🚇 T-bane",         "color": "#ff7f0e", "rgb": [255, 127, 14]},
    "ferry": {"label": "⛴️ Ferge",          "color": "#17becf", "rgb": [23, 190, 207]},
    "water": {"label": "⛴️ Båt",            "color": "#17becf", "rgb": [23, 190, 207]},
    "air":   {"label": "✈️ Fly",            "color": "#d62728", "rgb": [214, 39, 40]},
    "taxi":  {"label": "🚕 Taxi",           "color": "#e7ba52", "rgb": [231, 186, 82]},
    "NA":    {"label": "❓ Ukjent",          "color": "#7f7f7f", "rgb": [127, 127, 127]},
}

MODE_ORDER = ["rail", "metro", "tram", "bus", "coach", "ferry", "water", "air", "taxi", "NA"]


# ─── Paths ────────────────────────────────────────────────────────

def project_root():
    """Return the absolute path to the project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def master_csv_path():
    return os.path.join(project_root(), "data_collection", "forsinkelser_master.csv")


def stations_csv_path():
    return os.path.join(project_root(), "data_collection", "alle_stasjoner.csv")


# ─── Data loading ─────────────────────────────────────────────────

def get_mtime(path):
    """Return file modification time, or None if the file doesn't exist."""
    try:
        if not os.path.exists(path):
            return None
        return os.path.getmtime(path)
    except OSError:
        return None


@st.cache_data
def load_delay_data(path, _mtime):
    """Load and parse the master delay CSV."""
    if _mtime is None or not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "scheduledDeparture" in df.columns:
        df["scheduledDeparture"] = pd.to_datetime(
            df["scheduledDeparture"], utc=True, errors="coerce"
        )
        df["scheduledDeparture"] = df["scheduledDeparture"].dt.tz_convert(OSLO_TZ)
    if "delaySeconds" in df.columns:
        df["delaySeconds"] = pd.to_numeric(df["delaySeconds"], errors="coerce").fillna(0)
    if "isDelayed" in df.columns:
        df["isDelayed"] = pd.to_numeric(df["isDelayed"], errors="coerce").fillna(0).astype(int)
    return df


@st.cache_data
def load_stations(path):
    """Load the station registry CSV."""
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


# ─── Entur API ────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def fetch_route_geometry(line_id):
    """Fetch stop-place coordinates for a line from the Entur API."""
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


# ─── Color & map helpers ─────────────────────────────────────────

def delay_to_color(delay_sec, max_delay_val):
    """Convert delay in seconds to [R, G, B, A] (green → yellow → red)."""
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
    """Estimate a pydeck zoom level from geographic spread."""
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


# ─── Reusable display column config ──────────────────────────────

DISPLAY_COLUMNS = [
    "stationName", "destination", "lineName", "lineCode",
    "transportMode", "scheduledDeparture", "delaySeconds", "isDelayed",
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
    "realtime": "Sanntid",
}


# ─── Download helper ─────────────────────────────────────────────

def download_csv_button(df, prefix="togforsinkelser"):
    """Render a download button for the given DataFrame."""
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


# ─── Entur credit footer ─────────────────────────────────────────

def entur_footer():
    """Render the standard Entur credit footer."""
    st.markdown("---")
    col_logo, col_text = st.columns([1, 5])
    with col_logo:
        st.image(
            "https://upload.wikimedia.org/wikipedia/commons/e/e0/Entur_logo.svg",
            width=80,
        )
    with col_text:
        st.markdown("**Data gjort tilgjengelig av Entur**")
        st.caption(
            "Dataene publiseres under Norsk lisens for offentlige data (NLOD). "
            "Entur påtar seg intet ansvar for konsekvenser av feil i dataene eller API-systemene."
        )
