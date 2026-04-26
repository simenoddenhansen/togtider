"""
forsinkelser_scraper.py
───────────────────────
Samler inn forsinkelsesdata fra togstasjoner i hele Norge.

Historikk lagres som daglige CSV-filer i ``data_collection/history/``.
Dette unngår at én enkelt masterfil vokser ukontrollert i Git.

Resultater lagres i:
  - forsinkelser_siste_kjoring.csv              (siste snapshot)
  - history/forsinkelser_YYYY-MM-DD.csv         (historisk akkumulert per dag)

Kjør: python data_collection/forsinkelser_scraper.py [--modes rail,metro,tram]
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import pytz
import requests

API_URL = "https://api.entur.io/journey-planner/v3/graphql"
HEADERS = {
    "ET-Client-Name": "simenoddenhansen-togtider_dev",
    "Content-Type": "application/json",
}

OSLO_TZ = pytz.timezone("Europe/Oslo")
BATCH_SIZE = 20
MAX_DEPARTURES = 50
SLEEP_BETWEEN = 0.1
SCRIPT_TIMEOUT = 600

MAX_LOOKBACK_SECONDS = 14400
DEFAULT_LOOKBACK_SECONDS = 7200
LOOKAHEAD_SECONDS = 3600

HISTORY_DIRNAME = "history"
LEGACY_MASTER_FILENAME = "forsinkelser_master.csv"

EXPECTED_COLUMNS = [
    "stationId",
    "stationName",
    "scheduledDeparture",
    "expectedDeparture",
    "actualDeparture",
    "delaySeconds",
    "isDelayed",
    "destination",
    "lineId",
    "lineName",
    "lineCode",
    "transportMode",
    "serviceJourneyId",
    "realtime",
    "delaySource",
    "scrapedAt",
]

ESTIMATED_CALL_FIELDS = """
    realtime
    aimedDepartureTime
    expectedDepartureTime
    actualDepartureTime
    destinationDisplay { frontText }
    serviceJourney {
        id
        journeyPattern {
            line {
                id
                name
                publicCode
                transportMode
            }
        }
    }
