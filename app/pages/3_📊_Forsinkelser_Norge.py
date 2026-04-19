import os
import pandas as pd
import streamlit as st
import pydeck as pdk

st.set_page_config(page_title="Forsinkelser Norge", page_icon="📊", layout="wide")

st.title("📊 Forsinkelser i Norge")
st.caption("Se forsinkelsesdata for togstasjoner i hele landet, samlet inn automatisk.")

# --- Finn data ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
master_path = os.path.join(project_root, "data_collection", "forsinkelser_master.csv")
stations_path = os.path.join(project_root, "data_collection", "alle_stasjoner.csv")


@st.cache_data
def load_delay_data(path, _mtime):
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "scheduledDeparture" in df.columns:
        df["scheduledDeparture"] = pd.to_datetime(df["scheduledDeparture"], utc=True, errors="coerce")
    if "delaySeconds" in df.columns:
        df["delaySeconds"] = pd.to_numeric(df["delaySeconds"], errors="coerce").fillna(0)
    if "isDelayed" in df.columns:
        df["isDelayed"] = pd.to_numeric(df["isDelayed"], errors="coerce").fillna(0).astype(int)
    return df


@st.cache_data
def load_stations(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


# Load data
master_mtime = os.path.getmtime(master_path) if os.path.exists(master_path) else None
df = load_delay_data(master_path, master_mtime)
df_stations = load_stations(stations_path)

if df.empty:
    st.warning(
        "Ingen forsinkelsesdata funnet ennå. "
        "Kjør `python data_collection/forsinkelser_scraper.py` eller vent på neste GitHub Action-kjøring."
    )
    st.stop()

# ─────────────────────────────────────────────────────────────
# Sidebar: route selection
# ─────────────────────────────────────────────────────────────

st.sidebar.header("🔎 Velg rute")

# Get unique line names (sorted)
all_lines = sorted(df["lineName"].dropna().unique().tolist())

selected_line = st.sidebar.selectbox(
    "Velg linje / rute",
    options=["— Alle ruter —"] + all_lines,
    index=0,
)

# Filter by line
if selected_line != "— Alle ruter —":
    df_line = df[df["lineName"] == selected_line].copy()
else:
    df_line = df.copy()

# Station filter (based on current line selection)
stations_in_line = sorted(df_line["stationName"].dropna().unique().tolist())
selected_station = st.sidebar.selectbox(
    "Filtrer på stasjon (valgfritt)",
    options=["— Alle stasjoner —"] + stations_in_line,
    index=0,
)

if selected_station != "— Alle stasjoner —":
    df_view = df_line[df_line["stationName"] == selected_station].copy()
else:
    df_view = df_line.copy()

# ─────────────────────────────────────────────────────────────
# KPIs
# ─────────────────────────────────────────────────────────────

st.markdown("---")

kpi_cols = st.columns(4)

with kpi_cols[0]:
    st.metric("Avganger", len(df_view))

with kpi_cols[1]:
    delayed_count = int(df_view["isDelayed"].sum()) if "isDelayed" in df_view.columns else 0
    pct = (100 * delayed_count / len(df_view)) if len(df_view) > 0 else 0
    st.metric("Forsinkede", f"{delayed_count} ({pct:.0f}%)")

with kpi_cols[2]:
    avg_delay = df_view["delaySeconds"].mean() / 60 if len(df_view) > 0 else 0
    st.metric("Snitt forsinkelse", f"{avg_delay:.1f} min")

with kpi_cols[3]:
    max_delay = df_view["delaySeconds"].max() / 60 if len(df_view) > 0 else 0
    st.metric("Maks forsinkelse", f"{max_delay:.0f} min")

# ─────────────────────────────────────────────────────────────
# Delay per station (bar chart)
# ─────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("⏱️ Gjennomsnittlig forsinkelse per stasjon")

if not df_view.empty and "delaySeconds" in df_view.columns:
    chart_data = (
        df_view.groupby("stationName")["delaySeconds"]
        .mean()
        .div(60)
        .sort_values(ascending=False)
        .head(20)
        .to_frame(name="Snitt forsinkelse (min)")
    )
    if not chart_data.empty:
        st.bar_chart(chart_data)
    else:
        st.info("Ingen data å vise.")
else:
    st.info("Ingen data å vise.")

# ─────────────────────────────────────────────────────────────
# Delay % per line (top worst lines)
# ─────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("🚆 Mest forsinkede linjer")

if selected_line == "— Alle ruter —" and not df.empty:
    line_stats = (
        df.groupby("lineName")
        .agg(
            avgDelay=("delaySeconds", "mean"),
            delayedPct=("isDelayed", "mean"),
            totalDeps=("isDelayed", "count"),
        )
        .assign(
            avgDelay=lambda x: x["avgDelay"] / 60,
            delayedPct=lambda x: x["delayedPct"] * 100,
        )
        .sort_values("avgDelay", ascending=False)
        .head(15)
        .rename(columns={
            "avgDelay": "Snitt forsinkelse (min)",
            "delayedPct": "Andel forsinket (%)",
            "totalDeps": "Antall avganger",
        })
    )
    st.dataframe(line_stats, use_container_width=True)
else:
    st.caption("Velg «Alle ruter» for å se rangering.")

# ─────────────────────────────────────────────────────────────
# Map: stations colored by delay
# ─────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("🗺️ Forsinkelseskart")

if not df_view.empty and not df_stations.empty:
    # Compute average delay per station
    station_delays = (
        df_view.groupby("stationId")
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

        # Color: green (0 delay) → yellow → red (high delay)
        max_delay_val = max(df_map["avgDelay"].max(), 1)

        def delay_to_color(delay_sec):
            ratio = min(delay_sec / max_delay_val, 1.0)
            if ratio < 0.5:
                # Green → Yellow
                r = int(255 * (ratio * 2))
                g = 200
                b = 50
            else:
                # Yellow → Red
                r = 255
                g = int(200 * (1 - (ratio - 0.5) * 2))
                b = 50
            return [r, g, b, 180]

        df_map["color"] = df_map["avgDelay"].apply(delay_to_color)
        df_map["delayMin"] = (df_map["avgDelay"] / 60).round(1)

        scatter_data = df_map.to_dict("records")

        layer = pdk.Layer(
            "ScatterplotLayer",
            data=scatter_data,
            get_position=["longitude", "latitude"],
            get_fill_color="color",
            get_radius=800,
            radius_min_pixels=4,
            radius_max_pixels=15,
            pickable=True,
        )

        center_lat = df_map["latitude"].mean()
        center_lng = df_map["longitude"].mean()

        lat_spread = df_map["latitude"].max() - df_map["latitude"].min()
        lng_spread = df_map["longitude"].max() - df_map["longitude"].min()
        spread = max(lat_spread, lng_spread)
        if spread > 10:
            zoom = 4
        elif spread > 5:
            zoom = 5
        elif spread > 2:
            zoom = 6
        elif spread > 1:
            zoom = 7
        elif spread > 0.5:
            zoom = 8
        else:
            zoom = 10

        deck = pdk.Deck(
            layers=[layer],
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
            map_style="mapbox://styles/mapbox/dark-v11",
        )

        st.pydeck_chart(deck, use_container_width=True)
        st.caption(
            "🟢 Grønn = liten forsinkelse · 🟡 Gul = moderat · 🔴 Rød = stor forsinkelse"
        )
    else:
        st.info("Kunne ikke koble forsinkelsesdata med stasjonskart.")
else:
    st.info("Ingen data å vise på kart.")


# ─────────────────────────────────────────────────────────────
# Detail table
# ─────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("📋 Avganger (detaljer)")

show_only_delayed = st.checkbox("Vis kun forsinkede", value=False)

df_table = df_view.copy()
if show_only_delayed:
    df_table = df_table[df_table["isDelayed"] == 1]

display_cols = [
    "stationName", "destination", "lineName", "lineCode",
    "scheduledDeparture", "delaySeconds", "isDelayed", "realtime",
]
existing_cols = [c for c in display_cols if c in df_table.columns]
df_table = df_table[existing_cols].sort_values("scheduledDeparture", ascending=False)

# Rename for display
col_labels = {
    "stationName": "Stasjon",
    "destination": "Destinasjon",
    "lineName": "Linje",
    "lineCode": "Kode",
    "scheduledDeparture": "Planlagt avgang",
    "delaySeconds": "Forsinkelse (s)",
    "isDelayed": "Forsinket",
    "realtime": "Sanntid",
}
df_table = df_table.rename(columns=col_labels)

st.dataframe(df_table, use_container_width=True, hide_index=True)


# --- ENTUR RETNINGSLINJER OG KREDITERING ---
st.markdown("---")
col_logo, col_text = st.columns([1, 5])

with col_logo:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/e/e0/Entur_logo.svg",
        width=80)

with col_text:
    st.markdown("**Data gjort tilgjengelig av Entur**")
    st.caption("Dataene publiseres under Norsk lisens for offentlige data (NLOD).")
