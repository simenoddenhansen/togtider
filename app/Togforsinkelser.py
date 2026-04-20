"""
Togforsinkelser – Hovedside / Dashboard
────────────────────────────────────────
National landing page with styled KPIs, Plotly interactive charts,
a temporal heatmap (hour × weekday), and trend delta indicators.
"""

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
    ACCENT_COLOR,
    DELAY_COLOR_SCALE,
    PLOTLY_TEMPLATE,
    WEEKDAY_NAMES,
    load_delay_data,
    master_csv_path,
    get_mtime,
    styled_kpi,
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
        cutoff = now_oslo - timedelta(hours=24)
        df = df[df["scheduledDeparture"] >= cutoff]
    elif selected_time == "Siste 7 dager":
        cutoff = now_oslo - timedelta(days=7)
        df = df[df["scheduledDeparture"] >= cutoff]
    elif selected_time == "Siste 30 dager":
        cutoff = now_oslo - timedelta(days=30)
        df = df[df["scheduledDeparture"] >= cutoff]

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
# KPIs with styled cards and delta indicators
# ═════════════════════════════════════════════════════════════════

st.markdown("---")

total_n = len(df)
delayed_n = int(df["isDelayed"].sum()) if "isDelayed" in df.columns else 0
pct_delayed = (100 * delayed_n / total_n) if total_n > 0 else 0
avg_delay_min = (df["delaySeconds"].mean() / 60) if total_n > 0 else 0
punctuality = 100 - pct_delayed

# Compute delta vs. previous equivalent period for context
delta_text = None
if "scheduledDeparture" in df_master.columns and selected_time != "Alle":
    period_map = {
        "Siste 24 timer": timedelta(hours=24),
        "Siste 7 dager": timedelta(days=7),
        "Siste 30 dager": timedelta(days=30),
    }
    period = period_map.get(selected_time, timedelta(days=30))
    prev_start = now_oslo - (period * 2)
    prev_end = now_oslo - period
    df_prev = df_master[
        (df_master["scheduledDeparture"] >= prev_start)
        & (df_master["scheduledDeparture"] < prev_end)
    ]
    if len(df_prev) > 0 and "isDelayed" in df_prev.columns:
        prev_pct = 100 * df_prev["isDelayed"].mean()
        prev_punct = 100 - prev_pct
        delta_punct = punctuality - prev_punct
        delta_text = f"{delta_punct:+.1f}pp"

kpi_cols = st.columns(4)
with kpi_cols[0]:
    styled_kpi("Totale avganger", f"{total_n:,}".replace(",", " "))
with kpi_cols[1]:
    styled_kpi(
        "Forsinkede",
        f"{delayed_n:,} ({pct_delayed:.0f}%)".replace(",", " "),
    )
with kpi_cols[2]:
    styled_kpi("Snitt forsinkelse", f"{avg_delay_min:.1f} min")
with kpi_cols[3]:
    emoji = "🟢" if punctuality >= 90 else ("🟡" if punctuality >= 75 else "🔴")
    styled_kpi(
        "Punktlighet",
        f"{emoji} {punctuality:.1f}%",
        delta=delta_text,
        delta_color="normal",
    )


# ═════════════════════════════════════════════════════════════════
# Punctuality per time period
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
            with col:
                styled_kpi(label, f"{emoji} {p:.1f}%", delta=f"{len(df_period)} avganger")
        else:
            with col:
                styled_kpi(label, "—", delta="Ingen data")


# ═════════════════════════════════════════════════════════════════
# Daily delay chart (Plotly interactive)
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
    daily_stats = daily_stats.sort_values("date")

    fig_daily = px.area(
        daily_stats,
        x="date",
        y="totalDelayMin",
        template=PLOTLY_TEMPLATE,
        labels={
            "date": "Dato",
            "totalDelayMin": "Forsinkelsesminutter",
        },
        color_discrete_sequence=[ACCENT_COLOR],
    )
    fig_daily.update_layout(
        hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
        height=350,
        yaxis_title="Forsinkelsesminutter",
        xaxis_title="",
    )
    fig_daily.update_traces(
        hovertemplate="<b>%{x|%d. %b %Y}</b><br>Forsinkelsesminutter: %{y:.0f}<extra></extra>"
    )
    st.plotly_chart(fig_daily, use_container_width=True)

    with st.expander("📋 Daglig statistikk (tabell)", expanded=False):
        daily_display = daily_stats.set_index("date").copy()
        daily_display.columns = [
            "Totale forsinkelsesmin",
            "Snitt forsinkelse (min)",
            "Antall avganger",
            "Antall forsinkede",
        ]
        daily_display["Totale forsinkelsesmin"] = daily_display[
            "Totale forsinkelsesmin"
        ].round(0)
        daily_display["Snitt forsinkelse (min)"] = daily_display[
            "Snitt forsinkelse (min)"
        ].round(2)
        st.dataframe(daily_display, use_container_width=True)
