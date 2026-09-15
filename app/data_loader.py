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
ARCHIVE_INDEX_MAX_BYTES = 512 * 1024
ARCHIVE_DAY_MAX_BYTES = 16 * 1024 * 1024
ARCHIVE_INDEX_MAX_DAYS = 10_000
DELAY_DATA_NORMALIZATION_VERSION = 3

# Grenser for brukerinitierte nedlastinger. Intervallgrensen ma handheves i
# datalaget ogsa, slik at en fremtidig UI-endring ikke kan omga den.
MAX_DOWNLOAD_RANGE_DAYS = 7
DOWNLOAD_ROW_LIMITS = {
    "CSV": 100_000,
    "Excel (.xlsx)": 50_000,
    "JSON": 50_000,
}
MAX_DOWNLOAD_FRAME_BYTES = 64 * 1024 * 1024
MAX_DOWNLOAD_OUTPUT_BYTES = 64 * 1024 * 1024

# Lavkardinalitet-kolonner som komprimeres kraftig som category-dtype.
_CATEGORICAL_COLUMNS = frozenset({
    "lineName", "lineCode", "transportMode", "stationName", "stationId",
    "destination", "delaySource", "lineId",
})

# Standardkolonner for dashboardet (Togforsinkelser.py + felles sidebar).
DASHBOARD_COLUMNS = (
    "scheduledDeparture", "delaySeconds", "isDelayed",
    "lineName", "transportMode", "stationName",
)

# Standardkolonner for kartsiden / landingssiden (Togforsinkelser.py).
MAP_COLUMNS = (
    "scheduledDeparture", "delaySeconds", "isDelayed",
    "lineName", "lineCode", "transportMode",
    "stationId", "stationName", "destination",
    "delaySource", "realtime",
    "cancellation",
    "situationSummary", "situationDescription",
    "situationReportType", "situationSeverity",
)

# Antall dager med lokale data som lastes inn som standard. Eldre data
# hentes fra arkivet ved behov via load_delay_range / fetch_archived_day.
DEFAULT_RECENT_DAYS_DASHBOARD = 60   # 30-dagers KPI sammenligner mot forrige 30-dagers periode
DEFAULT_RECENT_DAYS_MAP = 30
DEFAULT_RECENT_DAYS_DOWNLOAD = MAX_DOWNLOAD_RANGE_DAYS


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


def get_last_scraped_at(path=None):
    """Returnerer siste scrapedAt-tidspunkt fra nyeste fil, eller None."""
    files = list_delay_data_files(path)
    if not files:
        return None

    # De nyeste filene ligger sist
    for file_path in reversed(files):
        try:
            df = pd.read_csv(file_path, usecols=["scrapedAt"], low_memory=False)
            if df.empty:
                continue
            last_ts = pd.to_datetime(df["scrapedAt"], utc=True, errors="coerce").max()
            if not pd.isna(last_ts):
                return last_ts.astimezone(OSLO_TZ)
        except Exception:
            continue
            
    return None


def _archive_url(*parts):
    """Bygger en URL under arkiv-basen, eller returnerer None hvis ikke konfigurert."""
    base = archive_base_url()
    if not base:
        return None
    return "/".join([base, *parts])


def _http_get_bytes(url, max_bytes):
    """Henter en begrenset respons. Returnerer None ved feil eller for stor fil."""
    if max_bytes <= 0:
        raise ValueError("max_bytes ma vaere positiv")

    try:
        request = Request(url, headers={"User-Agent": "togtider-app"})
        with urlopen(request, timeout=ARCHIVE_FETCH_TIMEOUT) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) > max_bytes:
                        st.warning("Arkivresponsen var for stor og ble avvist.")
                        return None
                except ValueError:
                    pass

            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                st.warning("Arkivresponsen var for stor og ble avvist.")
                return None
            return payload
    except HTTPError as e:
        if e.code == 404:
            return None
        st.warning(f"Kunne ikke hente data fra arkivet: HTTP {e.code}")
        return None
    except URLError as e:
        st.warning(f"Nettverksfeil mot arkivet: {e.reason}")
        return None


def _is_archive_day_key(value):
    """Returnerer True bare for kanoniske YYYY-MM-DD-datoer."""
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _parse_archive_index(payload):
    """Tolker og validerer en begrenset arkivindeks."""
    index = json.loads(payload.decode("utf-8"))
    if not isinstance(index, dict) or not isinstance(index.get("days"), list):
        raise ValueError("arkivindeksen mangler en gyldig days-liste")

    days = index["days"]
    if len(days) > ARCHIVE_INDEX_MAX_DAYS:
        raise ValueError("arkivindeksen inneholder for mange dager")
    if any(not _is_archive_day_key(day_key) for day_key in days):
        raise ValueError("arkivindeksen inneholder en ugyldig dato")

    return {**index, "days": sorted(set(days))}


