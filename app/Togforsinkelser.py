"""
Togforsinkelser – Hovedside / Dashboard
────────────────────────────────────────
Nasjonal landingsside med KPI-kort, Plotly interaktive grafer,
tidsheatmap (time × ukedag) med Viridis-fargeskala,
rutefiltrering, uteliggerdeteksjon og trendindikator.
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


# Lokale delte moduler
from data_loader import (
    DASHBOARD_COLUMNS,
    DEFAULT_RECENT_DAYS_DASHBOARD,
    OSLO_TZ,
    load_delay_data,
    master_csv_path,
    get_mtime,
    get_last_scraped_at,
    filter_rail_only,
)
from components.kpi import styled_kpi
from components.footer import entur_footer
from components.sidebar import apply_time_filter
from components.responsive_css import inject_responsive_css
from components.top_nav import render_top_nav
from schedule_utils import SCRAPE_INTERVAL_MINUTES, get_next_scheduled_update
from utils import (
    ACCENT_COLOR,
    DELAY_COLOR_SCALE,
    HEATMAP_COLOR_SCALE,
    PLOTLY_STATIC_CONFIG,
    PLOTLY_TEMPLATE,
    WEEKDAY_NAMES,
)

# ─── Sidekonfigurasjon ────────────────────────────────────────────

st.set_page_config(
    page_title="Togforsinkelser",
    page_icon="🚆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_responsive_css()
render_top_nav("Oversikt")

# Auto-refresh hvert minutt for nedtelling / ferske data
if _HAS_AUTOREFRESH:
    st_autorefresh(interval=60_000, key="countdown-refresh")

# ─── Last data ────────────────────────────────────────────────────

MASTER_PATH = master_csv_path()
master_mtime = get_mtime(MASTER_PATH)
now_oslo = datetime.now(OSLO_TZ)

df_master = load_delay_data(
    MASTER_PATH,
    master_mtime,
    days_back=DEFAULT_RECENT_DAYS_DASHBOARD,
    columns=DASHBOARD_COLUMNS,
)

# Filtrer til kun tog (rail) på datanivå
df_master = filter_rail_only(df_master)

# ─── Hero-seksjon ─────────────────────────────────────────────────

st.title("🚆 Togforsinkelser i Norge")
st.markdown(
    "Automatisk innsamling av forsinkelsesdata for **norsk jernbane** via "
    "[Entur](https://entur.no). Dataene oppdateres omtrent hvert "
    f"**{SCRAPE_INTERVAL_MINUTES}. minutt** via GitHub Actions."
)

# Dataferskhet & nedtelling
if master_mtime is not None:
    last_scraped_at = get_last_scraped_at(MASTER_PATH)
    last_updated = last_scraped_at or datetime.fromtimestamp(master_mtime, tz=OSLO_TZ)
    next_expected = get_next_scheduled_update(last_updated)
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
            "Tid til neste planlagte oppdatering"
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

df = df_master
selected_route = None
selected_time = "Alle"

# ─── Visningsindikator ───────────────────────────────────────────

if selected_route is not None:
    st.info(f"📍 Viser statistikk for: **{selected_route}**")
else:
    st.info("📊 Viser aggregerte tall for **hele tognettet** (alle ruter)")


# ═════════════════════════════════════════════════════════════════
# KPI-er med stiliserte kort og deltaindikatorer
# ═════════════════════════════════════════════════════════════════

st.markdown("---")

# KPI-terskler
DELAY_KPI_THRESHOLD_SECONDS = 180   # Forsinket = mer enn 3 min
PUNCTUALITY_THRESHOLD_SECONDS = 60  # Punktlig = under 1 min

# Norske månedsforkortelser for caption-tekst.
_NO_MND = [
    "jan", "feb", "mar", "apr", "mai", "jun",
    "jul", "aug", "sep", "okt", "nov", "des",
]

# KPI-ene viser hele lastet historikk (uavhengig av sidebar-tidsfilter)
# slik at alle fire kortene refererer samme tidsspenn. Sidebar-rutevalget
# respekteres fortsatt for å støtte drill-down på enkeltlinjer.
df_kpi = df_master
if selected_route is not None and "lineName" in df_kpi.columns:
    df_kpi = df_kpi[df_kpi["lineName"] == selected_route]

# Tidligste dato i lastet datasett — "max dato tilbake".
data_start_date = None
if "scheduledDeparture" in df_kpi.columns and not df_kpi.empty:
    earliest_ts = df_kpi["scheduledDeparture"].min()
    if pd.notna(earliest_ts):
        data_start_date = earliest_ts.date()

if data_start_date is not None:
    since_caption = (
        f"Siden {data_start_date.day}. "
        f"{_NO_MND[data_start_date.month - 1]} {data_start_date.year}"
    )
else:
    since_caption = "Siden start"

total_n = len(df_kpi)
severely_delayed_n = (
    int((df_kpi["delaySeconds"] > DELAY_KPI_THRESHOLD_SECONDS).sum())
    if "delaySeconds" in df_kpi.columns
    else 0
)
pct_severely_delayed = (100 * severely_delayed_n / total_n) if total_n > 0 else 0
avg_delay_min = (df_kpi["delaySeconds"].mean() / 60) if total_n > 0 else 0
on_time_n = (
    int((df_kpi["delaySeconds"] < PUNCTUALITY_THRESHOLD_SECONDS).sum())
    if "delaySeconds" in df_kpi.columns
    else 0
)
punctuality = (100 * on_time_n / total_n) if total_n > 0 else 0

kpi_cols = st.columns(4)
with kpi_cols[0]:
    styled_kpi(
        "Totale togavganger",
        f"{total_n:,}".replace(",", " "),
        caption=since_caption,
    )
with kpi_cols[1]:
    styled_kpi(
        "Andel forsinkede (>3 min)",
        f"{severely_delayed_n:,} ({pct_severely_delayed:.0f}%)".replace(",", " "),
        caption=since_caption,
    )
with kpi_cols[2]:
    styled_kpi(
        "Snitt forsinkelse",
        f"{avg_delay_min:.1f} min",
        caption=since_caption,
    )
with kpi_cols[3]:
    emoji = "🟢" if punctuality >= 90 else ("🟡" if punctuality >= 75 else "🔴")
    styled_kpi(
        "Punktlighet",
        f"{emoji} {punctuality:.1f}%",
        caption="< 1 min forsinkelse",
    )


# ═════════════════════════════════════════════════════════════════
# Punktlighet per tidsperiode
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
        # Filtrer på valgt rute hvis relevant
        if selected_route is not None and "lineName" in df_period.columns:
            df_period = df_period[df_period["lineName"] == selected_route]

        if len(df_period) > 0 and "isDelayed" in df_period.columns:
            p = 100 * (1 - df_period["isDelayed"].mean())
            emoji = "🟢" if p >= 90 else ("🟡" if p >= 75 else "🔴")
            with col:
                styled_kpi(label, f"{emoji} {p:.1f}%", delta=f"{len(df_period)} avganger")
        else:
            with col:
                styled_kpi(label, "—", delta="Ingen data")


# ═════════════════════════════════════════════════════════════════
# Daglig forsinkelsesdiagram (Plotly interaktivt)
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
        dragmode=False,
        margin=dict(l=0, r=0, t=10, b=0),
        height=350,
        yaxis_title="Forsinkelsesminutter",
        xaxis_title="",
    )
    fig_daily.update_traces(
        hovertemplate="<b>%{x|%d. %b %Y}</b><br>Forsinkelsesminutter: %{y:.0f}<extra></extra>"
    )
    st.plotly_chart(fig_daily, use_container_width=True, config=PLOTLY_STATIC_CONFIG)

    # ─── Daglig statistikk-tabell med uteliggerdeteksjon ─────────

    with st.expander("📋 Daglig statistikk (tabell)", expanded=False):

        daily_display = daily_stats.copy()
        daily_display["totalDelayMin"] = daily_display["totalDelayMin"].round(0)
        daily_display["avgDelayMin"] = daily_display["avgDelayMin"].round(2)

        # ── Uteliggerdeteksjon (IQR-metoden) ──
        # IQR er robust for skjeve fordelinger (forsinkelsesdata er typisk
        # høyreskjeve med mange ~0 og noen ekstreme verdier).
        col_for_outlier = "avgDelayMin"
        Q1 = daily_display[col_for_outlier].quantile(0.25)
        Q3 = daily_display[col_for_outlier].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        median_val = daily_display[col_for_outlier].median()

        daily_display["is_outlier"] = (
            (daily_display[col_for_outlier] < lower_bound)
            | (daily_display[col_for_outlier] > upper_bound)
        )
        daily_display["Uteligger"] = daily_display["is_outlier"].map(
            {True: "🔴 Uteligger", False: "✅ Normal"}
        )
        daily_display["Avvik fra median (min)"] = (
            daily_display[col_for_outlier] - median_val
        ).round(2)

        # ── Vis uteligger-seksjon ──
        outlier_rows = daily_display[daily_display["is_outlier"]]

        if not outlier_rows.empty:
            st.warning(f"⚠️ **{len(outlier_rows)} dag(er) skjevdeler gjennomsnittet**")
            st.markdown(
                "Følgende dager har uvanlig høy eller lav gjennomsnittsforsinkelse "
                f"(utenfor IQR-grensene: {lower_bound:.1f} – {upper_bound:.1f} min):"
            )

            outlier_info = outlier_rows[
                ["date", "avgDelayMin", "Avvik fra median (min)", "departures"]
            ].copy()
            outlier_info.columns = [
                "Dato", "Snitt forsinkelse (min)", "Avvik fra median (min)", "Avganger"
            ]
            outlier_info["Dato"] = outlier_info["Dato"].dt.strftime("%Y-%m-%d")
            st.dataframe(outlier_info, use_container_width=True, hide_index=True)
        else:
            st.info("✅ Ingen uteliggere identifisert i denne perioden — forsinkelsene er jevnt fordelt.")

        # ── Vis full tabell ──
        st.markdown("##### Komplett daglig oversikt")
        table_display = daily_display[
            ["date", "totalDelayMin", "avgDelayMin", "departures", "delayed", "Uteligger"]
        ].copy()
        table_display.columns = [
            "Dato",
            "Totale forsinkelsesmin",
            "Snitt forsinkelse (min)",
            "Antall avganger",
            "Antall forsinkede",
            "Uteligger",
        ]
        table_display["Dato"] = table_display["Dato"].dt.strftime("%Y-%m-%d")
        table_display = table_display.sort_values("Dato", ascending=False)
        st.dataframe(table_display, use_container_width=True, hide_index=True)

else:
    st.info("Ingen data tilgjengelig for å vise daglig statistikk.")


# ═════════════════════════════════════════════════════════════════
# Tidsheatmap: time × ukedag (Viridis — fargeblindevennlig)
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
route_label = selected_route if selected_route else "Alle ruter (aggregert)"
st.subheader(f"🔥 Forsinkelsesmønster — ukedag × time")
st.caption(
    f"Viser: **{route_label}** · "
    "Heatmap med gjennomsnittlig forsinkelse per ukedag og time. "
    "Hjelper deg å identifisere rushtid-mønstre og problematiske perioder. "
    "Fargeskala: Viridis (fargeblindevennlig)."
)

if not df.empty and "scheduledDeparture" in df.columns:
    df_heat = df.dropna(subset=["scheduledDeparture"]).copy()
    df_heat["hour"] = df_heat["scheduledDeparture"].dt.hour
    df_heat["weekday"] = df_heat["scheduledDeparture"].dt.weekday  # 0=Man

    heat_agg = (
        df_heat.groupby(["weekday", "hour"])["delaySeconds"]
        .mean()
        .div(60)
        .reset_index()
    )
    heat_agg.columns = ["weekday", "hour", "avgDelayMin"]

    # Opprett en full 7×24 matrise
    heat_pivot = heat_agg.pivot(index="weekday", columns="hour", values="avgDelayMin")
    heat_pivot = heat_pivot.reindex(index=range(7), columns=range(24), fill_value=0)

    # Begrens til 15 min for fargeklarthet
    heat_values = heat_pivot.values.clip(0, 15)

    fig_heat = px.imshow(
        heat_values,
        x=[f"{h:02d}:00" for h in range(24)],
        y=WEEKDAY_NAMES,
        color_continuous_scale=HEATMAP_COLOR_SCALE,
        zmin=0,
        zmax=15,
        labels={"x": "Time", "y": "Ukedag", "color": "Snitt forsinkelse (min)"},
        template=PLOTLY_TEMPLATE,
        aspect="auto",
    )
    fig_heat.update_layout(
        dragmode=False,
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
    st.plotly_chart(fig_heat, use_container_width=True, config=PLOTLY_STATIC_CONFIG)
else:
    st.info("Ingen data tilgjengelig for heatmap.")


# ═════════════════════════════════════════════════════════════════
# Mest forsinkede linjer (Plotly horisontalt stolpediagram)
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🚨 Mest forsinkede linjer")

# Lokalt tidsvindu for denne grafen (overstyrer sidebar-tidsfilter).
# "Maks tid" tilsvarer alle data som er lastet inn (opptil
# DEFAULT_RECENT_DAYS_DASHBOARD dager tilbake).
LINES_CHART_TIME_OPTIONS = [
    "Siste 24 timer",
    "Siste 7 dager",
    "Siste 30 dager",
    "Maks tid",
]
lines_chart_time = st.segmented_control(
    "Tidsperiode for grafen",
    options=LINES_CHART_TIME_OPTIONS,
    default="Siste 7 dager",
    key="dash_lines_time",
    label_visibility="collapsed",
)
if lines_chart_time is None:
    lines_chart_time = "Siste 7 dager"

# Bygg datasettet fra df_master slik at grafen kan vise data utover
# sidebar-tidsfilteret. Sidebar-rutevalget respekteres fortsatt.
df_lines = apply_time_filter(df_master, lines_chart_time, now_oslo)
if selected_route is not None and "lineName" in df_lines.columns:
    df_lines = df_lines[df_lines["lineName"] == selected_route]

if not df_lines.empty and "lineName" in df_lines.columns:
    line_stats = (
        df_lines.groupby("lineName", observed=True)
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
        dragmode=False,
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
    st.plotly_chart(fig_lines, use_container_width=True, config=PLOTLY_STATIC_CONFIG)
else:
    st.caption("Ingen linjedata tilgjengelig for valgt tidsvindu.")


# ═════════════════════════════════════════════════════════════════
# Nedlastingslenke (navigerer til dedikert side)
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📥 Last ned data")
st.caption(
    "Bruk den dedikerte nedlastingssiden for å velge kolonner, "
    "tidsperiode, ruter og filformat."
)
st.page_link(
    "pages/2_📥_Last_ned_data.py",
    label="📥 Gå til nedlastingssiden",
    icon="📥",
)


# ═════════════════════════════════════════════════════════════════
# Footer
# ═════════════════════════════════════════════════════════════════

entur_footer()
