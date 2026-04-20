"""
Søk Reise – Finn neste reise med punktlighetsindikator
───────────────────────────────────────────────────────
Journey search page using the Entur Journey Planner API.
Now also shows historical punctuality badges per line,
based on the locally collected delay data.
"""

import datetime
import os
import sys
from typing import Optional, Tuple

import pandas as pd
import streamlit as st
import requests

# Ensure the parent app/ directory is on the path so we can import utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import (
    API_HEADERS,
    OSLO_TZ,
    load_delay_data,
    master_csv_path,
    get_mtime,
    entur_footer,
)

st.set_page_config(page_title="Reisesøk", page_icon="🚆", layout="centered")
st.title("🚆 Finn neste reise")
st.markdown("Søk etter reiser i hele Norge, direkte fra Entur.")

# --- API Konfigurasjon ---
GEOCODER_API_URL = "https://api.entur.io/geocoder/v1/autocomplete"
JOURNEY_API_URL = "https://api.entur.io/journey-planner/v3/graphql"

# --- Transport mode icons and labels ---
MODE_ICONS = {
    "bus":    "🚌",
    "rail":   "🚆",
    "tram":   "🚋",
    "metro":  "🚇",
    "water":  "⛴️",
    "ferry":  "⛴️",
    "air":    "✈️",
    "coach":  "🚌",
}

CATEGORY_ICONS = {
    "onstreetBus":  "🚌",
    "busStation":   "🚌",
    "railStation":  "🚆",
    "metroStation": "🚇",
    "tramStation":  "🚋",
    "airport":      "✈️",
    "harbourPort":  "⛴️",
    "ferryStop":    "⛴️",
}

MODE_EMOJI = {
    "foot":   "🚶‍♂️",
    "bus":    "🚌",
    "rail":   "🚆",
    "tram":   "🚋",
    "metro":  "🚇",
    "water":  "⛴️",
    "air":    "✈️",
}

MODE_NO = {
    "foot":   "Gå",
    "bus":    "Buss",
    "rail":   "Tog",
    "tram":   "Trikk",
    "metro":  "T-bane",
    "water":  "Båt",
    "air":    "Fly",
}


# ─── Load historical delay data for punctuality badges ────────────

MASTER_PATH = master_csv_path()
master_mtime = get_mtime(MASTER_PATH)
df_delays = load_delay_data(MASTER_PATH, master_mtime)


@st.cache_data
def get_line_punctuality(_df_hash, line_name):
    """Return punctuality % for a given line name, or None if unknown."""
    if df_delays.empty or "lineName" not in df_delays.columns:
        return None
    df_line = df_delays[df_delays["lineName"] == line_name]
    if len(df_line) < 5:
        return None
    return 100 * (1 - df_line["isDelayed"].mean())


# ─── Helpers ──────────────────────────────────────────────────────

def parse_transport_icons(feature_props: dict) -> str:
    """Extract unique transport mode icons from an Entur geocoder feature."""
    icons_seen = set()
    icons_list = []

    modes = feature_props.get("mode", [])
    for m in modes:
        for key in m.keys():
            icon = MODE_ICONS.get(key.lower())
            if icon and icon not in icons_seen:
                icons_seen.add(icon)
                icons_list.append(icon)

    if not icons_list:
        categories = feature_props.get("category", [])
        for cat in categories:
            icon = CATEGORY_ICONS.get(cat)
            if icon and icon not in icons_seen:
                icons_seen.add(icon)
                icons_list.append(icon)

    return " ".join(icons_list)


