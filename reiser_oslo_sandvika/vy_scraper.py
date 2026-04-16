import requests
import json
from datetime import datetime, date, timedelta
import pandas as pd
import os
import signal
import pytz

## Info om dataene:
#  https://enturas.atlassian.net/wiki/spaces/PUBLIC/pages/637370392/SIRI-ET
#  https://developer.entur.org/pages-journeyplanner-journeyplanner

## Dette er API-inngangen til dataene våre. De har laget API med GraphQL
    ## https://developer.entur.org/pages-journeyplanner-journeyplanner

url = "https://api.entur.io/journey-planner/v3/graphql" 

# Vi ønsker å hente data for den siste timen.
# Tvinger GitHub-serveren til å bruke norsk tid (Europe/Oslo) i stedet for serverens UTC-tid.
oslo_tz = pytz.timezone("Europe/Oslo")
now = datetime.now(oslo_tz)
one_hour_ago = now - timedelta(hours=1)
start = one_hour_ago.replace(minute=0, second=0, microsecond=0)

# Formatter starttidspunktet i ISO 8601-format
start_time_str = start.strftime('%Y-%m-%dT%H:%M:%S%z')
# Legger inn et kolon i tidsforskyvningen (f.eks. +0200 -> +02:00) som Entur krever
start_time_str = start_time_str[:-2] + ':' + start_time_str[-2:]

query = f"""
  query{{
    stopPlace(id: "NSR:StopPlace:610") {{
      estimatedCalls(startTime: "{start_time_str}", timeRange: 6400, numberOfDepartures: 2000) {{
          date
          realtime
          aimedArrivalTime
          expectedArrivalTime
          actualArrivalTime
          aimedDepartureTime
          expectedDepartureTime
          actualDepartureTime
          destinationDisplay {{
              frontText
              }}
          serviceJourney {{
              id
              journeyPattern {{
                  line {{
                      id
                      name
                      transportMode
                  }}
              }}
          }}
      }}
    }}
  }}
"""

headers = {
    "Content-Type": "application/json",
    "ET-Client-Name": "vy-delay-checker"
}

## Setter et timeout som gjør at scriptet avslutter seg selv etter 10 minutter
def timeout_handler(signum, frame):
    print("Script timeout: execution exceeded 10 minutes, exiting gracefully")
    exit(0)

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(600)  # 10 min

# Parse as JSON - Dette er vår behandling av de dataene vi har bedt om fra API-kallet.
try:
    response = requests.post(url, json={"query": query}, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        print("GraphQL returned errors:")
        print(json.dumps(data["errors"], indent=2))

    departures_raw = (
        data.get("data", {})
        .get("stopPlace", {})
        .get("estimatedCalls")
    )
    if departures_raw is None:
        print("Response did not include expected data. Here's what we got:")
        print(json.dumps(data, indent=2))
        departures_raw = []

    expected_columns = [
        "scheduledDeparture",
        "actualDeparture",
        "isDelayed",
        "delaySeconds",
        "destination",
        "routeId",
        "routeName",
        "transportMode",
        "serviceJourneyId",
    ]

    rows = []
    for dep in departures_raw:
        aimed = dep.get("aimedDepartureTime")
        if aimed is None:
            continue

        # Håndtere at faktisk avreisetid gir None hvis den er presis.
        actual = dep.get("actualDepartureTime") or aimed

        destination = (dep.get("destinationDisplay") or {}).get("frontText")
        if destination not in ["Skien", "Spikkestad", "Kongsberg", "Drammen", "Asker"]:
            continue

        service_journey = dep.get("serviceJourney") or {}
        service_journey_id = service_journey.get("id")

        line = (
            (service_journey.get("journeyPattern") or {})
            .get("line")
        ) or {}

        route_id = line.get("id")
        route_name = line.get("name")
        transport_mode = line.get("transportMode")

        # Parser tidspunktene til datetime-objekter for å kunne kalkulere forsinkelse
        aimed_dt = datetime.fromisoformat(aimed)
        actual_dt = datetime.fromisoformat(actual)

        # Kalkuler forsinkelse i sekunder, og marker som forsinket hvis den er mer enn 0 sekunder
        delay_seconds = (actual_dt - aimed_dt).total_seconds()
        is_delayed = int(delay_seconds > 0)

        rows.append({
            "scheduledDeparture": aimed,
            "actualDeparture": actual,
            "isDelayed": is_delayed,
            "delaySeconds": delay_seconds,
            "destination": destination,
            "routeId": route_id,
            "routeName": route_name,
            "transportMode": transport_mode,
            "serviceJourneyId": service_journey_id,
        })

    df_new = pd.DataFrame(rows, columns=expected_columns)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    kildefil = os.path.join(script_dir, "OsloS_til_Sandvika_reiser_siste_timen.csv")
    masterfil = os.path.join(script_dir, "Alle_reiser_Oslo_Sandvika.csv")

    # Always write the last-hour file (even if empty) to keep the schema consistent
    df_new.to_csv(kildefil, index=False)

    # Master-file update with schema migration (preserve old rows and add new columns as NA)
    if os.path.exists(masterfil):
        df_master = pd.read_csv(masterfil)
        df_master = df_master.loc[:, ~df_master.columns.str.contains('^Unnamed')]
    else:
        df_master = pd.DataFrame()

    # Add missing columns to both frames
    for col in expected_columns:
        if col not in df_master.columns:
            df_master[col] = pd.NA

    for col in df_master.columns:
        if col not in df_new.columns:
            df_new[col] = pd.NA

    combined_columns = list(dict.fromkeys(list(df_master.columns) + list(df_new.columns)))
    df_master = df_master.reindex(columns=combined_columns)
    df_new = df_new.reindex(columns=combined_columns)

    df_all = pd.concat([df_master, df_new], ignore_index=True)

    # De-dupe (keep first seen) while avoiding accidental drops when IDs exist
    dedupe_keys = ["scheduledDeparture", "destination"]
    for extra_key in ["routeId", "serviceJourneyId"]:
        if extra_key in df_all.columns:
            dedupe_keys.append(extra_key)

    df_all = df_all.drop_duplicates(subset=dedupe_keys)
    df_all.to_csv(masterfil, index=False)

except (requests.RequestException, json.JSONDecodeError) as e:
    print("Failed to fetch or decode data:")
    print(str(e))
    if 'response' in locals():
        print("Response text:")
        print(response.text)
    exit()
