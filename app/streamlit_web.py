import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Togforsinkelser på Sandvika stasjon", layout="wide")

st.title("Togforsinkelser på Sandvika stasjon (tog som kommer fra Oslo)")
st.caption("Basert på avgangsdata fra Oslo S og slutt-destinasjon (proxy for tog som passerer Sandvika).")

# Egendefinert knapp for å starte skjult YouTube-musikk (omgår nettleserens autoplay-blokkering)
components.html(
    """
    <div id="player"></div>
    <button id="play-btn" onclick="playAudio()" style="padding: 8px 16px; background-color: #ff4b4b; color: white; border: none; border-radius: 4px; cursor: pointer; font-family: sans-serif; font-size: 14px;">
        🎵 Spill bakgrunnsmusikk
    </button>

    <script>
        var tag = document.createElement('script');
        tag.src = "https://www.youtube.com/iframe_api";
        var firstScriptTag = document.getElementsByTagName('script')[0];
        firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

        var player;
        function onYouTubeIframeAPIReady() {
            player = new YT.Player('player', {
                height: '0',
                width: '0',
                videoId: 'GHe8kKO8uds',
                playerVars: { 'playsinline': 1 }
            });
        }

        function playAudio() {
            if (player && typeof player.playVideo === 'function') {
                player.playVideo();
                document.getElementById('play-btn').style.display = 'none';
            }
        }
    </script>
    """,
    height=45,
)

CSV_PATH = "Alle_reiser_Oslo_Sandvika.csv"
OSLO_TZ = ZoneInfo("Europe/Oslo")

# Auto-refresh so the countdown (and newly updated CSV data) shows up without manual reload
st_autorefresh(interval=1000, key="countdown-refresh")


def _get_mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


@st.cache_data
def load_data(path: str, mtime: float | None) -> pd.DataFrame:
    if mtime is None or not os.path.exists(path):
        return pd.DataFrame()

    df = pd.read_csv(path)

    # Backward compatibility: older rows/files won't have these columns
    for col in ["routeId", "routeName", "transportMode", "serviceJourneyId"]:
        if col not in df.columns:
            df[col] = pd.NA

    # Types
    if "scheduledDeparture" in df.columns:
        df["scheduledDeparture"] = pd.to_datetime(df["scheduledDeparture"], utc=True, errors="coerce")
        df["scheduledDeparture"] = df["scheduledDeparture"].dt.tz_convert(OSLO_TZ)

    if "delaySeconds" in df.columns:
        df["delaySeconds"] = pd.to_numeric(df["delaySeconds"], errors="coerce")

    if "isDelayed" in df.columns:
        df["isDelayed"] = pd.to_numeric(df["isDelayed"], errors="coerce").fillna(0).astype(int)

    return df


csv_mtime = _get_mtime(CSV_PATH)
now_oslo = datetime.now(OSLO_TZ)

df = load_data(CSV_PATH, csv_mtime)

if csv_mtime is not None:
    last_updated = datetime.fromtimestamp(csv_mtime, tz=OSLO_TZ)
    next_expected = last_updated + timedelta(hours=1)
    seconds_left = int((next_expected - now_oslo).total_seconds())

    remaining = max(0, seconds_left)
    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    countdown = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    status_cols = st.columns([2, 1])
    with status_cols[0]:
        st.caption(
            f"Sist oppdatert: {last_updated:%Y-%m-%d %H:%M:%S} (Europe/Oslo) • "
            f"Neste forventet: {next_expected:%Y-%m-%d %H:%M:%S}"
        )
    with status_cols[1]:
        label = "Tid til neste forventede oppdatering" if seconds_left >= 0 else "Forventet oppdatering (forsinket)"
        st.metric(label, countdown)
else:
    st.info("Fant ikke datafilen ennå. Venter på første innsamling.")


if df.empty:
    st.info("Ingen data å vise ennå.")
