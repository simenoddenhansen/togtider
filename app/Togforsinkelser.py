import os
from datetime import datetime, timedelta
import pytz

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    from streamlit_autorefresh import st_autorefresh

    _HAS_AUTOREFRESH = True
except ModuleNotFoundError:
    # Optional dependency: keep the app working even if it's not installed.
    _HAS_AUTOREFRESH = False

    def st_autorefresh(*args, **kwargs):  # type: ignore[no-redef]
        return None


st.set_page_config(
    page_title="Togforsinkelser",
    page_icon="🚆",
    layout="wide")

st.title("🚆 Togforsinkelser i Norge")
st.markdown(
    "Automatisk innsamling av forsinkelsesdata fra norsk kollektivtransport via "
    "[Entur](https://entur.no). Dataene oppdateres hver time via GitHub Actions."
)

# Egendefinert knapp for å starte skjult YouTube-musikk (omgår
# nettleserens autoplay-blokkering)
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
                videoId: 'kMLLXxtUIxc', // <-- Updated video ID here
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

OSLO_TZ = pytz.timezone("Europe/Oslo")

# ─────────────────────────────────────────────────────────────
# Data paths
# ─────────────────────────────────────────────────────────────

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

# Nationwide delay data
MASTER_PATH = os.path.join(project_root, "data_collection", "forsinkelser_master.csv")
# Sandvika-specific data (legacy)
SANDVIKA_CSV = os.path.join(project_root, "reiser_oslo_sandvika", "Alle_reiser_Oslo_Sandvika.csv")

if not os.path.exists(SANDVIKA_CSV):
    fallback = os.path.join("reiser_oslo_sandvika", "Alle_reiser_Oslo_Sandvika.csv")
    if os.path.exists(fallback):
        SANDVIKA_CSV = fallback

# Auto-refresh so the countdown (and newly updated CSV data) shows up
# without manual reload
if _HAS_AUTOREFRESH:
    st_autorefresh(interval=60000, key="countdown-refresh")
else:
    st.info(
        "Automatisk nedtelling krever pakken 'streamlit-autorefresh'. "
        "Installer den i miljøet ditt for å få auto-oppdatering."
    )


def _get_mtime(path):
    try:
        if not os.path.exists(path):
            return None
        return os.path.getmtime(path)
    except OSError:
        return None


# ─────────────────────────────────────────────────────────────
# Load nationwide data
# ─────────────────────────────────────────────────────────────

@st.cache_data
def load_master(path, mtime):
    if mtime is None or not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "scheduledDeparture" in df.columns:
        df["scheduledDeparture"] = pd.to_datetime(df["scheduledDeparture"], utc=True, errors="coerce")
        df["scheduledDeparture"] = df["scheduledDeparture"].dt.tz_convert(OSLO_TZ)
    if "delaySeconds" in df.columns:
        df["delaySeconds"] = pd.to_numeric(df["delaySeconds"], errors="coerce").fillna(0)
    if "isDelayed" in df.columns:
        df["isDelayed"] = pd.to_numeric(df["isDelayed"], errors="coerce").fillna(0).astype(int)
    return df


@st.cache_data
def load_sandvika(path, mtime):
    if mtime is None or not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    for col in ["routeId", "routeName", "transportMode", "serviceJourneyId"]:
        if col not in df.columns:
            df[col] = pd.NA
    if "scheduledDeparture" in df.columns:
        df["scheduledDeparture"] = pd.to_datetime(df["scheduledDeparture"], utc=True, errors="coerce")
        df["scheduledDeparture"] = df["scheduledDeparture"].dt.tz_convert(OSLO_TZ)
    if "delaySeconds" in df.columns:
        df["delaySeconds"] = pd.to_numeric(df["delaySeconds"], errors="coerce")
    if "isDelayed" in df.columns:
        df["isDelayed"] = pd.to_numeric(df["isDelayed"], errors="coerce").fillna(0).astype(int)
    return df