@st.cache_data(ttl=60)
def get_station_suggestions(query_text: str):
    """
    Returns a list of dicts: {label, id, icons}
    One entry per unique stop from the Entur geocoder.
    """
    if not query_text or len(query_text.strip()) < 2:
        return []

    params = {"text": query_text.strip(), "size": 10, "lang": "no"}
    try:
        response = requests.get(
            GEOCODER_API_URL,
            params=params,
            headers={"ET-Client-Name": API_HEADERS["ET-Client-Name"]},
            timeout=5,
        )
        data = response.json()

        results = []
        seen_ids = set()
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            station_id = props.get("id", "")
            label = props.get("label", props.get("name", ""))
            if not label or station_id in seen_ids:
                continue
            seen_ids.add(station_id)
            icons = parse_transport_icons(props)
            results.append({"label": label, "id": station_id, "icons": icons})
        return results
    except Exception as e:
        st.error(f"Feil ved oppslag av stasjoner: {e}")
        return []


TRIP_QUERY = """
query GetTrip($fromId: String!, $toId: String!) {
  trip(
    from: {place: $fromId}
    to: {place: $toId}
    numTripPatterns: 5
  ) {
    tripPatterns {
      expectedStartTime
      expectedEndTime
      duration
      legs {
        mode
        distance
        line {
          id
          publicCode
          name
        }
        fromPlace {
          name
        }
        toPlace {
          name
        }
        situations {
          summary {
            value
          }
          description {
            value
          }
        }
      }
    }
  }
}
"""


def fetch_journeys(from_id: str, to_id: str):
    """Henter reiseforslag mellom to ID-er."""
    payload = {
        "query": TRIP_QUERY,
        "variables": {"fromId": from_id, "toId": to_id},
    }
    try:
        response = requests.post(
            JOURNEY_API_URL,
            json=payload,
            headers=API_HEADERS,
            timeout=10,
        )
        return response.json()
    except Exception as e:
        st.error(f"Feil ved henting av reise: {e}")
        return None


# ─── Autocomplete widget ─────────────────────────────────────────

def station_autocomplete(
    label: str, key: str, default_value: str = ""
) -> Tuple[Optional[str], Optional[str]]:
    """
    Renders a text input with a live suggestion dropdown beneath it.
    Returns (selected_label, selected_id) or (None, None) if nothing chosen.
    """
    input_key = f"{key}_input"
    chosen_key = f"{key}_chosen_label"
    chosen_id_key = f"{key}_chosen_id"

    if input_key not in st.session_state:
        st.session_state[input_key] = default_value
    if chosen_key not in st.session_state:
        st.session_state[chosen_key] = None
    if chosen_id_key not in st.session_state:
        st.session_state[chosen_id_key] = None

    st.markdown(f"**{label}**")

    query = st.text_input(
        "Skriv stasjon eller holdeplass…",
        key=input_key,
        label_visibility="collapsed",
        placeholder="Skriv stasjon eller holdeplass…",
    )

    if query != st.session_state.get(f"{key}_last_query"):
        st.session_state[chosen_key] = None
        st.session_state[chosen_id_key] = None
        st.session_state[f"{key}_last_query"] = query

    chosen_label = st.session_state[chosen_key]
    chosen_id = st.session_state[chosen_id_key]

    if chosen_label and chosen_id:
        st.success(f"✅ Valgt: **{chosen_label}**")
        if st.button("Endre valg", key=f"{key}_clear"):
            st.session_state[chosen_key] = None
            st.session_state[chosen_id_key] = None
            st.rerun()
        return chosen_label, chosen_id

    suggestions = get_station_suggestions(query)

    if query and len(query.strip()) >= 2:
        if not suggestions:
            st.caption("Ingen forslag funnet.")
        else:
            for i, suggestion in enumerate(suggestions):
                icons = suggestion["icons"]
                name = suggestion["label"]
                sid = suggestion["id"]
                btn_label = f"{icons}  {name}" if icons else name

                if st.button(
                    btn_label, key=f"{key}_sug_{i}", use_container_width=True
                ):
                    st.session_state[chosen_key] = name
                    st.session_state[chosen_id_key] = sid
                    st.rerun()

    return None, None


# ─── UI Layout ────────────────────────────────────────────────────

st.markdown("### 1. Velg stasjoner")

