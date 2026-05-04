"""
Forsinkelseskart – Interaktivt kart over forsinkelser
─────────────────────────────────────────────────────
Interaktivt pydeck-kart med fargekodede stasjoner og rutelinjer,
Plotly interaktive grafer og detaljert tabell.
Filtrert til kun togdata (rail).
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import pydeck as pdk
import plotly.express as px
import streamlit as st

try:
    import folium
    from streamlit_folium import st_folium

    _HAS_FOLIUM = True
except ModuleNotFoundError:
    _HAS_FOLIUM = False

# Sørg for at app/-mappen er på path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_loader import (
    DEFAULT_RECENT_DAYS_MAP,
    MAP_COLUMNS,
    OSLO_TZ,
    load_delay_data,
    load_stations,
    master_csv_path,
    stations_csv_path,
    get_mtime,
    filter_rail_only,
)
from components.kpi import styled_kpi
from components.footer import entur_footer
from components.sidebar import render_sidebar_filters
from components.responsive_css import inject_responsive_css
from components.top_nav import render_top_nav
from utils import (
    ACCENT_COLOR,
    DELAY_COLOR_SCALE,
    PLOTLY_STATIC_CONFIG,
    PLOTLY_TEMPLATE,
    COLUMN_LABELS,
    DISPLAY_COLUMNS,
    delay_to_color,
    compute_zoom,
)


def _rgba_to_hex(color):
    return "#{:02x}{:02x}{:02x}".format(*color[:3])


def render_station_delay_map(df_map, center_lat, center_lng, zoom):
    """Rendrer kartet med Folium når tilgjengelig, ellers pydeck."""
    if _HAS_FOLIUM:
        delay_map = folium.Map(
            location=[center_lat, center_lng],
            zoom_start=zoom,
            tiles="CartoDB dark_matter",
            control_scale=True,
            prefer_canvas=True,
        )

        for row in df_map.itertuples(index=False):
            color = _rgba_to_hex(row.color)
            popup_html = (
                f"<strong>{row.name}</strong><br>"
                f"Snitt forsinkelse: <strong>{row.delayMin} min</strong><br>"
                f"Avganger: {row.count}"
            )
            folium.CircleMarker(
                location=[row.latitude, row.longitude],
                radius=6,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.82,
                weight=2,
                tooltip=str(row.name),
                popup=folium.Popup(popup_html, max_width=280),
            ).add_to(delay_map)

        st_folium(
            delay_map,
            height=680,
            use_container_width=True,
            returned_objects=[],
        )
        return

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_map.to_dict("records"),
        get_position=["longitude", "latitude"],
        get_fill_color="color",
        get_radius=800,
        radius_min_pixels=4,
        radius_max_pixels=15,
        pickable=True,
    )

    deck = pdk.Deck(
        layers=[scatter_layer],
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


def render_map_section(df, df_stations):
    """Rendrer hovedkartet for forsinkelser."""
    st.markdown("---")
    st.subheader("🗺️ Forsinkelseskart")

    if df.empty or df_stations.empty:
        st.info("Ingen data å vise på kart.")
        return

    station_delays = (
        df.groupby("stationId")
        .agg(avgDelay=("delaySeconds", "mean"), count=("isDelayed", "count"))
        .reset_index()
    )

    df_map = station_delays.merge(
        df_stations[["id", "name", "latitude", "longitude"]],
        left_on="stationId",
        right_on="id",
        how="inner",
    )

    if df_map.empty or "latitude" not in df_map.columns:
        st.info("Kunne ikke koble forsinkelsesdata med stasjonskart.")
        return

    df_map = df_map.dropna(subset=["latitude", "longitude"])
    if df_map.empty:
        st.info("Kunne ikke koble forsinkelsesdata med stasjonskart.")
        return

    max_delay_val = max(df_map["avgDelay"].max(), 1)
    df_map["color"] = df_map["avgDelay"].apply(
        lambda d: delay_to_color(d, max_delay_val)
    )
    df_map["delayMin"] = (df_map["avgDelay"] / 60).round(1)

    center_lat = df_map["latitude"].mean()
    center_lng = df_map["longitude"].mean()
    lat_spread = df_map["latitude"].max() - df_map["latitude"].min()
    lng_spread = df_map["longitude"].max() - df_map["longitude"].min()
    zoom = compute_zoom(lat_spread, lng_spread)

    render_station_delay_map(df_map, center_lat, center_lng, zoom)
    st.caption("🟢 Grønn = liten forsinkelse · 🟡 Gul = moderat · 🔴 Rød = stor forsinkelse")


# ─── Sidekonfigurasjon ────────────────────────────────────────────

st.set_page_config(
    page_title="Forsinkelseskart",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_responsive_css()
render_top_nav("Kart")

st.title("🗺️ Forsinkelseskart")
st.caption(
    "Interaktivt kart over forsinkelser på norske togstasjoner. "
    "Grønn = liten forsinkelse · Gul = moderat · Rød = stor forsinkelse."
)

# ─── Last data ────────────────────────────────────────────────────

MASTER_PATH = master_csv_path()
STATIONS_PATH = stations_csv_path()

master_mtime = get_mtime(MASTER_PATH)
now_oslo = datetime.now(OSLO_TZ)

df_all = load_delay_data(
    MASTER_PATH,
    master_mtime,
    days_back=DEFAULT_RECENT_DAYS_MAP,
    columns=MAP_COLUMNS,
)
df_stations = load_stations(STATIONS_PATH)

# Filtrer til kun tog (rail) på datanivå
df_all = filter_rail_only(df_all)

if df_all.empty:
    st.warning(
        "Ingen forsinkelsesdata funnet ennå. "
        "Kjør `python data_collection/forsinkelser_scraper.py` eller vent på neste GitHub Action-kjøring."
    )
    entur_footer()
    st.stop()


# ─── Sidebar-filtre (kun tog) ────────────────────────────────────

df, selected_route, selected_time = render_sidebar_filters(
    df_all, page_key="map", now_oslo=now_oslo
)


# ─── KPI-er ──────────────────────────────────────────────────────

st.markdown("---")

kpi_cols = st.columns(4)
total_n = len(df)
delayed_n = int(df["isDelayed"].sum()) if "isDelayed" in df.columns else 0
pct = (100 * delayed_n / total_n) if total_n > 0 else 0
avg_delay = (df["delaySeconds"].mean() / 60) if total_n > 0 else 0
max_delay = (df["delaySeconds"].max() / 60) if total_n > 0 else 0

with kpi_cols[0]:
    styled_kpi("Avganger", f"{total_n:,}".replace(",", " "))
with kpi_cols[1]:
    styled_kpi("Forsinkede", f"{delayed_n:,} ({pct:.0f}%)".replace(",", " "))
with kpi_cols[2]:
    styled_kpi("Snitt forsinkelse", f"{avg_delay:.1f} min")
with kpi_cols[3]:
    styled_kpi("Maks forsinkelse", f"{max_delay:.0f} min")


# ═════════════════════════════════════════════════════════════════
# KART (hovedopplevelse)
# ═════════════════════════════════════════════════════════════════

render_map_section(df, df_stations)


# ═════════════════════════════════════════════════════════════════
# FORSINKELSESFORDELING (Plotly interaktivt histogram)
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📊 Forsinkelsesfordeling")

if not df.empty and "delaySeconds" in df.columns:
    delay_min = df["delaySeconds"] / 60

    dist_left, dist_right = st.columns([2, 3])

    with dist_left:
        # Statistikk i stiliserte kort
        buckets = {
            "🟢 I rute (0 min)": (delay_min == 0).sum(),
            "🟢 < 1 min": ((delay_min > 0) & (delay_min < 1)).sum(),
            "🟡 1–5 min": ((delay_min >= 1) & (delay_min < 5)).sum(),
            "🟠 5–15 min": ((delay_min >= 5) & (delay_min < 15)).sum(),
            "🔴 15–30 min": ((delay_min >= 15) & (delay_min < 30)).sum(),
            "🔴 30+ min": (delay_min >= 30).sum(),
        }

        st.markdown("**Antall avganger per forsinkelsesgruppe:**")
        for label, count in buckets.items():
            pct_bucket = (100 * count / total_n) if total_n > 0 else 0
            st.markdown(f"{label}: **{count:,}** ({pct_bucket:.1f}%)")

        on_time = list(buckets.values())[0] + list(buckets.values())[1]
        on_time_pct = (100 * on_time / total_n) if total_n > 0 else 0
        st.markdown(f"\n**Punktlighet (< 1 min):** {on_time_pct:.1f}%")

    with dist_right:
        # Interaktivt Plotly-histogram
        df_hist = df[["delaySeconds"]].copy()
        df_hist["delayMin"] = df_hist["delaySeconds"] / 60

        # Begrens til 30 min for renere visualisering
        df_hist["delayMin_capped"] = df_hist["delayMin"].clip(upper=30)

        fig_hist = px.histogram(
            df_hist,
            x="delayMin_capped",
            nbins=30,
            template=PLOTLY_TEMPLATE,
            labels={"delayMin_capped": "Forsinkelse (min)"},
            color_discrete_sequence=[ACCENT_COLOR],
        )
        fig_hist.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            height=300,
            xaxis_title="Forsinkelse (min, maks 30)",
            yaxis_title="Antall avganger",
            bargap=0.05,
        )
        fig_hist.update_traces(
            hovertemplate="Forsinkelse: %{x:.1f} min<br>Antall: %{y}<extra></extra>"
        )
        st.plotly_chart(fig_hist, use_container_width=True, config=PLOTLY_STATIC_CONFIG)

else:
    st.info("Ingen forsinkelsesdata tilgjengelig for å vise fordeling.")


# ═════════════════════════════════════════════════════════════════
# FORSINKELSE PER TIME (døgnmønster)
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("⏰ Forsinkelse per time (døgnmønster)")

if not df.empty and "scheduledDeparture" in df.columns:
    df_hourly = df.dropna(subset=["scheduledDeparture"]).copy()
    df_hourly["hour"] = df_hourly["scheduledDeparture"].dt.hour

    hourly_stats = (
        df_hourly.groupby("hour")
        .agg(
            avgDelay=("delaySeconds", lambda x: x.mean() / 60),
            count=("isDelayed", "count"),
        )
        .reindex(range(24), fill_value=0)
        .reset_index()
    )
    hourly_stats.columns = ["hour", "avgDelay", "count"]

    fig_hourly = px.bar(
        hourly_stats,
        x="hour",
        y="avgDelay",
        template=PLOTLY_TEMPLATE,
        labels={"hour": "Time", "avgDelay": "Snitt forsinkelse (min)"},
        color="avgDelay",
        color_continuous_scale=DELAY_COLOR_SCALE,
    )
    fig_hourly.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=280,
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(24)),
            ticktext=[f"{h:02d}" for h in range(24)],
        ),
        coloraxis_showscale=False,
        yaxis_title="Snitt forsinkelse (min)",
        xaxis_title="Time på døgnet",
    )
    fig_hourly.update_traces(
        hovertemplate="<b>Kl %{x}:00</b><br>Snitt: %{y:.1f} min<br>Avganger: %{customdata[0]}<extra></extra>",
        customdata=hourly_stats[["count"]].values,
    )
    st.plotly_chart(fig_hourly, use_container_width=True, config=PLOTLY_STATIC_CONFIG)
else:
    st.info("Ingen data tilgjengelig.")


# ═════════════════════════════════════════════════════════════════
# Stolpediagrammer (Plotly interaktive, side ved side)
# ═════════════════════════════════════════════════════════════════

st.markdown("---")

chart_left, chart_right = st.columns(2)

with chart_left:
    st.subheader("⏱️ Mest forsinkede stasjoner")
    if not df.empty and "delaySeconds" in df.columns:
        station_stats = (
            df.groupby("stationName")["delaySeconds"]
            .mean()
            .div(60)
            .sort_values(ascending=True)
            .tail(10)
            .reset_index()
        )
        station_stats.columns = ["stationName", "avgDelay"]

        if not station_stats.empty:
            fig_stations = px.bar(
                station_stats,
                y="stationName",
                x="avgDelay",
                orientation="h",
                template=PLOTLY_TEMPLATE,
                labels={"stationName": "", "avgDelay": "Snitt forsinkelse (min)"},
                color="avgDelay",
                color_continuous_scale=DELAY_COLOR_SCALE,
            )
            fig_stations.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                height=350,
                coloraxis_showscale=False,
                yaxis_title="",
            )
            fig_stations.update_traces(
                hovertemplate="<b>%{y}</b><br>Snitt: %{x:.1f} min<extra></extra>"
            )
            st.plotly_chart(fig_stations, use_container_width=True, config=PLOTLY_STATIC_CONFIG)
        else:
            st.info("Ingen data å vise.")
    else:
        st.info("Ingen data å vise.")

with chart_right:
    st.subheader("🚆 Mest forsinkede linjer")
    if not df.empty and "lineName" in df.columns:
        line_stats = (
            df.groupby("lineName")["delaySeconds"]
            .mean()
            .div(60)
            .sort_values(ascending=True)
            .tail(10)
            .reset_index()
        )
        line_stats.columns = ["lineName", "avgDelay"]

        if not line_stats.empty:
            fig_lines = px.bar(
                line_stats,
                y="lineName",
                x="avgDelay",
                orientation="h",
                template=PLOTLY_TEMPLATE,
                labels={"lineName": "", "avgDelay": "Snitt forsinkelse (min)"},
                color="avgDelay",
                color_continuous_scale=DELAY_COLOR_SCALE,
            )
            fig_lines.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                height=350,
                coloraxis_showscale=False,
                yaxis_title="",
            )
            fig_lines.update_traces(
                hovertemplate="<b>%{y}</b><br>Snitt: %{x:.1f} min<extra></extra>"
            )
            st.plotly_chart(fig_lines, use_container_width=True, config=PLOTLY_STATIC_CONFIG)
        else:
            st.info("Ingen data å vise.")
    else:
        st.info("Ingen data å vise.")


# ═════════════════════════════════════════════════════════════════
# Detaljert tabell
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
# Footer
# ═════════════════════════════════════════════════════════════════

entur_footer()