else:
    st.info("Ingen data tilgjengelig for å vise daglig statistikk.")


# ═════════════════════════════════════════════════════════════════
# Temporal heatmap: hour × weekday
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🔥 Forsinkelsesmønster — ukedag × time")
st.caption(
    "Heatmap som viser gjennomsnittlig forsinkelse per ukedag og time. "
    "Hjelper deg å identifisere rushtid-mønstre og problematiske perioder."
)

if not df.empty and "scheduledDeparture" in df.columns:
    df_heat = df.dropna(subset=["scheduledDeparture"]).copy()
    df_heat["hour"] = df_heat["scheduledDeparture"].dt.hour
    df_heat["weekday"] = df_heat["scheduledDeparture"].dt.weekday  # 0=Mon

    heat_agg = (
        df_heat.groupby(["weekday", "hour"])["delaySeconds"]
        .mean()
        .div(60)
        .reset_index()
    )
    heat_agg.columns = ["weekday", "hour", "avgDelayMin"]

    # Create a full 7×24 matrix
    heat_pivot = heat_agg.pivot(index="weekday", columns="hour", values="avgDelayMin")
    heat_pivot = heat_pivot.reindex(index=range(7), columns=range(24), fill_value=0)

    # Cap at 15 min for color clarity
    heat_values = heat_pivot.values.clip(0, 15)

    fig_heat = px.imshow(
        heat_values,
        x=[f"{h:02d}:00" for h in range(24)],
        y=WEEKDAY_NAMES,
        color_continuous_scale=DELAY_COLOR_SCALE,
        zmin=0,
        zmax=15,
        labels={"x": "Time", "y": "Ukedag", "color": "Snitt forsinkelse (min)"},
        template=PLOTLY_TEMPLATE,
        aspect="auto",
    )
    fig_heat.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=300,
        coloraxis_colorbar=dict(
            title="Min",
            tickvals=[0, 5, 10, 15],
            ticktext=["0", "5", "10", "15+"],
        ),
    )
    fig_heat.update_traces(
        hovertemplate="<b>%{y}, kl %{x}</b><br>Snitt forsinkelse: %{z:.1f} min<extra></extra>"
    )
    st.plotly_chart(fig_heat, use_container_width=True)
else:
    st.info("Ingen data tilgjengelig for heatmap.")


# ═════════════════════════════════════════════════════════════════
# Worst-performing lines (Plotly horizontal bar)
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
        .sort_values("avgDelay", ascending=True)
        .tail(10)
    )

    fig_lines = px.bar(
        line_stats.reset_index(),
        y="lineName",
        x="avgDelay",
        orientation="h",
        template=PLOTLY_TEMPLATE,
        labels={
            "lineName": "",
            "avgDelay": "Snitt forsinkelse (min)",
        },
        color="avgDelay",
        color_continuous_scale=DELAY_COLOR_SCALE,
        hover_data={
            "delayedPct": ":.1f",
            "totalDeps": True,
            "avgDelay": ":.1f",
        },
    )
    fig_lines.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=400,
        coloraxis_showscale=False,
        yaxis_title="",
        xaxis_title="Snitt forsinkelse (min)",
    )
    fig_lines.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Snitt forsinkelse: %{x:.1f} min<br>"
            "Andel forsinket: %{customdata[0]:.1f}%<br>"
            "Avganger: %{customdata[1]}<extra></extra>"
        )
    )
    st.plotly_chart(fig_lines, use_container_width=True)
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