col1, col2 = st.columns(2)

with col1:
    from_label, from_id = station_autocomplete(
        "Fra:", key="from", default_value="Oslo S"
    )

with col2:
    to_label, to_id = station_autocomplete(
        "Til:", key="to", default_value="Sandvika"
    )

st.markdown("---")

# ─── Journey search ──────────────────────────────────────────────

if st.button("Søk etter reiser 🔍", type="primary"):
    if not from_id or not to_id:
        st.warning("Vennligst velg både et 'Fra'- og 'Til'-sted fra forslagene.")
    else:
        with st.spinner("Leter etter reiser…"):
            st.success(f"Søker reise: **{from_label}** ➡️ **{to_label}**")
            data = fetch_journeys(from_id, to_id)

            if data:
                trips = (
                    data.get("data", {}).get("trip", {}).get("tripPatterns", [])
                )

                if not trips:
                    st.info(
                        "Fant ingen reiser på denne strekningen i nærmeste fremtid."
                    )
                else:
                    for i, trip in enumerate(trips):
                        start_dt = datetime.datetime.fromisoformat(
                            trip["expectedStartTime"]
                        )
                        end_dt = datetime.datetime.fromisoformat(
                            trip["expectedEndTime"]
                        )
                        start_time = start_dt.strftime("%H:%M")
                        end_time = end_dt.strftime("%H:%M")
                        duration_minutes = trip["duration"] // 60

                        modes_used = []
                        for leg in trip["legs"]:
                            m = leg.get("mode", "foot")
                            emoji = MODE_EMOJI.get(m, "🚏")
                            if emoji not in modes_used:
                                modes_used.append(emoji)
                        modes_str = " ".join(modes_used)

                        with st.expander(
                            f"Avgang kl {start_time} – Ankomst {end_time} "
                            f"({duration_minutes} min) {modes_str}",
                            expanded=(i == 0),
                        ):
                            for leg in trip["legs"]:
                                mode_raw = leg.get("mode", "foot")
                                mode_name = MODE_NO.get(
                                    mode_raw, mode_raw.capitalize()
                                )
                                emoji = MODE_EMOJI.get(mode_raw, "🚏")
                                line_info = leg.get("line") or {}
                                line_code = line_info.get("publicCode", "")
                                line_name = line_info.get("name", "")
                                from_name = leg["fromPlace"]["name"]
                                to_name = leg["toPlace"]["name"]

                                if mode_raw == "foot":
                                    distance = int(leg.get("distance", 0))
                                    st.markdown(
                                        f"{emoji} **Gå** {distance} meter "
                                        f"fra _{from_name}_ til _{to_name}_"
                                    )
                                else:
                                    line_str = (
                                        f" {line_code}" if line_code else ""
                                    )
                                    st.markdown(
                                        f"{emoji} **{mode_name}{line_str}**: "
                                        f"{from_name} ➡️ {to_name}"
                                    )

                                    # ─── Punctuality badge ───
                                    if line_name:
                                        # Use a simple hash of the delay df length for caching
                                        df_hash = len(df_delays)
                                        punct = get_line_punctuality(
                                            df_hash, line_name
                                        )
                                        if punct is not None:
                                            if punct >= 90:
                                                st.caption(
                                                    f"✅ {punct:.0f}% punktlig (historisk)"
                                                )
                                            elif punct >= 75:
                                                st.caption(
                                                    f"⚠️ {punct:.0f}% punktlig (historisk)"
                                                )
                                            else:
                                                st.caption(
                                                    f"🔴 {punct:.0f}% punktlig (historisk)"
                                                )

                                for sit in leg.get("situations", []):
                                    summary = sit.get("summary", [])
                                    if summary:
                                        st.warning(
                                            f"⚠️ **Avvik:** {summary[0].get('value')}"
                                        )

                            st.markdown("---")

# ─── Footer ──────────────────────────────────────────────────────

entur_footer()
