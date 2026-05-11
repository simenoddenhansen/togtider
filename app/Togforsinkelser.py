"""
Togforsinkelser i Norge – Landingsside (Forsinkelseskart)
─────────────────────────────────────────────────────────
Interaktivt kart over forsinkelser på norske togstasjoner (Folium/pydeck),
med situasjonsmeldinger, fordelingsdiagrammer og detaljert tabell.
Filtrert til kun togdata (rail). Data fra Entur (NLOD 2.0).
"""

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
from components.footer import entur_footer
from components.sidebar import apply_time_filter

from components.responsive_css import inject_responsive_css
from components.top_nav import render_top_nav
from utils import (
    ACCENT_COLOR,
    DELAY_COLOR_SCALE,
    MAP_DELAY_LEGEND,
    PLOTLY_STATIC_CONFIG,
    PLOTLY_TEMPLATE,
    COLUMN_LABELS,
    DISPLAY_COLUMNS,
    delay_to_color,
    compute_zoom,
)


def _rgba_to_hex(color):
    return "#{:02x}{:02x}{:02x}".format(*color[:3])


# Minste antall avganger for at en linje skal kunne bli «verstinglinje»
# på en stasjon – hindrer at en linje med svært få avganger dominerer.
_MIN_DEPARTURES_FOR_WORST_LINE = 5


def _format_min_sec(seconds):
    """Formatterer et sekundtall som «Xmin Y sek»."""
    total = max(0, int(round(float(seconds or 0))))
    minutes, secs = divmod(total, 60)
    return f"{minutes}min {secs} sek"


def compute_worst_line_per_station(df):
    """Per stasjon: linjen med høyest andel forsinkede avganger.

    Returnerer {stationId: {"lineName": str, "share": float, "avgSec": float}}.
    """
    if df.empty or "lineName" not in df.columns or "stationId" not in df.columns:
        return {}

    work = df.copy()
    work["lineName"] = work["lineName"].astype("object").fillna("").astype(str).str.strip()
    work = work[work["lineName"] != ""]
    if work.empty:
        return {}

    if "isDelayed" in work.columns:
        work["_delayed"] = pd.to_numeric(work["isDelayed"], errors="coerce").fillna(0)
    elif "delaySeconds" in work.columns:
        work["_delayed"] = (
            pd.to_numeric(work["delaySeconds"], errors="coerce").fillna(0) > 0
        ).astype(int)
    else:
        return {}

    if "delaySeconds" in work.columns:
        work["_delaySec"] = pd.to_numeric(work["delaySeconds"], errors="coerce").fillna(0)
    else:
        work["_delaySec"] = 0.0

    grouped = (
        work.groupby(["stationId", "lineName"], observed=True)
        .agg(n=("_delayed", "size"), share=("_delayed", "mean"), avgSec=("_delaySec", "mean"))
        .reset_index()
    )

    result = {}
    for station_id, sub in grouped.groupby("stationId", observed=True):
        candidates = sub[sub["n"] >= _MIN_DEPARTURES_FOR_WORST_LINE]
        if candidates.empty:
            candidates = sub
        top = candidates.sort_values(["share", "avgSec"], ascending=False).iloc[0]
        result[station_id] = {
            "lineName": str(top["lineName"]),
            "share": float(top["share"]),
            "avgSec": float(top["avgSec"]),
        }
    return result


def _worst_line_html(info):
    """HTML-fragment for verstinglinjen (tom streng hvis ingen)."""
    if not info or not info.get("lineName"):
        return ""
    label = f"{info['lineName']} (snittforsinkelse {_format_min_sec(info.get('avgSec'))})"
    return f"<br>Linje med høyest andel forsinkelser: {label}"


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
                f"{getattr(row, 'worstLineHtml', '')}"
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
                popup=folium.Popup(popup_html, max_width=340),
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
                "{worstLineHtml}"
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
    if df.empty or df_stations.empty:
        st.info("Ingen data å vise på kart.")
        return

    station_delays = (
        df.groupby("stationId")
        .agg(avgDelay=("delaySeconds", "mean"), count=("isDelayed", "count"))
        .reset_index()
    )

    # Ved korte tidshorisonter kan det forekomme NaN i delaySeconds.
    # Sørg for at kartet alltid får en numerisk verdi å fargekode.
    if "avgDelay" in station_delays.columns:
        station_delays["avgDelay"] = pd.to_numeric(station_delays["avgDelay"], errors="coerce").fillna(0)

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

    # Fargekode med absolutte grenser (samme uansett valgt tidsperiode):
    # grønn < 2 min · gul 2–5 min · rød ≥ 5 min snittforsinkelse.
    df_map["color"] = df_map["avgDelay"].apply(delay_to_color)
    df_map["delayMin"] = (df_map["avgDelay"] / 60).round(1)

    worst_lines = compute_worst_line_per_station(df)
    df_map["worstLineHtml"] = df_map["stationId"].map(
        lambda sid: _worst_line_html(worst_lines.get(sid))
    )

    center_lat = df_map["latitude"].mean()
    center_lng = df_map["longitude"].mean()
    lat_spread = df_map["latitude"].max() - df_map["latitude"].min()
    lng_spread = df_map["longitude"].max() - df_map["longitude"].min()
    zoom = compute_zoom(lat_spread, lng_spread)

    render_station_delay_map(df_map, center_lat, center_lng, zoom)
    st.caption(MAP_DELAY_LEGEND)