@st.cache_data(ttl=300)
def load_archive_index():
    """
    Henter arkivindeksen fra fjernarkivet. Returnerer en dict med 'days'-liste,
    eller en tom dict hvis arkivet ikke er konfigurert eller utilgjengelig.
    """
    url = _archive_url(ARCHIVE_INDEX_FILENAME)
    if url is None:
        return {}

    payload = _http_get_bytes(url, ARCHIVE_INDEX_MAX_BYTES)
    if payload is None:
        return {}

    try:
        return _parse_archive_index(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        st.warning(f"Klarte ikke å tolke arkivindeks: {e}")
        return {}


@st.cache_data(ttl=3600)
def fetch_archived_day(day_key):
    """
    Henter én arkivert daglig CSV (YYYY-MM-DD) over HTTPS og returnerer
    en normalisert DataFrame. Returnerer tom DataFrame hvis filen ikke finnes.
    """
    if not _is_archive_day_key(day_key):
        st.warning("Ugyldig dato for arkivfil.")
        return pd.DataFrame()

    url = _archive_url(f"forsinkelser_{day_key}.csv")
    if url is None:
        return pd.DataFrame()

    payload = _http_get_bytes(url, ARCHIVE_DAY_MAX_BYTES)
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
            day_key = name[len("forsinkelser_") : -len(".csv")]
            if _is_archive_day_key(day_key):
                keys.add(day_key)
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


def validate_download_range(start_date, end_date):
    """Validerer og normaliserer et brukerinitiert nedlastingsintervall."""
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise TypeError("start_date og end_date må være datoer")
    if start_date > end_date:
        raise ValueError("Startdato kan ikke være etter sluttdato.")
    if (end_date - start_date).days > MAX_DOWNLOAD_RANGE_DAYS:
        raise ValueError(
            f"Perioden kan ikke være lengre enn {MAX_DOWNLOAD_RANGE_DAYS} dager."
        )
    return start_date, end_date


def load_delay_range(start_date, end_date):
    """
    Laster forsinkelsesdata for et datointervall ved å kombinere lokale filer
    og arkivhenting på forespørsel. Bruker Streamlits cache, så hver
    arkivdag hentes maksimalt én gang per prosess.

    Parametere:
        start_date, end_date: date-objekter (inklusive begge ender).
    """
    start_date, end_date = validate_download_range(start_date, end_date)

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
            f"{len(missing_remote)} dag(er) i intervallet finnes verken lokalt "
            "eller i arkivet og ble hoppet over."
        )

    if not frames:
        return pd.DataFrame()

    return _apply_categorical_dtypes(pd.concat(frames, ignore_index=True))


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
        ).fillna(0).clip(lower=0)

    if "isDelayed" in df.columns:
        if "delaySeconds" in df.columns:
            df["isDelayed"] = (df["delaySeconds"] > 0).astype(int)
        else:
            df["isDelayed"] = pd.to_numeric(
                df["isDelayed"], errors="coerce"
            ).fillna(0).astype(int)

    return df


def _filename_date(path):
    """Returnerer YYYY-MM-DD-datoen fra en historikkfil, eller None."""
    name = os.path.basename(path)
    if not (name.startswith("forsinkelser_") and name.endswith(".csv")):
        return None
    key = name[len("forsinkelser_") : -len(".csv")]
    try:
        return date.fromisoformat(key)
    except ValueError:
        return None


def _filter_recent_files(files, days_back, today=None):
    """
    Returnerer kun historikkfiler innenfor de siste ``days_back`` dagene.
    Filer uten gjenkjennelig datostempel (f.eks. legacy master-fil) beholdes.
    """
    if days_back is None:
        return files
    if today is None:
        today = datetime.now(OSLO_TZ).date()
    cutoff = today - timedelta(days=days_back)
    kept = []
    for file_path in files:
        d = _filename_date(file_path)
        if d is None or d >= cutoff:
            kept.append(file_path)
    return kept


def _apply_categorical_dtypes(df):
    """Konverterer lavkardinalitet-strengkolonner til category for memory."""
    for col in df.columns:
        if col in _CATEGORICAL_COLUMNS and df[col].dtype == object:
            df[col] = df[col].astype("category")
    return df


@st.cache_data
def _load_delay_file(
    file_path,
    mtime,
    columns=None,
    normalization_version=DELAY_DATA_NORMALIZATION_VERSION,
):
    """Laster og parser én forsinkelsesfil. Cachet per (sti, mtime, kolonner)."""
    read_kwargs = {"low_memory": False}
    if columns is not None:
        read_kwargs["usecols"] = lambda name: name in columns or name.startswith("Unnamed")

    try:
        df_part = pd.read_csv(file_path, **read_kwargs)
    except Exception as e:
        st.error(f"Kunne ikke lese datafilen {file_path}: {e}")
        return pd.DataFrame()

    df_part = df_part.loc[:, ~df_part.columns.str.contains("^Unnamed")]
    if df_part.empty:
        return pd.DataFrame()

    df_part = _normalize_delay_data(df_part)
    return _apply_categorical_dtypes(df_part)


def load_delay_data(path, mtime, days_back=None, columns=None):
    """
    Laster og parser forsinkelsesdata fra daglige historikkfiler.

    Parametere:
        path: Sti til historikkmappen (eller legacy master-fil).
        mtime: Sist-endret-tid for cache-invalidering.
        days_back: Hvis satt, last kun filer for de siste N dagene.
        columns: Hvis satt, last kun disse kolonnene (memory-optimalisering).
    """
    files = list_delay_data_files(path)
    if mtime is None or not files:
        return pd.DataFrame()

    files = _filter_recent_files(files, days_back)
    if not files:
        return pd.DataFrame()

    columns_key = tuple(columns) if columns is not None else None

    frames = []
    for file_path in files:
        try:
            file_mtime = os.path.getmtime(file_path)
        except OSError:
            continue
        df_part = _load_delay_file(file_path, file_mtime, columns=columns_key)
        if not df_part.empty:
            frames.append(df_part)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    return _apply_categorical_dtypes(result)


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
    Etter filtreringen ryddes ubrukte category-verdier bort, slik at downstream
    groupby/value_counts ikke produserer tomme rader for buss-/båtkategorier.
    """
    if df.empty or "transportMode" not in df.columns:
        return df
    result = df[df["transportMode"] == "rail"].copy()
    for col in result.select_dtypes(include="category").columns:
        result[col] = result[col].cat.remove_unused_categories()
    return result


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
