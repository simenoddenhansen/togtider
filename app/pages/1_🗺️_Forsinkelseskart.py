"""
Forsinkelseskart – Interaktivt kart over forsinkelser
─────────────────────────────────────────────────────
Combines the best of the old Ruteoversikt and Forsinkelser_Norge
pages: an interactive pydeck map with colour-coded stations and
route lines, plus bar charts and a full detail table.
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import pydeck as pdk
import streamlit as st

# Ensure the parent app/ directory is on the path so we can import utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import (
    OSLO_TZ,
    TRANSPORT_CONFIG,
    MODE_ORDER,
    COLUMN_LABELS,
    DISPLAY_COLUMNS,
    load_delay_data,
    load_stations,
    master_csv_path,
    stations_csv_path,
    get_mtime,
    fetch_route_geometry,
    delay_to_color,
    compute_zoom,
    download_csv_button,
    entur_footer,
)

# ─── Page config ──────────────────────────────────────────────────

st.set_page_config(page_title="Forsinkelseskart", page_icon="🗺️", layout="wide")

st.title("🗺️ Forsinkelseskart")
st.caption(
    "Interaktivt kart over forsinkelser på norske togstasjoner. "
    "Grønn = liten forsinkelse · Gul = moderat · Rød = stor forsinkelse."
)

# ─── Load data ────────────────────────────────────────────────────

MASTER_PATH = master_csv_path()
STATIONS_PATH = stations_csv_path()

master_mtime = get_mtime(MASTER_PATH)
now_oslo = datetime.now(OSLO_TZ)

df_all = load_delay_data(MASTER_PATH, master_mtime)
df_stations = load_stations(STATIONS_PATH)

if df_all.empty:
    st.warning(
        "Ingen forsinkelsesdata funnet ennå. "
        "Kjør `python data_collection/forsinkelser_scraper.py` eller vent på neste GitHub Action-kjøring."
    )
    entur_footer()
    st.stop()


# ─── Sidebar filters ─────────────────────────────────────────────

st.sidebar.header("🔎 Filtre")

# Time period
time_options = ["Siste 24 timer", "Siste 7 dager", "Siste 30 dager", "Alle"]
selected_time = st.sidebar.selectbox(
    "Tidsperiode", options=time_options, index=2, key="map_time_filter"
)

df = df_all.copy()
if "scheduledDeparture" in df.columns:
    if selected_time == "Siste 24 timer":
        df = df[df["scheduledDeparture"] >= (now_oslo - timedelta(hours=24))]
    elif selected_time == "Siste 7 dager":
        df = df[df["scheduledDeparture"] >= (now_oslo - timedelta(days=7))]
    elif selected_time == "Siste 30 dager":
        df = df[df["scheduledDeparture"] >= (now_oslo - timedelta(days=30))]

# Line filter
all_lines = (
    sorted(df["lineName"].dropna().unique().tolist())
    if "lineName" in df.columns
    else []
)
selected_line = st.sidebar.selectbox(
    "Velg linje / rute",
    options=["— Alle ruter —"] + all_lines,
    index=0,
    key="map_line_filter",
)
if selected_line != "— Alle ruter —":
    df = df[df["lineName"] == selected_line]

# Station filter
stations_in_selection = (
    sorted(df["stationName"].dropna().unique().tolist())
    if "stationName" in df.columns
    else []
)
selected_station = st.sidebar.selectbox(
    "Filtrer på stasjon",
    options=["— Alle stasjoner —"] + stations_in_selection,
    index=0,
    key="map_station_filter",
)
if selected_station != "— Alle stasjoner —":
    df = df[df["stationName"] == selected_station]

# Transport mode
all_modes = (
    sorted(df["transportMode"].dropna().unique().tolist())
    if "transportMode" in df.columns
    else []
)
selected_modes = st.sidebar.multiselect(
    "Transporttype",
    options=all_modes,
    default=all_modes,
    key="map_mode_filter",
)
if selected_modes and "transportMode" in df.columns:
    df = df[df["transportMode"].isin(selected_modes)]

only_delayed = st.sidebar.checkbox(
    "Vis kun forsinkede", value=False, key="map_only_delayed"
)
if only_delayed and "isDelayed" in df.columns:
    df = df[df["isDelayed"] == 1]


# ─── KPIs ─────────────────────────────────────────────────────────

st.markdown("---")

kpi_cols = st.columns(4)
total_n = len(df)
delayed_n = int(df["isDelayed"].sum()) if "isDelayed" in df.columns else 0
pct = (100 * delayed_n / total_n) if total_n > 0 else 0
avg_delay = (df["delaySeconds"].mean() / 60) if total_n > 0 else 0
max_delay = (df["delaySeconds"].max() / 60) if total_n > 0 else 0

with kpi_cols[0]:
    st.metric("Avganger", f"{total_n:,}".replace(",", " "))
with kpi_cols[1]:
    st.metric("Forsinkede", f"{delayed_n:,} ({pct:.0f}%)".replace(",", " "))
with kpi_cols[2]:
    st.metric("Snitt forsinkelse", f"{avg_delay:.1f} min")
with kpi_cols[3]:
    st.metric("Maks forsinkelse", f"{max_delay:.0f} min")


# ═════════════════════════════════════════════════════════════════
# DELAY DISTRIBUTION
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📊 Forsinkelsesfordeling")

if not df.empty and "delaySeconds" in df.columns:
    delay_min = df["delaySeconds"] / 60

    # Define severity buckets
    buckets = {
        "I rute (0 min)":    (delay_min == 0).sum(),
        "< 1 min":           ((delay_min > 0) & (delay_min < 1)).sum(),
        "1–5 min":           ((delay_min >= 1) & (delay_min < 5)).sum(),
        "5–15 min":          ((delay_min >= 5) & (delay_min < 15)).sum(),
        "15–30 min":         ((delay_min >= 15) & (delay_min < 30)).sum(),
        "30+ min":           (delay_min >= 30).sum(),
    }

    dist_left, dist_right = st.columns([1, 2])

    with dist_left:
        st.markdown("**Antall avganger per forsinkelsesgruppe:**")

        emojis = ["🟢", "🟢", "🟡", "🟠", "🔴", "🔴"]
        for (label, count), emoji in zip(buckets.items(), emojis):
            pct_bucket = (100 * count / total_n) if total_n > 0 else 0
            st.markdown(f"{emoji} **{label}**: {count:,} ({pct_bucket:.1f}%)")

        on_time = buckets["I rute (0 min)"] + buckets["< 1 min"]
        on_time_pct = (100 * on_time / total_n) if total_n > 0 else 0
        st.markdown(f"\n**Punktlighet (< 1 min):** {on_time_pct:.1f}%")

    with dist_right:
        bucket_df = pd.DataFrame(
            {"Antall avganger": list(buckets.values())},
            index=list(buckets.keys()),
        )
        st.bar_chart(bucket_df)

else:
    st.info("Ingen forsinkelsesdata tilgjengelig for å vise fordeling.")


# ═════════════════════════════════════════════════════════════════
# MAP
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🗺️ Forsinkelseskart")

if not df.empty and not df_stations.empty:
    # Average delay per station
    station_delays = (
        df.groupby("stationId")
        .agg(avgDelay=("delaySeconds", "mean"), count=("isDelayed", "count"))
        .reset_index()
    )

    # Merge with station coordinates
    df_map = station_delays.merge(
        df_stations[["id", "name", "latitude", "longitude"]],
        left_on="stationId",
        right_on="id",
        how="inner",
    )

    if not df_map.empty and "latitude" in df_map.columns:
        df_map = df_map.dropna(subset=["latitude", "longitude"])

        max_delay_val = max(df_map["avgDelay"].max(), 1)

        df_map["color"] = df_map["avgDelay"].apply(
            lambda d: delay_to_color(d, max_delay_val)
        )
        df_map["delayMin"] = (df_map["avgDelay"] / 60).round(1)

        scatter_data = df_map.to_dict("records")

        # Station scatter layer
        scatter_layer = pdk.Layer(
            "ScatterplotLayer",
            data=scatter_data,
            get_position=["longitude", "latitude"],
            get_fill_color="color",
            get_radius=800,
            radius_min_pixels=4,
            radius_max_pixels=15,
            pickable=True,
        )

        layers = [scatter_layer]

        # ─── Route lines (when a specific line is selected) ───
        if selected_line != "— Alle ruter —" and "lineId" in df.columns:
            line_ids = df["lineId"].dropna().unique().tolist()

            line_segments = []

            for lid in line_ids[:5]:
                geometry = fetch_route_geometry(lid)
                if geometry is None:
                    continue

                stops = geometry["stops"]

                for i in range(len(stops) - 1):
                    s1 = stops[i]
                    s2 = stops[i + 1]

                    s1_name = s1.get("name", "")
                    s2_name = s2.get("name", "")

                    s1_delay = 0
                    s2_delay = 0
                    for _, row in df_map.iterrows():
                        if (
                            row["name"]
                            and s1_name
                            and row["name"].lower().startswith(s1_name.lower()[:8])
                        ):
                            s1_delay = row["avgDelay"]
                        if (
                            row["name"]
                            and s2_name
                            and row["name"].lower().startswith(s2_name.lower()[:8])
                        ):
                            s2_delay = row["avgDelay"]

                    seg_delay = (s1_delay + s2_delay) / 2
                    seg_color = delay_to_color(seg_delay, max_delay_val)

                    line_segments.append(
                        {
                            "from_lat": s1["latitude"],
                            "from_lng": s1["longitude"],
                            "to_lat": s2["latitude"],
                            "to_lng": s2["longitude"],
                            "color": seg_color,
                            "route": geometry["name"],
                            "delayMin": round(seg_delay / 60, 1),
                        }
                    )

            if line_segments:
                line_layer = pdk.Layer(
                    "LineLayer",
                    data=line_segments,
                    get_source_position=["from_lng", "from_lat"],
                    get_target_position=["to_lng", "to_lat"],
                    get_color="color",
                    get_width=4,
                    width_min_pixels=2,
                    pickable=True,
                )
                layers.insert(0, line_layer)

        # Map center & zoom
        center_lat = df_map["latitude"].mean()
        center_lng = df_map["longitude"].mean()
        lat_spread = df_map["latitude"].max() - df_map["latitude"].min()
        lng_spread = df_map["longitude"].max() - df_map["longitude"].min()
        zoom = compute_zoom(lat_spread, lng_spread)

        deck = pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=center_lat,
                longitude=center_lng,
                zoom=zoom,
                pitch=0,
            ),
            tooltip={
                "html": (
                    "<b>{name}</b><br/>"
                    "Snitt forsinkelse: <b>{delayMin} min</b><br/>"
                    "Avganger: {count}"
                ),
                "style": {
                    "backgroundColor": "#1a1a2e",
                    "color": "white",
                    "fontSize": "12px",
                    "padding": "8px",
                    "borderRadius": "6px",
                },
            },
            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        )

        st.pydeck_chart(deck, use_container_width=True)

        legend_text = "🟢 Grønn = liten forsinkelse · 🟡 Gul = moderat · 🔴 Rød = stor forsinkelse"
        if selected_line != "— Alle ruter —":
            legend_text += " · Linjer mellom stopp viser forsinkelse langs ruten"
        st.caption(legend_text)
    else:
        st.info("Kunne ikke koble forsinkelsesdata med stasjonskart.")
else:
    st.info("Ingen data å vise på kart.")


# ═════════════════════════════════════════════════════════════════
# Bar charts
# ═════════════════════════════════════════════════════════════════

st.markdown("---")

chart_left, chart_right = st.columns(2)

with chart_left:
    st.subheader("⏱️ Mest forsinkede stasjoner")
    if not df.empty and "delaySeconds" in df.columns:
        station_chart = (
            df.groupby("stationName")["delaySeconds"]
            .mean()
            .div(60)
            .sort_values(ascending=False)
            .head(15)
            .to_frame(name="Snitt forsinkelse (min)")
        )
        if not station_chart.empty:
            st.bar_chart(station_chart)
        else:
            st.info("Ingen data å vise.")
    else:
        st.info("Ingen data å vise.")

with chart_right:
    st.subheader("🚆 Mest forsinkede linjer")
    if not df.empty and "lineName" in df.columns:
        line_chart = (
            df.groupby("lineName")["delaySeconds"]
            .mean()
            .div(60)
            .sort_values(ascending=False)
            .head(15)
            .to_frame(name="Snitt forsinkelse (min)")
        )
        if not line_chart.empty:
            st.bar_chart(line_chart)
        else:
            st.info("Ingen data å vise.")
    else:
        st.info("Ingen data å vise.")


# ═════════════════════════════════════════════════════════════════
# Detail table
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📋 Avganger (detaljer)")

existing_cols = [c for c in DISPLAY_COLUMNS if c in df.columns]
if "realtime" in df.columns:
    existing_cols.append("realtime")

df_table = df[existing_cols].sort_values("scheduledDeparture", ascending=False)
df_table = df_table.rename(columns=COLUMN_LABELS)

st.dataframe(df_table, use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════
# CSV download
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
download_csv_button(df, prefix="forsinkelseskart")


# ═════════════════════════════════════════════════════════════════
# Footer
# ═════════════════════════════════════════════════════════════════

entur_footer()