else:
    # --- Sidebar filters ---
    st.sidebar.header("Filtre")

    time_range = st.sidebar.selectbox(
        "Tidsperiode",
        ["Siste 24 timer", "Siste 7 dager", "Siste 30 dager", "Alle"],
        index=2,
    )

    if time_range == "Siste 24 timer":
        df_time = df[df["scheduledDeparture"] >= (now_oslo - timedelta(hours=24))]
    elif time_range == "Siste 7 dager":
        df_time = df[df["scheduledDeparture"] >= (now_oslo - timedelta(days=7))]
    elif time_range == "Siste 30 dager":
        df_time = df[df["scheduledDeparture"] >= (now_oslo - timedelta(days=30))]
    else:
        df_time = df

    destinations = sorted(df_time["destination"].dropna().unique().tolist()) if "destination" in df_time.columns else []
    selected_destinations = st.sidebar.multiselect("Slutt-destinasjon", destinations, default=destinations)

    route_names = sorted(df_time["routeName"].fillna("NA").unique().tolist())
    selected_route_names = st.sidebar.multiselect("Linje / rute-navn", route_names, default=route_names)

    transport_modes = sorted(df_time["transportMode"].fillna("NA").unique().tolist())
    selected_transport_modes = st.sidebar.multiselect("Transportmode", transport_modes, default=transport_modes)

    only_delayed = st.sidebar.checkbox("Vis kun forsinkede", value=False)
    min_delay_min = st.sidebar.slider("Min forsinkelse (min)", min_value=0, max_value=60, value=0, step=1)

    df_filtered = df_time.copy()

    if selected_destinations:
        df_filtered = df_filtered[df_filtered["destination"].isin(selected_destinations)]

    if selected_route_names:
        df_filtered = df_filtered[df_filtered["routeName"].fillna("NA").isin(selected_route_names)]

    if selected_transport_modes:
        df_filtered = df_filtered[df_filtered["transportMode"].fillna("NA").isin(selected_transport_modes)]

    if only_delayed and "isDelayed" in df_filtered.columns:
        df_filtered = df_filtered[df_filtered["isDelayed"] == 1]

    if min_delay_min > 0 and "delaySeconds" in df_filtered.columns:
        df_filtered = df_filtered[df_filtered["delaySeconds"] >= (min_delay_min * 60)]

    # --- KPIs ---
    kpi_cols = st.columns(3)
    with kpi_cols[0]:
        st.metric("Totale avganger", int(len(df_filtered)))
    with kpi_cols[1]:
        st.metric("Forsinkede tog", int(df_filtered["isDelayed"].sum()) if "isDelayed" in df_filtered.columns else 0)
    with kpi_cols[2]:
        avg_delay = df_filtered["delaySeconds"].mean() / 60 if "delaySeconds" in df_filtered.columns else 0
        st.metric("Snitt forsinkelse", f"{avg_delay:.1f} min")

    # --- Charts ---
    st.subheader("Gjennomsnittlig forsinkelse per slutt-destinasjon")
    if not df_filtered.empty and "delaySeconds" in df_filtered.columns:
        chart_data = (df_filtered.groupby("destination")["delaySeconds"].mean() / 60).sort_values(ascending=False)
        st.bar_chart(chart_data)

    st.subheader("Historisk punktlighet per rute (Oslo → slutt-destinasjon)")

    with st.sidebar.expander("Rutehistorikk", expanded=True):
        route_end = st.selectbox("Velg slutt-destinasjon", destinations if destinations else ["NA"])
        route_line = st.selectbox(
            "(Valgfritt) Velg linje / rute-navn",
            ["Alle"] + route_names,
        )
        metric = st.selectbox("Måltall", ["Snittforsinkelse (min)", "Andel forsinket (%)"])
        granularity = st.selectbox("Oppløsning", ["Dag", "Uke", "Måned"])

    df_route = df_time.copy()
    if route_end != "NA" and "destination" in df_route.columns:
        df_route = df_route[df_route["destination"] == route_end]

    if route_line != "Alle":
        df_route = df_route[df_route["routeName"].fillna("NA") == route_line]

    if df_route.empty:
        st.info("Ingen historiske data for valgt rute i valgt tidsperiode.")
    else:
        df_route = df_route.dropna(subset=["scheduledDeparture"]).set_index("scheduledDeparture")
        df_route = df_route.sort_index()

        rule = {"Dag": "D", "Uke": "W", "Måned": "M"}[granularity]

        if metric == "Snittforsinkelse (min)":
            series = (df_route["delaySeconds"].resample(rule).mean() / 60).to_frame(name="Snitt (min)")
        else:
            series = (df_route["isDelayed"].resample(rule).mean() * 100).to_frame(name="Andel (%)")

        st.line_chart(series)

    # --- Table ---
    st.subheader("Avganger fra Oslo (tog som forventes å passere Sandvika)")

    columns_for_table = [
        "scheduledDeparture",
        "destination",
        "routeName",
        "routeId",
        "serviceJourneyId",
        "transportMode",
        "delaySeconds",
        "isDelayed",
        "actualDeparture",
    ]

    df_table = df_filtered.copy()
    for col in columns_for_table:
        if col not in df_table.columns:
            df_table[col] = pd.NA

    df_table = df_table[columns_for_table].sort_values(by="scheduledDeparture", ascending=False)

    for col in ["routeName", "routeId", "serviceJourneyId", "transportMode"]:
        df_table[col] = df_table[col].fillna("NA")

    st.dataframe(df_table, use_container_width=True)


# --- ENTUR RETNINGSLINJER OG KREDITERING ---
st.markdown("---") # Lager en tynn, pen skillelinje

# Lager to kolonner slik at logoen og teksten står pent ved siden av hverandre
col_logo, col_text = st.columns([1, 5])

with col_logo:
    # Henter Entur-logoen direkte fra nettet (Wikimedia Commons for stabilitet)
    st.image("https://upload.wikimedia.org/wikipedia/commons/e/e0/Entur_logo.svg", width=80)

with col_text:
    st.markdown("**Data gjort tilgjengelig av Entur**")
    st.caption(
        "Dataene publiseres under Norsk lisens for offentlige data (NLOD). "
        "Entur påtar seg intet ansvar for konsekvenser av feil i dataene eller API-systemene."
    )