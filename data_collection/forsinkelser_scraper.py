"""
forsinkelser_scraper.py
───────────────────────
Samler inn forsinkelsesdata fra togstasjoner i hele Norge.

Leser stasjonslisten fra alle_stasjoner.csv, filtrerer på transporttype,
og bruker Entur Journey Planner API med batch-queries (GraphQL-aliaser)
for å hente estimatedCalls med forsinkelsesdata.

Resultater lagres i:
  - forsinkelser_siste_kjoring.csv  (siste snapshot)
  - forsinkelser_master.csv         (historisk akkumulert)

Kjør:  python data_collection/forsinkelser_scraper.py [--modes rail,metro,tram]
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

# ─── Konfigurasjon ───────────────────────────────────────────────

API_URL = "https://api.entur.io/journey-planner/v3/graphql"
HEADERS = {
    "ET-Client-Name": "simenoddenhansen-togtider_dev",
    "Content-Type": "application/json",
}

OSLO_TZ = pytz.timezone("Europe/Oslo")
BATCH_SIZE = 20          # antall stasjoner per API-kall
TIME_RANGE = 7200        # sekunder (2 timer)
MAX_DEPARTURES = 50      # per stasjon
SLEEP_BETWEEN = 0.1      # sekunder mellom batcher (rate-limiting)
SCRIPT_TIMEOUT = 600     # 10 minutter maks

# ─── Timeout-handler (for GitHub Actions) ────────────────────────

def _timeout_handler(signum, frame):
    print("Script timeout: avslutter etter 10 minutter.")
    sys.exit(0)

if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(SCRIPT_TIMEOUT)

# ─── Hjelpefunksjoner ────────────────────────────────────────────

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


def build_batch_query(station_ids, start_time_str):
    """Bygger en GraphQL-query med aliaser for en batch av stasjoner."""
    aliases = []
    for i, sid in enumerate(station_ids):
        aliases.append(
            f'  s{i}: stopPlace(id: "{sid}") {{\n'
            f'    id\n'
            f'    name\n'
            f'    estimatedCalls(\n'
            f'      startTime: "{start_time_str}"\n'
            f'      timeRange: {TIME_RANGE}\n'
            f'      numberOfDepartures: {MAX_DEPARTURES}\n'
            f'    ) {{\n'
            f'      {ESTIMATED_CALL_FIELDS}\n'
            f'    }}\n'
            f'  }}'
        )
    return "{\n" + "\n".join(aliases) + "\n}"


def parse_calls(stop_data, scraped_at):
    """Parser estimatedCalls fra ett stoppested til en liste av dicts."""
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

        # Beregn forsinkelse
        try:
            aimed_dt = datetime.fromisoformat(aimed)
            expected_dt = datetime.fromisoformat(expected)
            delay_seconds = (expected_dt - aimed_dt).total_seconds()
        except (ValueError, TypeError):
            delay_seconds = 0.0

        rows.append({
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
            "scrapedAt": scraped_at,
        })

    return rows


def fetch_delays(station_ids, start_time_str, scraped_at):
    """Henter forsinkelsesdata for alle stasjoner med batch-queries."""
    all_rows = []
    total_batches = (len(station_ids) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(station_ids))
        batch = station_ids[start:end]

        query = build_batch_query(batch, start_time_str)

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
                print(f"  Batch {batch_idx + 1}: GraphQL-feil: {data['errors'][:2]}")

            result = data.get("data", {})
            for i in range(len(batch)):
                stop_data = result.get(f"s{i}")
                if stop_data:
                    all_rows.extend(parse_calls(stop_data, scraped_at))

        except requests.RequestException as e:
            print(f"  Batch {batch_idx + 1}/{total_batches}: Nettverksfeil: {e}")

        if batch_idx < total_batches - 1:
            time.sleep(SLEEP_BETWEEN)

        if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
            print(f"  Batch {batch_idx + 1}/{total_batches} ferdig — {len(all_rows)} avganger samlet inn.")

    return all_rows


# ─── Hovedprogram ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Samler forsinkelsesdata fra norske stasjoner")
    parser.add_argument(
        "--modes",
        default="rail",
        help="Kommaseparerte transporttyper å hente (default: rail). Eksempel: rail,metro,tram",
    )
    args = parser.parse_args()
    target_modes = [m.strip().lower() for m in args.modes.split(",")]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    stations_path = os.path.join(script_dir, "alle_stasjoner.csv")

    if not os.path.exists(stations_path):
        print(f"Finner ikke stasjonsfilen: {stations_path}")
        print("Kjør først:  python data_collection/hent_alle_stasjoner.py")
        sys.exit(1)

    # Les stasjoner og filtrer
    df_stations = pd.read_csv(stations_path)
    print(f"Lastet {len(df_stations)} stoppesteder fra {stations_path}")

    # Filtrer på transporttype (transportMode kan inneholde kommaseparerte verdier)
    mask = df_stations["transportMode"].fillna("").apply(
        lambda x: any(m in x.lower() for m in target_modes)
    )
    df_filtered = df_stations[mask]
    print(f"Filtrert til {len(df_filtered)} stasjoner med transporttype: {', '.join(target_modes)}")

    if df_filtered.empty:
        print("Ingen stasjoner å hente data for. Avslutter.")
        return

    station_ids = df_filtered["id"].tolist()

    # Tid
    now = datetime.now(OSLO_TZ)
    one_hour_ago = now - timedelta(hours=1)
    start_time = one_hour_ago.replace(minute=0, second=0, microsecond=0)
    start_time_str = start_time.isoformat()
    scraped_at = now.isoformat()

    print(f"\nHenter forsinkelsesdata fra {start_time_str} …")
    print(f"Batcher: {(len(station_ids) + BATCH_SIZE - 1) // BATCH_SIZE} (à {BATCH_SIZE} stasjoner)\n")

    t0 = time.time()
    rows = fetch_delays(station_ids, start_time_str, scraped_at)
    elapsed = time.time() - t0

    print(f"\nFerdig! {len(rows)} avganger samlet inn på {elapsed:.1f}s.")

    if not rows:
        print("Ingen avganger funnet. Avslutter.")
        return

    # ─── Lagre ────────────────────────────────────────────────

    EXPECTED_COLUMNS = [
        "stationId", "stationName", "scheduledDeparture", "expectedDeparture",
        "actualDeparture", "delaySeconds", "isDelayed", "destination",
        "lineId", "lineName", "lineCode", "transportMode",
        "serviceJourneyId", "realtime", "scrapedAt",
    ]

    df_new = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)

    # Snapshot (overskrives hver gang)
    snapshot_path = os.path.join(script_dir, "forsinkelser_siste_kjoring.csv")
    df_new.to_csv(snapshot_path, index=False, encoding="utf-8")
    print(f"Snapshot lagret: {snapshot_path} ({len(df_new)} rader)")

    # Master (akkumuleres)
    master_path = os.path.join(script_dir, "forsinkelser_master.csv")

    if os.path.exists(master_path):
        df_master = pd.read_csv(master_path)
        df_master = df_master.loc[:, ~df_master.columns.str.contains("^Unnamed")]
    else:
        df_master = pd.DataFrame(columns=EXPECTED_COLUMNS)

    # Legg til manglende kolonner
    for col in EXPECTED_COLUMNS:
        if col not in df_master.columns:
            df_master[col] = pd.NA

    df_all = pd.concat([df_master, df_new], ignore_index=True)

    # Dedupliser på (stationId, scheduledDeparture, serviceJourneyId)
    dedupe_keys = ["stationId", "scheduledDeparture", "serviceJourneyId"]
    before = len(df_all)
    df_all = df_all.drop_duplicates(subset=dedupe_keys, keep="last")
    after = len(df_all)

    df_all.to_csv(master_path, index=False, encoding="utf-8")
    print(f"Master lagret: {master_path} ({after} rader, {before - after} duplikater fjernet)")


if __name__ == "__main__":
    main()