"""


def _timeout_handler(signum, frame):
    print("Script timeout: avslutter etter 10 minutter.")
    sys.exit(0)


if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(SCRIPT_TIMEOUT)


def history_dir_path(script_dir):
    """Returnerer stien til historikkmappen."""
    return os.path.join(script_dir, HISTORY_DIRNAME)


def ensure_history_dir(script_dir):
    """Oppretter historikkmappen hvis den ikke finnes."""
    os.makedirs(history_dir_path(script_dir), exist_ok=True)
    return history_dir_path(script_dir)


def legacy_master_path(script_dir):
    """Returnerer stien til gammel masterfil."""
    return os.path.join(script_dir, LEGACY_MASTER_FILENAME)


def list_daily_history_paths(script_dir):
    """Returnerer daglige historikkfiler i sortert rekkefolge."""
    history_dir = history_dir_path(script_dir)
    if not os.path.isdir(history_dir):
        return []

    return [
        os.path.join(history_dir, name)
        for name in sorted(os.listdir(history_dir))
        if name.endswith(".csv")
    ]


def daily_history_path(script_dir, day_key):
    """Returnerer filsti for en daglig historikkfil."""
    ensure_history_dir(script_dir)
    return os.path.join(history_dir_path(script_dir), f"forsinkelser_{day_key}.csv")


def _prepare_dataframe_columns(df):
    """Rydder kolonner og sikrer forventet skjema."""
    if df.empty:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    df = df.loc[:, ~df.columns.str.contains("^Unnamed")].copy()
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    return df.reindex(columns=EXPECTED_COLUMNS)


def _history_day_keys(df):
    """
    Returnerer dagnoekkel (YYYY-MM-DD) for hver rad.

    Bruker scheduledDeparture foerst, og scrapedAt som fallback.
    """
    scheduled = pd.to_datetime(df.get("scheduledDeparture"), utc=True, errors="coerce")
    scraped = pd.to_datetime(df.get("scrapedAt"), utc=True, errors="coerce")
    day_base = scheduled.fillna(scraped)
    return day_base.dt.strftime("%Y-%m-%d")


def migrate_legacy_master_to_daily(script_dir):
    """
    Splitter gammel masterfil til daglige historikkfiler foerste gang.

    Legacy-filen beholdes som sikkerhetsnett inntil brukeren selv velger
    aa rydde Git-historikken senere.
    """
    daily_paths = list_daily_history_paths(script_dir)
    legacy_path = legacy_master_path(script_dir)

    if daily_paths or not os.path.exists(legacy_path):
        return

    df_legacy = pd.read_csv(legacy_path, low_memory=False)
    df_legacy = _prepare_dataframe_columns(df_legacy)
    if df_legacy.empty:
        ensure_history_dir(script_dir)
        return

    day_keys = _history_day_keys(df_legacy)
    valid_mask = day_keys.notna()
    df_legacy = df_legacy[valid_mask].copy()
    df_legacy["_historyDay"] = day_keys[valid_mask]

    if df_legacy.empty:
        ensure_history_dir(script_dir)
        print("Fant legacy master-fil, men ingen gyldige datoer aa migrere.")
        return

    for day_key, df_day in df_legacy.groupby("_historyDay", sort=True):
        day_path = daily_history_path(script_dir, day_key)
        df_day = df_day.drop(columns=["_historyDay"])
        df_day.to_csv(day_path, index=False, encoding="utf-8")
        print(f"Migrerte legacy-data til {day_path} ({len(df_day)} rader)")


def get_last_scraped_time(script_dir):
    """Leser siste scrapedAt fra daglige filer, eller legacy-fil som fallback."""
    candidate_paths = list(reversed(list_daily_history_paths(script_dir)))

    if not candidate_paths:
        legacy_path = legacy_master_path(script_dir)
        if os.path.exists(legacy_path):
            candidate_paths = [legacy_path]

    for path in candidate_paths:
        try:
            df = pd.read_csv(path, usecols=["scrapedAt"], low_memory=False)
            if df.empty:
                continue

            last_ts = pd.to_datetime(df["scrapedAt"], utc=True, errors="coerce").max()
            if pd.isna(last_ts):
                continue

            return last_ts.astimezone(OSLO_TZ)
        except Exception as e:
            print(f"Advarsel: Kunne ikke lese siste scrapedAt fra {path}: {e}")

    return None


def build_batch_query(station_ids, start_time_str, time_range):
    """Bygger GraphQL-query med aliaser for en batch av stasjoner."""
    aliases = []
    for i, sid in enumerate(station_ids):
        aliases.append(
            f'  s{i}: stopPlace(id: "{sid}") {{\n'
            f'    id\n'
            f'    name\n'
            f'    estimatedCalls(\n'
            f'      startTime: "{start_time_str}"\n'
            f'      timeRange: {time_range}\n'
            f'      numberOfDepartures: {MAX_DEPARTURES}\n'
            f'    ) {{\n'
            f'      {ESTIMATED_CALL_FIELDS}\n'
            f'    }}\n'
            f'  }}'
        )
    return "{\n" + "\n".join(aliases) + "\n}"


def parse_calls(stop_data, scraped_at):
    """Parser estimatedCalls fra ett stoppested til en liste med rader."""
    rows = []
    station_id = stop_data.get("id", "")
    station_name = stop_data.get("name", "")

    for call in stop_data.get("estimatedCalls", []):
        aimed = call.get("aimedDepartureTime")
        if aimed is None:
            continue

        expected = call.get("expectedDepartureTime") or aimed
        actual = call.get("actualDepartureTime")
        destination = (call.get("destinationDisplay") or {}).get("frontText", "")

        sj = call.get("serviceJourney") or {}
        sj_id = sj.get("id", "")
        jp = sj.get("journeyPattern") or {}
        line = jp.get("line") or {}

        delay_seconds = 0.0
        delay_source = "planned"

        try:
            aimed_dt = datetime.fromisoformat(aimed)
            if actual:
                actual_dt = datetime.fromisoformat(actual)
                delay_seconds = (actual_dt - aimed_dt).total_seconds()
                delay_source = "actual"
            elif expected and expected != aimed:
                expected_dt = datetime.fromisoformat(expected)
                delay_seconds = (expected_dt - aimed_dt).total_seconds()
                delay_source = "expected"
        except (ValueError, TypeError):
            delay_seconds = 0.0
            delay_source = "error"

        rows.append(
            {
                "stationId": station_id,
                "stationName": station_name,
                "scheduledDeparture": aimed,
                "expectedDeparture": expected,
                "actualDeparture": actual,
                "delaySeconds": delay_seconds,
                "isDelayed": int(delay_seconds > 0),
                "destination": destination,
                "lineId": line.get("id", ""),
                "lineName": line.get("name", ""),
                "lineCode": line.get("publicCode", ""),
                "transportMode": line.get("transportMode", ""),
                "serviceJourneyId": sj_id,
                "realtime": call.get("realtime", False),
                "delaySource": delay_source,
                "scrapedAt": scraped_at,
            }
        )

    return rows


def fetch_delays(station_ids, start_time_str, time_range, scraped_at):
    """Henter forsinkelsesdata for alle stasjoner med batch-queries."""
    all_rows = []
    total_batches = (len(station_ids) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(station_ids))
        batch = station_ids[start:end]
        query = build_batch_query(batch, start_time_str, time_range)

        try:
            response = requests.post(
                API_URL,
                json={"query": query},
                headers=HEADERS,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                print(f"Batch {batch_idx + 1}: GraphQL-feil: {data['errors'][:2]}")

            result = data.get("data", {})
            for i in range(len(batch)):
                stop_data = result.get(f"s{i}")
                if stop_data:
                    all_rows.extend(parse_calls(stop_data, scraped_at))
        except requests.RequestException as e:
            print(f"Batch {batch_idx + 1}/{total_batches}: Nettverksfeil: {e}")

        if batch_idx < total_batches - 1:
            time.sleep(SLEEP_BETWEEN)

        if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
            print(
                f"Batch {batch_idx + 1}/{total_batches} ferdig - "
                f"{len(all_rows)} avganger samlet inn."
            )

    return all_rows


def smart_dedup(df_all, dedupe_keys):
    """Beholder den beste raden per unik avgang."""
    before = len(df_all)

    df_all["_has_actual"] = df_all["actualDeparture"].notna() & (
        df_all["actualDeparture"] != ""
    )
    df_all["_is_realtime"] = df_all["realtime"].astype(str).str.lower() == "true"

    df_all = df_all.sort_values(
        by=["_has_actual", "_is_realtime", "scrapedAt"],
        ascending=[False, False, False],
    )
    df_all = df_all.drop_duplicates(subset=dedupe_keys, keep="first")
    df_all = df_all.drop(columns=["_has_actual", "_is_realtime"])

    after = len(df_all)
    print(f"Smart dedup: {before} -> {after} rader ({before - after} duplikater fjernet)")
    return df_all


def append_to_daily_history(script_dir, df_new):
    """Oppdaterer berorte dagsfiler med nye rader og smart deduplisering."""
    df_new = _prepare_dataframe_columns(df_new)
    day_keys = _history_day_keys(df_new)
    valid_mask = day_keys.notna()

    if not valid_mask.any():
        print("Ingen gyldige datoer aa lagre i historikkfilene.")
        return

    df_new = df_new[valid_mask].copy()
    df_new["_historyDay"] = day_keys[valid_mask]
    dedupe_keys = ["stationId", "scheduledDeparture", "serviceJourneyId"]

    for day_key, df_day_new in df_new.groupby("_historyDay", sort=True):
        day_path = daily_history_path(script_dir, day_key)
        df_day_new = df_day_new.drop(columns=["_historyDay"])

        if os.path.exists(day_path):
            df_existing = pd.read_csv(day_path, low_memory=False)
            df_existing = _prepare_dataframe_columns(df_existing)
        else:
            df_existing = pd.DataFrame(columns=EXPECTED_COLUMNS)

        df_all = pd.concat([df_existing, df_day_new], ignore_index=True)
        df_all = smart_dedup(df_all, dedupe_keys)
        df_all.to_csv(day_path, index=False, encoding="utf-8")
        print(f"Historikk lagret: {day_path} ({len(df_all)} rader)")


def main():
    parser = argparse.ArgumentParser(
        description="Samler forsinkelsesdata fra norske stasjoner"
    )
    parser.add_argument(
        "--modes",
        default="rail",
        help="Kommaseparerte transporttyper aa hente, f.eks. rail,metro,tram",
    )
    args = parser.parse_args()
    target_modes = [m.strip().lower() for m in args.modes.split(",")]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    stations_path = os.path.join(script_dir, "alle_stasjoner.csv")

    migrate_legacy_master_to_daily(script_dir)

    if not os.path.exists(stations_path):
        print(f"Finner ikke stasjonsfilen: {stations_path}")
        print("Kjor foerst: python data_collection/hent_alle_stasjoner.py")
        sys.exit(1)

    df_stations = pd.read_csv(stations_path)
    print(f"Lastet {len(df_stations)} stoppesteder fra {stations_path}")

    mask = df_stations["transportMode"].fillna("").apply(
        lambda x: any(mode in x.lower() for mode in target_modes)
    )
    df_filtered = df_stations[mask]
    print(
        f"Filtrert til {len(df_filtered)} stasjoner med transporttype: "
        f"{', '.join(target_modes)}"
    )

    if df_filtered.empty:
        print("Ingen stasjoner aa hente data for. Avslutter.")
        return

    now = datetime.now(OSLO_TZ)
    last_scraped = get_last_scraped_time(script_dir)
    if last_scraped is not None:
        gap_start = last_scraped - timedelta(minutes=15)
        lookback_seconds = int((now - gap_start).total_seconds())
        lookback_seconds = min(lookback_seconds, MAX_LOOKBACK_SECONDS)
        gap_minutes = int((now - last_scraped).total_seconds() / 60)
        print(f"\nSiste scrape: {last_scraped.isoformat()} ({gap_minutes} min siden)")
    else:
        lookback_seconds = DEFAULT_LOOKBACK_SECONDS
        print(f"\nIngen tidligere scrape funnet - bruker standard {lookback_seconds}s bakover")

    start_time = now - timedelta(seconds=lookback_seconds)
    start_time_str = start_time.isoformat()
    time_range = lookback_seconds + LOOKAHEAD_SECONDS
    scraped_at = now.isoformat()

    station_ids = df_filtered["id"].tolist()
    print(f"Henter forsinkelsesdata fra {start_time_str} (timeRange={time_range}s) ...")
    print(
        f"Batcher: {(len(station_ids) + BATCH_SIZE - 1) // BATCH_SIZE} "
        f"(a {BATCH_SIZE} stasjoner)\n"
    )

    t0 = time.time()
    rows = fetch_delays(station_ids, start_time_str, time_range, scraped_at)
    elapsed = time.time() - t0
    print(f"\nFerdig! {len(rows)} avganger samlet inn pa {elapsed:.1f}s.")

    if not rows:
        print("Ingen avganger funnet. Avslutter.")
        return

    df_new = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    snapshot_path = os.path.join(script_dir, "forsinkelser_siste_kjoring.csv")
    df_new.to_csv(snapshot_path, index=False, encoding="utf-8")
    print(f"Snapshot lagret: {snapshot_path} ({len(df_new)} rader)")

    append_to_daily_history(script_dir, df_new)


if __name__ == "__main__":
    main()
