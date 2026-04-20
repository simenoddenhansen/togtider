"""
Togforsinkelser – Hovedside / Dashboard
────────────────────────────────────────
National landing page with KPIs, daily trend chart, worst-performing
lines, and a punctuality gauge.  Sidebar filters propagate via
session_state so they can be reused on sub-pages.
"""

import os
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    _HAS_AUTOREFRESH = True
except ModuleNotFoundError:
    _HAS_AUTOREFRESH = False
    def st_autorefresh(*args, **kwargs):
        return None

# Local shared helpers
from utils import (
    OSLO_TZ,
    COLUMN_LABELS,
    DISPLAY_COLUMNS,
    load_delay_data,
    load_stations,
    master_csv_path,
    stations_csv_path,
    get_mtime,
    download_csv_button,
    entur_footer,
)

# ─── Page config ──────────────────────────────────────────────────

st.set_page_config(
    page_title="Togforsinkelser",
    page_icon="🚆",
    layout="wide",
)

# Auto-refresh every minute for the countdown / fresh data
if _HAS_AUTOREFRESH:
    st_autorefresh(interval=60_000, key="countdown-refresh")

# ─── Load data ────────────────────────────────────────────────────

MASTER_PATH = master_csv_path()
master_mtime = get_mtime(MASTER_PATH)
now_oslo = datetime.now(OSLO_TZ)

df_master = load_delay_data(MASTER_PATH, master_mtime)

# ─── Hero section ─────────────────────────────────────────────────

st.title("🚆 Togforsinkelser i Norge")
st.markdown(
    "Automatisk innsamling av forsinkelsesdata fra norsk kollektivtransport via "
    "[Entur](https://entur.no). Dataene oppdateres hver time via GitHub Actions."
)

# Data freshness & countdown
if master_mtime is not None:
    last_updated = datetime.fromtimestamp(master_mtime, tz=OSLO_TZ)
    next_expected = last_updated + timedelta(hours=1)
    seconds_left = int((next_expected - now_oslo).total_seconds())

    remaining = max(0, seconds_left)
    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    countdown = (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        if hours
        else f"{minutes:02d}:{seconds:02d}"
    )

    status_cols = st.columns([2, 1])
    with status_cols[0]:
        st.caption(
            f"Sist oppdatert: {last_updated:%Y-%m-%d %H:%M:%S} (Europe/Oslo) · "
            f"Neste forventet: {next_expected:%Y-%m-%d %H:%M:%S}"
        )
    with status_cols[1]:
        label = (
            "Tid til neste forventede oppdatering"
            if seconds_left >= 0
            else "Forventet oppdatering (forsinket)"
        )
        st.metric(label, countdown)
else:
    st.info("Fant ikke datafilen ennå. Venter på første innsamling.")

if df_master.empty:
    st.warning("Ingen data tilgjengelig ennå – vent på neste scraper-kjøring.")
    entur_footer()
    st.stop()

# ─── Sidebar filters ─────────────────────────────────────────────

st.sidebar.header("🔎 Filtre")

# Time period filter
time_options = ["Siste 24 timer", "Siste 7 dager", "Siste 30 dager", "Alle"]
selected_time = st.sidebar.selectbox(
    "Tidsperiode",
    options=time_options,
    index=2,
    key="dash_time_filter",
)

df = df_master.copy()
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
    key="dash_line_filter",
)
if selected_line != "— Alle ruter —":
    df = df[df["lineName"] == selected_line]

# Station filter
all_stations = (
    sorted(df["stationName"].dropna().unique().tolist())
    if "stationName" in df.columns
    else []
)
selected_station = st.sidebar.selectbox(
    "Filtrer på stasjon",
    options=["— Alle stasjoner —"] + all_stations,
    index=0,
    key="dash_station_filter",
)
if selected_station != "— Alle stasjoner —":
    df = df[df["stationName"] == selected_station]

# Transport mode filter
all_modes = (
    sorted(df["transportMode"].dropna().unique().tolist())
    if "transportMode" in df.columns
    else []
)
selected_modes = st.sidebar.multiselect(
    "Transporttype",
    options=all_modes,
    default=all_modes,
    key="dash_mode_filter",
)
if selected_modes and "transportMode" in df.columns:
    df = df[df["transportMode"].isin(selected_modes)]