master_mtime = _get_mtime(MASTER_PATH)
sandvika_mtime = _get_mtime(SANDVIKA_CSV)
now_oslo = datetime.now(OSLO_TZ)

df_master = load_master(MASTER_PATH, master_mtime)
df_sandvika = load_sandvika(SANDVIKA_CSV, sandvika_mtime)

# ─────────────────────────────────────────────────────────────
# Data freshness info
# ─────────────────────────────────────────────────────────────

if master_mtime is not None:
    last_updated = datetime.fromtimestamp(master_mtime, tz=OSLO_TZ)
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
            f"Neste forventet: {next_expected:%Y-%m-%d %H:%M:%S}")
    with status_cols[1]:
        label = "Tid til neste forventede oppdatering" if seconds_left >= 0 else "Forventet oppdatering (forsinket)"
        st.metric(label, countdown)
else:
    st.info("Fant ikke datafilen ennå. Venter på første innsamling.")


# ═════════════════════════════════════════════════════════════
# SECTION 1: Nationwide overview
# ═════════════════════════════════════════════════════════════

if not df_master.empty:
    st.markdown("---")
    st.header("📊 Oversikt – alle innsamlede forsinkelser")

    # --- Sidebar filters for nationwide data ---
    st.sidebar.header("🔎 Filtre (landsdekkende)")

    # Line filter
    all_lines = sorted(df_master["lineName"].dropna().unique().tolist()) if "lineName" in df_master.columns else []
    selected_line = st.sidebar.selectbox(
        "Velg linje / rute",
        options=["— Alle ruter —"] + all_lines,
        index=0,
        key="main_line_filter",
    )

    if selected_line != "— Alle ruter —":
        df_nat = df_master[df_master["lineName"] == selected_line].copy()
    else:
        df_nat = df_master.copy()

    # Station filter
    all_stations = sorted(df_nat["stationName"].dropna().unique().tolist()) if "stationName" in df_nat.columns else []
    selected_station = st.sidebar.selectbox(
        "Filtrer på stasjon",
        options=["— Alle stasjoner —"] + all_stations,
        index=0,
        key="main_station_filter",
    )

    if selected_station != "— Alle stasjoner —":
        df_nat = df_nat[df_nat["stationName"] == selected_station].copy()

    # Transport mode filter
    all_modes = sorted(df_nat["transportMode"].dropna().unique().tolist()) if "transportMode" in df_nat.columns else []
    selected_modes = st.sidebar.multiselect(
        "Transporttype",
        options=all_modes,
        default=all_modes,
        key="main_mode_filter",
    )
    if selected_modes and "transportMode" in df_nat.columns:
        df_nat = df_nat[df_nat["transportMode"].isin(selected_modes)]

    only_delayed = st.sidebar.checkbox("Vis kun forsinkede", value=False, key="main_only_delayed")
    if only_delayed and "isDelayed" in df_nat.columns:
        df_nat = df_nat[df_nat["isDelayed"] == 1]

    # --- KPIs ---
    kpi_cols = st.columns(4)
    with kpi_cols[0]:
        st.metric("Totale avganger", f"{len(df_nat):,}".replace(",", " "))
    with kpi_cols[1]:
        delayed_n = int(df_nat["isDelayed"].sum()) if "isDelayed" in df_nat.columns else 0
        pct = (100 * delayed_n / len(df_nat)) if len(df_nat) > 0 else 0
        st.metric("Forsinkede", f"{delayed_n:,} ({pct:.0f}%)".replace(",", " "))
    with kpi_cols[2]:
        avg_d = df_nat["delaySeconds"].mean() / 60 if len(df_nat) > 0 else 0
        st.metric("Snitt forsinkelse", f"{avg_d:.1f} min")
    with kpi_cols[3]:
        total_delay_min = df_nat["delaySeconds"].sum() / 60 if len(df_nat) > 0 else 0
        if total_delay_min > 60:
            st.metric("Total forsinkelse", f"{total_delay_min / 60:.0f} timer")
        else:
            st.metric("Total forsinkelse", f"{total_delay_min:.0f} min")

    # ─── Totale forsinkelsesminutter per dag ───
    st.markdown("---")
    st.subheader("📈 Totale forsinkelsesminutter per dag")

    if not df_nat.empty and "scheduledDeparture" in df_nat.columns:
        df_daily = df_nat.dropna(subset=["scheduledDeparture"]).copy()
        df_daily["date"] = df_daily["scheduledDeparture"].dt.date

        daily_stats = (
            df_daily.groupby("date")
            .agg(
                totalDelayMin=("delaySeconds", lambda x: x.sum() / 60),
                avgDelayMin=("delaySeconds", lambda x: x.mean() / 60),
                departures=("isDelayed", "count"),
                delayed=("isDelayed", "sum"),
            )
            .reset_index()
        )

        daily_stats["date"] = pd.to_datetime(daily_stats["date"])
        daily_stats = daily_stats.set_index("date").sort_index()

        # Main chart: total delay minutes per day
        chart_col = daily_stats[["totalDelayMin"]].rename(
            columns={"totalDelayMin": "Forsinkelsesminutter"}
        )
        st.line_chart(chart_col)

        # Additional detail: daily stats table
        with st.expander("📋 Daglig statistikk (tabell)", expanded=False):
            daily_display = daily_stats.copy()
            daily_display.columns = [
                "Totale forsinkelsesmin",
                "Snitt forsinkelse (min)",
                "Antall avganger",
                "Antall forsinkede",
            ]
            daily_display["Totale forsinkelsesmin"] = daily_display["Totale forsinkelsesmin"].round(0)
            daily_display["Snitt forsinkelse (min)"] = daily_display["Snitt forsinkelse (min)"].round(2)
            st.dataframe(daily_display, use_container_width=True)
    else:
        st.info("Ingen data tilgjengelig for å vise daglig statistikk.")

    # ─── Full data table ───
    st.markdown("---")
    st.subheader("📋 Alle forsinkelser (landsdekkende)")

    display_cols = [
        "stationName", "destination", "lineName", "lineCode",
        "transportMode", "scheduledDeparture", "delaySeconds", "isDelayed",
    ]
    existing_cols = [c for c in display_cols if c in df_nat.columns]
    df_nat_table = df_nat[existing_cols].sort_values("scheduledDeparture", ascending=False)

    col_labels = {
        "stationName": "Stasjon",
        "destination": "Destinasjon",
        "lineName": "Linje",
        "lineCode": "Kode",
        "transportMode": "Type",
        "scheduledDeparture": "Planlagt avgang",
        "delaySeconds": "Forsinkelse (s)",
        "isDelayed": "Forsinket",
    }
    df_nat_table = df_nat_table.rename(columns=col_labels)
    st.dataframe(df_nat_table, use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════
# SECTION 2: Sandvika-specific data (legacy, collapsed)
# ═════════════════════════════════════════════════════════════

st.markdown("---")

with st.expander("🚉 Sandvika-spesifikke data (Oslo S → Sandvika)", expanded=False):
    if df_sandvika.empty:
        st.info("Ingen Sandvika-data å vise ennå.")
    else:
        # --- Sidebar filters (in expander scope) ---
        st.markdown("##### Filtre for Sandvika-data")

        time_range = st.selectbox(
            "Tidsperiode",
            ["Siste 24 timer", "Siste 7 dager", "Siste 30 dager", "Alle"],
            index=2,
            key="sv_time",
        )

        if time_range == "Siste 24 timer":
            df_time = df_sandvika[df_sandvika["scheduledDeparture"] >= (now_oslo - timedelta(hours=24))]
        elif time_range == "Siste 7 dager":
            df_time = df_sandvika[df_sandvika["scheduledDeparture"] >= (now_oslo - timedelta(days=7))]
        elif time_range == "Siste 30 dager":
            df_time = df_sandvika[df_sandvika["scheduledDeparture"] >= (now_oslo - timedelta(days=30))]
        else:
            df_time = df_sandvika

        destinations = sorted(df_time["destination"].dropna().unique().tolist()) if "destination" in df_time.columns else []
        selected_destinations = st.multiselect(
            "Slutt-destinasjon", destinations, default=destinations, key="sv_dest")

        route_names = sorted(df_time["routeName"].fillna("NA").unique().tolist())

        df_filtered = df_time.copy()
        if selected_destinations:
            df_filtered = df_filtered[df_filtered["destination"].isin(selected_destinations)]

        # KPIs
        sv_kpi = st.columns(3)
        with sv_kpi[0]:
            st.metric("Totale avganger", int(len(df_filtered)))
        with sv_kpi[1]:
            st.metric(
                "Forsinkede tog",
                int(df_filtered["isDelayed"].sum()) if "isDelayed" in df_filtered.columns else 0,
            )
        with sv_kpi[2]:
            avg_delay = df_filtered["delaySeconds"].mean() / 60 if "delaySeconds" in df_filtered.columns and len(df_filtered) > 0 else 0
            st.metric("Snitt forsinkelse", f"{avg_delay:.1f} min")

        # Bar chart
        st.markdown("**Gjennomsnittlig forsinkelse per slutt-destinasjon**")
        if not df_filtered.empty and "delaySeconds" in df_filtered.columns:
            chart_data = (
                df_filtered.groupby("destination")["delaySeconds"].mean() / 60
            ).sort_values(ascending=False)
            st.bar_chart(chart_data)

        # Historical punctuality
        st.markdown("**Historisk punktlighet per rute (Oslo → slutt-destinasjon)**")

        route_end = st.selectbox(
            "Velg slutt-destinasjon",
            destinations if destinations else ["NA"],
            key="sv_route_end",
        )
        metric = st.selectbox(
            "Måltall",
            ["Snittforsinkelse (min)", "Andel forsinket (%)"],
            key="sv_metric",
        )
        granularity = st.selectbox("Oppløsning", ["Dag", "Uke", "Måned"], key="sv_gran")

        df_route = df_time.copy()
        if route_end != "NA" and "destination" in df_route.columns:
            df_route = df_route[df_route["destination"] == route_end]

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

        # Table
        st.markdown("**Avganger fra Oslo (tog som forventes å passere Sandvika)**")

        columns_for_table = [
            "scheduledDeparture", "destination", "routeName", "routeId",
            "serviceJourneyId", "transportMode", "delaySeconds", "isDelayed",
            "actualDeparture",
        ]

        df_sv_table = df_filtered.copy()
        for col in columns_for_table:
            if col not in df_sv_table.columns:
                df_sv_table[col] = pd.NA

        df_sv_table = df_sv_table[columns_for_table].sort_values(
            by="scheduledDeparture", ascending=False)

        for col in ["routeName", "routeId", "serviceJourneyId", "transportMode"]:
            df_sv_table[col] = df_sv_table[col].fillna("NA")

        st.dataframe(df_sv_table, use_container_width=True)


# --- ENTUR RETNINGSLINJER OG KREDITERING ---
st.markdown("---")  # Lager en tynn, pen skillelinje

# Lager to kolonner slik at logoen og teksten står pent ved siden av hverandre
col_logo, col_text = st.columns([1, 5])

with col_logo:
    # Henter Entur-logoen direkte fra nettet (Wikimedia Commons for stabilitet)
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/e/e0/Entur_logo.svg",
        width=80)

with col_text:
    st.markdown("**Data gjort tilgjengelig av Entur**")
    st.caption(
        "Dataene publiseres under Norsk lisens for offentlige data (NLOD). "
        "Entur påtar seg intet ansvar for konsekvenser av feil i dataene eller API-systemene.")
