"""
data_loader.py
──────────────
Sentralisert datalasting og filtrering for Togforsinkelser-appen.

Inneholder funksjoner for å lese forsinkelsesdata fra daglige CSV-filer,
filtrere på transporttype, og tilby hjelpefunksjoner for rute- og trafikkdata.
"""

import os

import pandas as pd
import pytz
import streamlit as st

OSLO_TZ = pytz.timezone("Europe/Oslo")
HISTORY_DIRNAME = "history"
LEGACY_MASTER_FILENAME = "forsinkelser_master.csv"
ARCHIVE_BASE_URL_ENV = "TOGTIDER_ARCHIVE_BASE_URL"


def project_root():
    """Returnerer absolutt sti til prosjektets rotmappe."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def delay_data_dir():
    """Returnerer sti til mappen som inneholder forsinkelsesdata."""
    return os.path.join(project_root(), "data_collection")


def delay_history_dir():
    """Returnerer sti til historikkmappen med daglige CSV-filer."""
    return os.path.join(delay_data_dir(), HISTORY_DIRNAME)


def legacy_master_csv_path():
    """Returnerer sti til den gamle samlefilen som fallback under overgang."""
    return os.path.join(delay_data_dir(), LEGACY_MASTER_FILENAME)


def master_csv_path():
    """
    Returnerer historikkstien for forsinkelsesdata.

    Navnet beholdes for bakoverkompatibilitet i appen, men peker nå på
    mappen med daglige CSV-filer i stedet for én stor master-fil.
    """
    return delay_history_dir()


def stations_csv_path():
    """Returnerer sti til alle_stasjoner.csv."""
    return os.path.join(delay_data_dir(), "alle_stasjoner.csv")


def archive_base_url():
    """Returnerer valgfri base-URL for ekstern arkivhistorikk."""
    return os.environ.get(ARCHIVE_BASE_URL_ENV, "").rstrip("/")


def list_delay_data_files(path=None):
    """
    Returnerer lokale historikkfiler som skal leses.

    Foretrekker daglige filer i ``history/``. Hvis disse ikke finnes ennå,
    brukes den gamle master-filen som fallback slik at appen fortsatt virker
    under overgangen.
    """
    target_path = path or master_csv_path()
    legacy_path = legacy_master_csv_path()

    if os.path.isdir(target_path):
        files = [
            os.path.join(target_path, name)
            for name in sorted(os.listdir(target_path))
            if name.endswith(".csv")
        ]
        if files:
            return files
        return [legacy_path] if os.path.exists(legacy_path) else []

    if target_path == master_csv_path() and not os.path.exists(target_path):
        return [legacy_path] if os.path.exists(legacy_path) else []

    return [target_path] if os.path.exists(target_path) else []


def get_mtime(path):
    """Returnerer sist-endret-tid for en fil eller historikkmappe, eller None."""
    files = list_delay_data_files(path)
    if not files:
        return None

    try:
        return max(os.path.getmtime(file_path) for file_path in files)
    except OSError:
        return None


def _normalize_delay_data(df):
    """Normaliserer dato- og tallkolonner etter innlesing."""
    if "scheduledDeparture" in df.columns:
        df["scheduledDeparture"] = pd.to_datetime(
            df["scheduledDeparture"], utc=True, errors="coerce"
        )
        df["scheduledDeparture"] = df["scheduledDeparture"].dt.tz_convert(OSLO_TZ)

    if "delaySeconds" in df.columns:
        df["delaySeconds"] = pd.to_numeric(
            df["delaySeconds"], errors="coerce"
        ).fillna(0)

    if "isDelayed" in df.columns:
        df["isDelayed"] = pd.to_numeric(
            df["isDelayed"], errors="coerce"
        ).fillna(0).astype(int)

    return df


@st.cache_data
def load_delay_data(path, _mtime):
    """
    Laster og parser forsinkelsesdata fra daglige historikkfiler.

    Parametere:
        path: Sti til historikkmappe eller én konkret CSV-fil.
        _mtime: Sist-endret-tid, brukt til cache-invalidering.
    """
    files = list_delay_data_files(path)
    if _mtime is None or not files:
        return pd.DataFrame()

    frames = []
    try:
        for file_path in files:
            df_part = pd.read_csv(file_path, low_memory=False)
            df_part = df_part.loc[:, ~df_part.columns.str.contains("^Unnamed")]
            if not df_part.empty:
                frames.append(df_part)
    except Exception as e:
        st.error(f"Kunne ikke lese datafilen: {e}")
        return pd.DataFrame()

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    return _normalize_delay_data(df)


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


def filter_rail_only(df):
    """
    Filtrerer datasettet til kun å inneholde tog (transportMode == 'rail').

    Dette sikrer at appen viser togdata uavhengig av hvordan historikken er lagret.
    """
    if df.empty or "transportMode" not in df.columns:
        return df
    return df[df["transportMode"] == "rail"].copy()


def get_unique_routes(df, sort_by="alphabetical"):
    """Returnerer unike rutenavn, sortert alfabetisk eller etter trafikk."""
    if df.empty or "lineName" not in df.columns:
        return []

    if sort_by == "traffic":
        return df["lineName"].value_counts().index.tolist()

    return sorted(df["lineName"].dropna().unique().tolist())


def get_route_traffic_counts(df):
    """Returnerer en dict med rutenavn til antall avganger."""
    if df.empty or "lineName" not in df.columns:
        return {}
    return df["lineName"].value_counts().to_dict()
