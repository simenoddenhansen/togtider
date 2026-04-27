"""
data_loader.py
──────────────
Sentralisert datalasting og filtrering for Togforsinkelser-appen.

Inneholder funksjoner for å lese forsinkelsesdata fra daglige CSV-filer,
filtrere på transporttype, og tilby hjelpefunksjoner for rute- og trafikkdata.
"""

import io
import json
import os
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import pytz
import streamlit as st

OSLO_TZ = pytz.timezone("Europe/Oslo")
HISTORY_DIRNAME = "history"
LEGACY_MASTER_FILENAME = "forsinkelser_master.csv"
ARCHIVE_BASE_URL_ENV = "TOGTIDER_ARCHIVE_BASE_URL"
ARCHIVE_INDEX_FILENAME = "archive_index.json"
ARCHIVE_FETCH_TIMEOUT = 15


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


def _archive_url(*parts):
    """Bygger en URL under arkiv-basen, eller returnerer None hvis ikke konfigurert."""
    base = archive_base_url()
    if not base:
        return None
    return "/".join([base, *parts])


def _http_get_bytes(url):
    """Henter rå bytes fra en URL. Returnerer None ved 404 eller nettverksfeil."""
    try:
        request = Request(url, headers={"User-Agent": "togtider-app"})
        with urlopen(request, timeout=ARCHIVE_FETCH_TIMEOUT) as response:
            return response.read()
    except HTTPError as e:
        if e.code == 404:
            return None
        st.warning(f"Kunne ikke hente {url}: HTTP {e.code}")
        return None
    except URLError as e:
        st.warning(f"Nettverksfeil mot arkivet ({url}): {e.reason}")
        return None


@st.cache_data(ttl=300)
def load_archive_index():
    """
    Henter arkivindeksen fra fjernarkivet. Returnerer en dict med 'days'-liste,
    eller en tom dict hvis arkivet ikke er konfigurert eller utilgjengelig.
    """
    url = _archive_url(ARCHIVE_INDEX_FILENAME)
    if url is None:
        return {}

    payload = _http_get_bytes(url)
    if payload is None:
        return {}

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        st.warning(f"Klarte ikke å tolke arkivindeks: {e}")
        return {}


@st.cache_data(ttl=3600)
def fetch_archived_day(day_key):
    """
    Henter én arkivert daglig CSV (YYYY-MM-DD) over HTTPS og returnerer
    en normalisert DataFrame. Returnerer tom DataFrame hvis filen ikke finnes.
    """
    url = _archive_url(f"forsinkelser_{day_key}.csv")
    if url is None:
        return pd.DataFrame()

    payload = _http_get_bytes(url)
    if payload is None:
        return pd.DataFrame()

    try:
        df = pd.read_csv(io.BytesIO(payload), low_memory=False)
    except Exception as e:
        st.warning(f"Klarte ikke å lese arkivfil for {day_key}: {e}")
        return pd.DataFrame()

    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
    return _normalize_delay_data(df)


def local_history_day_keys():
    """Returnerer settet av YYYY-MM-DD-nøkler som finnes lokalt i history/."""
    history_dir = delay_history_dir()
    if not os.path.isdir(history_dir):
        return set()

    keys = set()
    for name in os.listdir(history_dir):
        if name.startswith("forsinkelser_") and name.endswith(".csv"):
            keys.add(name[len("forsinkelser_") : -len(".csv")])
    return keys


def archive_day_keys():
    """Returnerer settet av YYYY-MM-DD-nøkler som finnes i fjernarkivet."""
    index = load_archive_index()
    return set(index.get("days", []))


def all_available_day_keys():
    """Returnerer alle datoer (lokale + arkiv) sortert stigende."""
    return sorted(local_history_day_keys() | archive_day_keys())


def earliest_available_date():
    """Returnerer tidligste tilgjengelige dato (date-objekt) eller None."""
    keys = all_available_day_keys()
    if not keys:
        return None
    try:
        return date.fromisoformat(keys[0])
    except ValueError:
        return None


def _day_keys_in_range(start, end):
    """Returnerer YYYY-MM-DD-nøkler mellom to datoer (inklusive begge)."""
    if start > end:
        return []
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def load_delay_range(start_date, end_date):
    """
    Laster forsinkelsesdata for et datointervall ved å kombinere lokale filer
    og arkivhenting på forespørsel. Bruker Streamlits cache, så hver
    arkivdag hentes maksimalt én gang per prosess.

    Parametere:
        start_date, end_date: date-objekter (inklusive begge ender).
    """
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()

    needed = _day_keys_in_range(start_date, end_date)
    if not needed:
        return pd.DataFrame()

    local_keys = local_history_day_keys()
    history_dir = delay_history_dir()

    frames = []
    missing_remote = []

    for key in needed:
        if key in local_keys:
            file_path = os.path.join(history_dir, f"forsinkelser_{key}.csv")
            try:
                df_part = pd.read_csv(file_path, low_memory=False)
                df_part = df_part.loc[:, ~df_part.columns.str.contains("^Unnamed")]
                if not df_part.empty:
                    frames.append(_normalize_delay_data(df_part))
            except Exception as e:
                st.warning(f"Kunne ikke lese {file_path}: {e}")
        else:
            df_remote = fetch_archived_day(key)
            if df_remote.empty:
                missing_remote.append(key)
            else:
                frames.append(df_remote)

    if missing_remote:
        st.caption(
            f"ℹ️ {len(missing_remote)} dag(er) i intervallet finnes verken lokalt "
            "eller i arkivet og ble hoppet over."
        )

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


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
