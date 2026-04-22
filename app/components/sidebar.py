"""
sidebar.py — Felles sidebar-filtre for Togforsinkelser-appen.

Gir en konsistent filtreringsopplevelse på tvers av alle sider.
Alle filtre er togrelaterte — ingen andre transportmidler.
"""

from datetime import datetime, timedelta

import streamlit as st

from data_loader import OSLO_TZ, get_unique_routes


def apply_time_filter(df, selected_time, now_oslo=None):
    """
    Filtrerer DataFrame basert på valgt tidsperiode.

    Parametere:
        df: DataFrame med 'scheduledDeparture'-kolonne.
        selected_time: Tekststreng for valgt tidsperiode.
        now_oslo: Nåværende tidspunkt i Oslo-tid (default: datetime.now).

    Returnerer:
        Filtrert DataFrame.
    """
    if now_oslo is None:
        now_oslo = datetime.now(OSLO_TZ)

    if "scheduledDeparture" not in df.columns:
        return df

    period_map = {
        "Siste 24 timer": timedelta(hours=24),
        "Siste 7 dager": timedelta(days=7),
        "Siste 30 dager": timedelta(days=30),
    }

    delta = period_map.get(selected_time)
    if delta is not None:
        cutoff = now_oslo - delta
        return df[df["scheduledDeparture"] >= cutoff]

    return df  # "Alle" — ingen filtrering


def render_sidebar_filters(df, page_key, now_oslo=None):
    """
    Rendrer sidebar-filtre og returnerer filtrert DataFrame.

    Filtre:
    - Tidsperiode (24t / 7d / 30d / Alle)
    - Togrute (selectbox med søk)
    - Stasjon
    - Kun forsinkede (checkbox)

    Parametere:
        df: DataFrame med forsinkelsesdata (allerede filtrert til rail).
        page_key: Unik nøkkel-prefix for å unngå widget-kollisjoner mellom sider.
        now_oslo: Nåværende tidspunkt i Oslo-tid.

    Returnerer:
        Tuple av (filtrert_df, selected_route, selected_time)
    """
    if now_oslo is None:
        now_oslo = datetime.now(OSLO_TZ)

    st.sidebar.header("🔎 Filtre")

    # ── Tidsperiode ──
    time_options = ["Siste 24 timer", "Siste 7 dager", "Siste 30 dager", "Alle"]
    selected_time = st.sidebar.selectbox(
        "Tidsperiode",
        options=time_options,
        index=2,
        key=f"{page_key}_time_filter",
    )
    df = apply_time_filter(df, selected_time, now_oslo)

    # ── Rutesortering ──
    sort_mode = st.sidebar.radio(
        "Sorter ruter",
        options=["Alfabetisk (A–Å)", "Mest trafikkerte først"],
        index=0,
        key=f"{page_key}_route_sort",
        horizontal=True,
    )
    sort_by = "traffic" if "trafikkerte" in sort_mode else "alphabetical"
    all_routes = get_unique_routes(df, sort_by=sort_by)

    # ── Rutevalg ──
    selected_route = st.sidebar.selectbox(
        "Velg togrute",
        options=all_routes,
        index=None,
        placeholder="Alle ruter (aggregert)",
        key=f"{page_key}_route_filter",
    )
    if selected_route is not None:
        df = df[df["lineName"] == selected_route]

    # ── Stasjonsfilter ──
    all_stations = (
        sorted(df["stationName"].dropna().unique().tolist())
        if "stationName" in df.columns
        else []
    )
    selected_station = st.sidebar.selectbox(
        "Filtrer på stasjon",
        options=all_stations,
        index=None,
        placeholder="Alle stasjoner",
        key=f"{page_key}_station_filter",
    )
    if selected_station is not None:
        df = df[df["stationName"] == selected_station]

    # ── Kun forsinkede ──
    only_delayed = st.sidebar.checkbox(
        "Vis kun forsinkede", value=False, key=f"{page_key}_only_delayed"
    )
    if only_delayed and "isDelayed" in df.columns:
        df = df[df["isDelayed"] == 1]

    return df, selected_route, selected_time
