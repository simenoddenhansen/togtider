"""
forsinkelser_scraper.py
───────────────────────
Samler inn forsinkelsesdata fra togstasjoner i hele Norge.

Leser stasjonslisten fra alle_stasjoner.csv, filtrerer på transporttype,
og bruker Entur Journey Planner API med batch-queries (GraphQL-aliaser)
for å hente estimatedCalls med forsinkelsesdata.

Forbedringer (v2):
  - Dynamisk tidsvindu: leser siste scrapedAt fra master-filen og dekker
    hele gapet tilbake, slik at ingen avganger går tapt ved uregelmessige
    GitHub Actions-kjøringer.
  - Prioriterer actualDepartureTime > expectedDepartureTime for beregning
    av forsinkelse (mest presis kilde).
  - Smart dedup: beholder raden med best datakvalitet (actual > realtime > nyeste)
    i stedet for blindt å ta den siste.
  - Ny kolonne 'delaySource' som indikerer kvaliteten på forsinkelsesmålingen.

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
MAX_DEPARTURES = 50      # per stasjon
SLEEP_BETWEEN = 0.1      # sekunder mellom batcher (rate-limiting)
SCRIPT_TIMEOUT = 600     # 10 minutter maks

# Maks tidsvindu bakover (sekunder) — begrenser hvor langt tilbake vi ser
# selv om gapet er stort (API-et har uansett slettet data etter ~2-3 timer)
MAX_LOOKBACK_SECONDS = 14400   # 4 timer
# Standard fallback hvis ingen tidligere kjøring finnes
DEFAULT_LOOKBACK_SECONDS = 7200  # 2 timer
# Hvor langt fremover vi ser (fange avganger som snart skjer)
LOOKAHEAD_SECONDS = 3600  # 1 time

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


def get_last_scraped_time(master_path):
    """
    Leser siste scrapedAt-tidsstempel fra master-CSV-filen.

    Brukes til å beregne dynamisk tidsvindu slik at vi dekker hele gapet
    siden forrige kjøring, i stedet for et fast 1-timers vindu.

    Returnerer:
        datetime med timezone, eller None hvis filen ikke finnes.
    """
    if not os.path.exists(master_path):
        return None

    try:
        # Les kun scrapedAt-kolonnen for ytelse (master kan være stor)
        df = pd.read_csv(master_path, usecols=["scrapedAt"])
        if df.empty:
            return None

        last_ts = pd.to_datetime(df["scrapedAt"]).max()
        if pd.isna(last_ts):
            return None

        # Konverter til Oslo-tid
        if last_ts.tzinfo is None:
            last_ts = OSLO_TZ.localize(last_ts)
        else:
            last_ts = last_ts.astimezone(OSLO_TZ)

        return last_ts
    except Exception as e:
        print(f"  Advarsel: Kunne ikke lese siste scrapedAt: {e}")
        return None


def build_batch_query(station_ids, start_time_str, time_range):
    """Bygger en GraphQL-query med aliaser for en batch av stasjoner."""
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
    """
    Parser estimatedCalls fra ett stoppested til en liste av dicts.

    Forsinkelse beregnes med prioritering:
      1. actualDepartureTime (best — observert avgang)
      2. expectedDepartureTime (nest best — sanntidsestimat)
      3. aimedDepartureTime (verst — kun planlagt, delay = 0)

    Kolonnen 'delaySource' indikerer hvilken kilde som ble brukt.
    """
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

        # ── Beregn forsinkelse med prioritert kilde ──
        # Prioritet: actual > expected > aimed
        delay_seconds = 0.0
        delay_source = "planned"  # Standardantakelse

        try:
            aimed_dt = datetime.fromisoformat(aimed)

            if actual:
                # Best: faktisk observert avgangstid
                actual_dt = datetime.fromisoformat(actual)
                delay_seconds = (actual_dt - aimed_dt).total_seconds()
                delay_source = "actual"
            elif expected and expected != aimed:
                # Nest best: sanntidsestimat (avviker fra planlagt)
                expected_dt = datetime.fromisoformat(expected)
                delay_seconds = (expected_dt - aimed_dt).total_seconds()
                delay_source = "expected"
            else:
                # Verst: ingen sanntidsdata, antar i rute
                delay_seconds = 0.0
                delay_source = "planned"
        except (ValueError, TypeError):
            delay_seconds = 0.0
            delay_source = "error"

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
            "delaySource": delay_source,
            "scrapedAt": scraped_at,
        })

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


def smart_dedup(df_all, dedupe_keys):
    """
    Intelligent deduplisering som beholder den mest presise målingen.

    Prioriteringsrekkefølge (best først):
      1. Rader med actualDeparture (faktisk observert)
      2. Rader med realtime=True (sanntidsestimat)
      3. Nyeste scrapedAt (mest oppdatert)

    Dette forhindrer at en presis måling (med actualDepartureTime)
    overskrives av en senere scrape der API-et allerede har begynt
    å rydde data.
    """
    before = len(df_all)

    # Opprett sorteringskolonner for prioritering
    df_all["_has_actual"] = df_all["actualDeparture"].notna() & (df_all["actualDeparture"] != "")
    df_all["_is_realtime"] = df_all["realtime"].astype(str).str.lower() == "true"

    # Sorter: actual først, deretter realtime, deretter nyeste scrape
    df_all = df_all.sort_values(
        by=["_has_actual", "_is_realtime", "scrapedAt"],
        ascending=[False, False, False],
    )

    # Behold den første (= beste) per unik kombinasjon
    df_all = df_all.drop_duplicates(subset=dedupe_keys, keep="first")

    # Rydd opp midlertidige kolonner
    df_all = df_all.drop(columns=["_has_actual", "_is_realtime"])

    after = len(df_all)
    print(f"  Smart dedup: {before} → {after} rader ({before - after} duplikater fjernet)")

    return df_all


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

    # ── Beregn dynamisk tidsvindu ──
    now = datetime.now(OSLO_TZ)
    master_path = os.path.join(script_dir, "forsinkelser_master.csv")
    last_scraped = get_last_scraped_time(master_path)

    if last_scraped is not None:
        # Dynamisk: dekk fra 15 min FØR siste scrape (overlap for sikkerhet)
        gap_start = last_scraped - timedelta(minutes=15)
        lookback_seconds = int((now - gap_start).total_seconds())

        # Begrens til maks — API-et har uansett slettet data etter ~2-3 timer
        lookback_seconds = min(lookback_seconds, MAX_LOOKBACK_SECONDS)

        gap_minutes = int((now - last_scraped).total_seconds() / 60)
        print(f"\nSiste scrape: {last_scraped.isoformat()} ({gap_minutes} min siden)")
        print(f"Dynamisk tidsvindu: {lookback_seconds}s bakover + {LOOKAHEAD_SECONDS}s fremover")
    else:
        lookback_seconds = DEFAULT_LOOKBACK_SECONDS
        print(f"\nIngen tidligere scrape funnet — bruker standard {lookback_seconds}s bakover")

    start_time = now - timedelta(seconds=lookback_seconds)
    start_time_str = start_time.isoformat()
    time_range = lookback_seconds + LOOKAHEAD_SECONDS
    scraped_at = now.isoformat()

    print(f"Henter forsinkelsesdata fra {start_time_str} (timeRange={time_range}s) …")
    print(f"Batcher: {(len(station_ids) + BATCH_SIZE - 1) // BATCH_SIZE} (à {BATCH_SIZE} stasjoner)\n")

    t0 = time.time()
    rows = fetch_delays(station_ids, start_time_str, time_range, scraped_at)
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
        "serviceJourneyId", "realtime", "delaySource", "scrapedAt",
    ]

    df_new = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)

    # Kvalitetsstatistikk
    n_actual = (df_new["delaySource"] == "actual").sum()
    n_expected = (df_new["delaySource"] == "expected").sum()
    n_planned = (df_new["delaySource"] == "planned").sum()
    print(f"\nDatakvalitet: {n_actual} actual, {n_expected} expected, {n_planned} planned")

    # Snapshot (overskrives hver gang)
    snapshot_path = os.path.join(script_dir, "forsinkelser_siste_kjoring.csv")
    df_new.to_csv(snapshot_path, index=False, encoding="utf-8")
    print(f"Snapshot lagret: {snapshot_path} ({len(df_new)} rader)")

    # Master (akkumuleres)
    if os.path.exists(master_path):
        df_master = pd.read_csv(master_path)
        df_master = df_master.loc[:, ~df_master.columns.str.contains("^Unnamed")]
    else:
        df_master = pd.DataFrame(columns=EXPECTED_COLUMNS)

    # Legg til manglende kolonner (bakoverkompatibilitet)
    for col in EXPECTED_COLUMNS:
        if col not in df_master.columns:
            df_master[col] = pd.NA

    df_all = pd.concat([df_master, df_new], ignore_index=True)

    # Smart deduplisering — behold mest presise måling
    dedupe_keys = ["stationId", "scheduledDeparture", "serviceJourneyId"]
    df_all = smart_dedup(df_all, dedupe_keys)

    df_all.to_csv(master_path, index=False, encoding="utf-8")
    print(f"Master lagret: {master_path} ({len(df_all)} rader)")


if __name__ == "__main__":
    main()