# ─── Sidekonfigurasjon ────────────────────────────────────────────

st.set_page_config(
    page_title="Togforsinkelser i Norge",
    page_icon="🚆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_responsive_css()
render_top_nav("Kart", show_icons=False, show_brand_emoji=False)

st.title("Togforsinkelser i Norge")
st.caption("Interaktivt kart over forsinkelser på norske togstasjoner.")
st.caption(MAP_DELAY_LEGEND)
st.caption(
    "**Datakilde:** Sanntids- og rutedata er hentet via "
    "[Entur](https://entur.no) sitt åpne API og publisert under "
    "[Norsk lisens for offentlige data (NLOD 2.0)](https://data.norge.no/nlod/no/2.0). "
    "Dette er et uoffisielt prosjekt uten tilknytning til Entur, Bane NOR eller "
    "togselskapene. Tallene er beregnet ut fra innsamlede øyeblikksbilder og kan "
    "inneholde feil, hull eller forsinkelser i oppdateringen — bruk dem til "
    "informasjon og statistikk, ikke som grunnlag for å planlegge enkeltreiser. "
    "Entur påtar seg intet ansvar for konsekvenser av feil i data eller API-systemene."
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


df = df_all


# ═════════════════════════════════════════════════════════════════
# KART (hovedopplevelse)
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("Forsinkelseskart")

# Tidshorisont (samme oppsett som "Mest forsinkede linjer")
MAP_TIME_OPTIONS = [
    "Siste 24 timer",
    "Siste 7 dager",
    "Siste 30 dager",
    "Maks tid",
]

map_time_horizon = st.segmented_control(
    "Tidshorisont",
    options=MAP_TIME_OPTIONS,
    default="Siste 7 dager",
    key="map_time_horizon",
    label_visibility="collapsed",
)
if map_time_horizon is None:
    map_time_horizon = "Siste 7 dager"

df = apply_time_filter(df_all, map_time_horizon, now_oslo=now_oslo)
total_n = len(df)

render_map_section(df, df_stations)


# ═════════════════════════════════════════════════════════════════
# Årsaker / situasjonsmeldinger (fra API)
# ═════════════════════════════════════════════════════════════════

with st.expander("Hvorfor er det forsinkelse?", expanded=False):
    if (
        "situationSummary" not in df_all.columns
        and "situationDescription" not in df_all.columns
        and "delaySource" not in df_all.columns
    ):
        st.info("Fant ingen situasjons-/årsaksfelter i datasettet.")
    else:
        reasons_time_horizon = st.segmented_control(
            "Tidsperiode",
            options=MAP_TIME_OPTIONS,
            default="Siste 7 dager",
            key="map_reasons_time_horizon",
            label_visibility="collapsed",
        )
        if reasons_time_horizon is None:
            reasons_time_horizon = "Siste 7 dager"

        df_reasons = apply_time_filter(df_all, reasons_time_horizon, now_oslo=now_oslo)

        only_disruptions = st.checkbox(
            "Kun forsinkede/kansellerte", value=True, key="map_reasons_only_disruptions"
        )
        if only_disruptions:
            mask = pd.Series([False] * len(df_reasons), index=df_reasons.index)
            if "delaySeconds" in df_reasons.columns:
                delay_sec = pd.to_numeric(df_reasons["delaySeconds"], errors="coerce").fillna(0)
                mask |= delay_sec > 0
            elif "isDelayed" in df_reasons.columns:
                mask |= (df_reasons["isDelayed"] == 1)
            if "cancellation" in df_reasons.columns:
                mask |= (df_reasons["cancellation"] == 1)
            df_reasons = df_reasons[mask]

        level = st.radio(
            "Nivå",
            options=["Hele nettet", "Stasjon", "Linje"],
            index=0,
            horizontal=True,
            key="map_reasons_level",
            label_visibility="collapsed",
        )

        if level == "Stasjon" and "stationName" in df_reasons.columns:
            stations = sorted(df_reasons["stationName"].dropna().unique().tolist())
            if not stations:
                st.caption("Ingen stasjoner tilgjengelig for valgt filter.")
            else:
                selected_station = st.selectbox(
                    "Velg stasjon",
                    options=stations,
                    index=0,
                    key="map_reasons_station",
                )
                if selected_station:
                    df_reasons = df_reasons[df_reasons["stationName"] == selected_station]
        elif level == "Linje" and "lineName" in df_reasons.columns:
            lines = sorted(df_reasons["lineName"].dropna().unique().tolist())
            if not lines:
                st.caption("Ingen linjer tilgjengelig for valgt filter.")
            else:
                selected_line = st.selectbox(
                    "Velg linje",
                    options=lines,
                    index=0,
                    key="map_reasons_line",
                )
                if selected_line:
                    df_reasons = df_reasons[df_reasons["lineName"] == selected_line]

        # Normaliser tekstfelter
        df_msgs = df_reasons.copy()
        if "situationSummary" in df_msgs.columns:
            df_msgs["situationSummary"] = (
                df_msgs["situationSummary"].fillna("").astype(str).str.strip()
            )
        else:
            df_msgs["situationSummary"] = ""

        if "situationDescription" in df_msgs.columns:
            df_msgs["situationDescription"] = (
                df_msgs["situationDescription"].fillna("").astype(str).str.strip()
            )
        else:
            df_msgs["situationDescription"] = ""

        df_msgs = df_msgs[
            (df_msgs["situationSummary"] != "") | (df_msgs["situationDescription"] != "")
        ]

        if df_msgs.empty:
            st.caption("Ingen situasjonsmeldinger tilgjengelig for valgt tidsperiode.")
        else:
            if "delaySeconds" in df_msgs.columns:
                df_msgs["delayMin"] = (pd.to_numeric(df_msgs["delaySeconds"], errors="coerce") / 60).fillna(0)
            else:
                df_msgs["delayMin"] = 0

            grouped = (
                df_msgs.groupby(
                    ["situationSummary", "situationDescription"],
                    dropna=False,
                )
                .agg(
                    hendelser=("delayMin", "size"),
                    snitt_forsinkelse_min=("delayMin", "mean"),
                    maks_forsinkelse_min=("delayMin", "max"),
                )
                .sort_values("hendelser", ascending=False)
                .head(20)
                .reset_index()
            )

            st.dataframe(
                grouped,
                use_container_width=True,
                hide_index=True,
            )


# ═════════════════════════════════════════════════════════════════
# FORSINKELSESFORDELING (Plotly interaktivt histogram)
# ═════════════════════════════════════════════════════════════════

with st.expander("Forsinkelsesfordeling", expanded=False):
    dist_time_horizon = st.segmented_control(
        "Tidsperiode",
        options=MAP_TIME_OPTIONS,
        default="Siste 7 dager",
        key="map_dist_time_horizon",
        label_visibility="collapsed",
    )
    if dist_time_horizon is None:
        dist_time_horizon = "Siste 7 dager"

    df_dist = apply_time_filter(df_all, dist_time_horizon, now_oslo=now_oslo)
    total_n_dist = len(df_dist)

    if not df_dist.empty and "delaySeconds" in df_dist.columns:
        delay_min = df_dist["delaySeconds"] / 60

        dist_left, dist_right = st.columns([2, 3])

        with dist_left:
            buckets = {
                "I rute (0 min)": (delay_min == 0).sum(),
                "< 1 min": ((delay_min > 0) & (delay_min < 1)).sum(),
                "1–5 min": ((delay_min >= 1) & (delay_min < 5)).sum(),
                "5–15 min": ((delay_min >= 5) & (delay_min < 15)).sum(),
                "15–30 min": ((delay_min >= 15) & (delay_min < 30)).sum(),
                "30+ min": (delay_min >= 30).sum(),
            }

            st.markdown("**Antall avganger per forsinkelsesgruppe:**")
            for label, count in buckets.items():
                pct_bucket = (100 * count / total_n_dist) if total_n_dist > 0 else 0
                st.markdown(f"{label}: **{count:,}** ({pct_bucket:.1f}%)")

            on_time = list(buckets.values())[0] + list(buckets.values())[1]
            on_time_pct = (100 * on_time / total_n_dist) if total_n_dist > 0 else 0
            st.markdown(f"\n**Punktlighet (< 1 min):** {on_time_pct:.1f}%")

        with dist_right:
            df_hist = df_dist[["delaySeconds"]].copy()
            df_hist["delayMin"] = df_hist["delaySeconds"] / 60
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
            st.plotly_chart(
                fig_hist,
                use_container_width=True,
                config=PLOTLY_STATIC_CONFIG,
            )
    else:
        st.info("Ingen forsinkelsesdata tilgjengelig for å vise fordeling.")


# ═════════════════════════════════════════════════════════════════
# FORSINKELSE PER TIME (døgnmønster)
# ═════════════════════════════════════════════════════════════════

with st.expander("Forsinkelse per time (døgnmønster)", expanded=False):
    hourly_time_horizon = st.segmented_control(
        "Tidsperiode",
        options=MAP_TIME_OPTIONS,
        default="Siste 7 dager",
        key="map_hourly_time_horizon",
        label_visibility="collapsed",
    )
    if hourly_time_horizon is None:
        hourly_time_horizon = "Siste 7 dager"

    df_hourly_base = apply_time_filter(df_all, hourly_time_horizon, now_oslo=now_oslo)

    if not df_hourly_base.empty and "scheduledDeparture" in df_hourly_base.columns:
        df_hourly = df_hourly_base.dropna(subset=["scheduledDeparture"]).copy()
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
            hovertemplate=(
                "<b>Kl %{x}:00</b><br>Snitt: %{y:.1f} min<br>"
                "Avganger: %{customdata[0]}<extra></extra>"
            ),
            customdata=hourly_stats[["count"]].values,
        )
        st.plotly_chart(
            fig_hourly,
            use_container_width=True,
            config=PLOTLY_STATIC_CONFIG,
        )
    else:
        st.info("Ingen data tilgjengelig.")


# ═════════════════════════════════════════════════════════════════
# Stolpediagrammer (Plotly interaktive, side ved side)
# ═════════════════════════════════════════════════════════════════

with st.expander("Mest forsinkede stasjoner", expanded=False):
    stations_time_horizon = st.segmented_control(
        "Tidsperiode",
        options=MAP_TIME_OPTIONS,
        default="Siste 7 dager",
        key="map_stations_time_horizon",
        label_visibility="collapsed",
    )
    if stations_time_horizon is None:
        stations_time_horizon = "Siste 7 dager"

    df_stations_chart = apply_time_filter(df_all, stations_time_horizon, now_oslo=now_oslo)

    if not df_stations_chart.empty and "delaySeconds" in df_stations_chart.columns:
        station_stats = (
            df_stations_chart.groupby("stationName")["delaySeconds"]
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
            st.plotly_chart(
                fig_stations,
                use_container_width=True,
                config=PLOTLY_STATIC_CONFIG,
            )
        else:
            st.info("Ingen data å vise.")
    else:
        st.info("Ingen data å vise.")


with st.expander("Mest forsinkede linjer", expanded=False):
    lines_time_horizon = st.segmented_control(
        "Tidsperiode",
        options=MAP_TIME_OPTIONS,
        default="Siste 7 dager",
        key="map_lines_time_horizon",
        label_visibility="collapsed",
    )
    if lines_time_horizon is None:
        lines_time_horizon = "Siste 7 dager"

    df_lines_chart = apply_time_filter(df_all, lines_time_horizon, now_oslo=now_oslo)

    if not df_lines_chart.empty and "lineName" in df_lines_chart.columns:
        line_stats = (
            df_lines_chart.groupby("lineName")["delaySeconds"]
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
            st.plotly_chart(
                fig_lines,
                use_container_width=True,
                config=PLOTLY_STATIC_CONFIG,
            )
        else:
            st.info("Ingen data å vise.")
    else:
        st.info("Ingen data å vise.")


# ═════════════════════════════════════════════════════════════════
# Detaljert tabell
# ═════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("Avganger (detaljer)")

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