only_delayed = st.sidebar.checkbox(
    "Vis kun forsinkede", value=False, key="dash_only_delayed"
)
if only_delayed and "isDelayed" in df.columns:
    df = df[df["isDelayed"] == 1]


# ═════════════════════════════════════════════════════════════════
# KPIs
# ═════════════════════════════════════════════════════════════════

st.markdown("---")

kpi_cols = st.columns(4)

total_n = len(df)
delayed_n = int(df["isDelayed"].sum()) if "isDelayed" in df.columns else 0
pct_delayed = (100 * delayed_n / total_n) if total_n > 0 else 0
avg_delay_min = (df["delaySeconds"].mean() / 60) if total_n > 0 else 0
punctuality = 100 - pct_delayed

with kpi_cols[0]:
    st.metric("Totale avganger", f"{total_n:,}".replace(",", " "))
with kpi_cols[1]:
    st.metric("Forsinkede", f"{delayed_n:,} ({pct_delayed:.0f}%)".replace(",", " "))
with kpi_cols[2]:
    st.metric("Snitt forsinkelse", f"{avg_delay_min:.1f} min")
with kpi_cols[3]:
    emoji = "🟢" if punctuality >= 90 else ("🟡" if punctuality >= 75 else "🔴")
    st.metric("Punktlighet", f"{emoji} {punctuality:.0f}%")


# ═════════════════════════════════════════════════════════════════
# Punctuality over time periods
# ═════════════════════════════════════════════════════════════════

if "scheduledDeparture" in df_master.columns and not df_master.empty:
    st.markdown("---")
    st.subheader("📊 Punktlighet per tidsperiode")

    period_cols = st.columns(3)
    periods = [
        ("Siste 24 timer", timedelta(hours=24)),
        ("Siste 7 dager", timedelta(days=7)),
        ("Siste 30 dager", timedelta(days=30)),
    ]
    for col, (label, delta) in zip(period_cols, periods):
        df_period = df_master[df_master["scheduledDeparture"] >= (now_oslo - delta)]
        if len(df_period) > 0 and "isDelayed" in df_period.columns:
            p = 100 * (1 - df_period["isDelayed"].mean())
            emoji = "🟢" if p >= 90 else ("🟡" if p >= 75 else "🔴")
            col.metric(label, f"{emoji} {p:.1f}%", f"{len(df_period)} avganger")
        else:
            col.metric(label, "—", "Ingen data")


# ═════════════════════════════════════════════════════════════════
# Daily delay chart
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📈 Totale forsinkelsesminutter per dag")

if not df.empty and "scheduledDeparture" in df.columns:
    df_daily = df.dropna(subset=["scheduledDeparture"]).copy()
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

    chart_col = daily_stats[["totalDelayMin"]].rename(
        columns={"totalDelayMin": "Forsinkelsesminutter"}
    )
    st.line_chart(chart_col)

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


# ═════════════════════════════════════════════════════════════════
# Worst-performing lines
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🚨 Mest forsinkede linjer")

if not df.empty and "lineName" in df.columns:
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
        .head(10)
        .rename(
            columns={
                "avgDelay": "Snitt forsinkelse (min)",
                "delayedPct": "Andel forsinket (%)",
                "totalDeps": "Antall avganger",
            }
        )
    )
    line_stats["Snitt forsinkelse (min)"] = line_stats["Snitt forsinkelse (min)"].round(1)
    line_stats["Andel forsinket (%)"] = line_stats["Andel forsinket (%)"].round(1)
    st.dataframe(line_stats, use_container_width=True)
else:
    st.caption("Ingen linjedata tilgjengelig.")


# ═════════════════════════════════════════════════════════════════
# CSV download
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📥 Last ned data")
st.caption("Last ned det filtrerte datasettet som CSV for videre analyse.")
download_csv_button(df, prefix="togforsinkelser_dashboard")


# ═════════════════════════════════════════════════════════════════
# Footer
# ═════════════════════════════════════════════════════════════════

entur_footer()
