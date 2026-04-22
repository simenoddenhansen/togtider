"""
data_loader.py
──────────────
Sentralisert datalasting og filtrering for Togforsinkelser-appen.

Inneholder alle funksjoner for å lese CSV-filer, filtrere på transporttype,
og tilby hjelpefunksjoner for rute- og trafikkdata.
"""

import os
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

# ─── Konstanter ───────────────────────────────────────────────────

OSLO_TZ = pytz.timezone("Europe/Oslo")


# ─── Filstier ─────────────────────────────────────────────────────

def project_root():
    """Returnerer absolutt sti til prosjektets rotmappe."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def master_csv_path():
    """Returnerer sti til forsinkelser_master.csv."""
    return os.path.join(project_root(), "data_collection", "forsinkelser_master.csv")


def stations_csv_path():
    """Returnerer sti til alle_stasjoner.csv."""
    return os.path.join(project_root(), "data_collection", "alle_stasjoner.csv")


# ─── Filtidsstempel ──────────────────────────────────────────────

def get_mtime(path):
    """Returnerer filens sist-endret-tidsstempel, eller None hvis filen ikke finnes."""
    try:
        if not os.path.exists(path):
            return None
        return os.path.getmtime(path)
    except OSError:
        return None


# ─── Datalasting ─────────────────────────────────────────────────

@st.cache_data
def load_delay_data(path, _mtime):
    """
    Laster og parser forsinkelsesdata fra master-CSV.

    Parametere:
        path: Sti til CSV-filen.
        _mtime: Filens mtime — brukes til cache-invalidering.

    Returnerer:
        pd.DataFrame med parsede datoer og numeriske forsinkelseskolonner.
    """
    if _mtime is None or not os.path.exists(path):
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
    except Exception as e:
        st.error(f"Kunne ikke lese datafilen: {e}")
        return pd.DataFrame()

    if "scheduledDeparture" in df.columns:
        df["scheduledDeparture"] = pd.to_datetime(
            df["scheduledDeparture"], utc=True, errors="coerce"
        )
        df["scheduledDeparture"] = df["scheduledDeparture"].dt.tz_convert(OSLO_TZ)

    if "delaySeconds" in df.columns:
        df["delaySeconds"] = pd.to_numeric(df["delaySeconds"], errors="coerce").fillna(0)

    if "isDelayed" in df.columns:
        df["isDelayed"] = pd.to_numeric(df["isDelayed"], errors="coerce").fillna(0).astype(int)

    return df


@st.cache_data
def load_stations(path):
    """Laster stasjonsregisteret fra CSV."""
    if not os.path.exists(path):
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except Exception as e:
        st.error(f"Kunne ikke lese stasjonsfilen: {e}")
        return pd.DataFrame()


# ─── Togfiltrering ───────────────────────────────────────────────

def filter_rail_only(df):
    """
    Filtrerer datasettet til kun å inneholde tog (transportMode == 'rail').

    Dette sikrer at appen utelukkende viser togdata, uavhengig av hva
    som finnes i master-CSV-filen.
    """
    if df.empty or "transportMode" not in df.columns:
        return df
    return df[df["transportMode"] == "rail"].copy()


# ─── Rute-hjelpefunksjoner ───────────────────────────────────────

def get_unique_routes(df, sort_by="alphabetical"):
    """
    Returnerer en liste med unike rutenavn, sortert etter valgt metode.

    Parametere:
        df: DataFrame med forsinkelsesdata.
        sort_by: 'alphabetical' for A–Å, 'traffic' for mest trafikkerte først.

    Returnerer:
        Liste med rutenavn (str).
    """
    if df.empty or "lineName" not in df.columns:
        return []

    if sort_by == "traffic":
        # Sorter etter antall avganger (synkende) som proxy for trafikk
        route_counts = df["lineName"].value_counts()
        return route_counts.index.tolist()
    else:
        # Alfabetisk (A–Å)
        return sorted(df["lineName"].dropna().unique().tolist())


def get_route_traffic_counts(df):
    """
    Returnerer en dict med rutenavn → antall avganger.

    Brukes for å vise trafikktall i dropdown-labels.
    """
    if df.empty or "lineName" not in df.columns:
        return {}
    return df["lineName"].value_counts().to_dict()
