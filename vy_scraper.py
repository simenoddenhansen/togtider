import requests
import json
from datetime import datetime, date, timedelta
import pandas as pd
import os
import signal
from zoneinfo import ZoneInfo 

## Info om dataene:
#  https://enturas.atlassian.net/wiki/spaces/PUBLIC/pages/637370392/SIRI-ET
#  https://developer.entur.org/pages-journeyplanner-journeyplanner

## Dette er API-inngangen til dataene våre. De har laget API med GraphQL
    ## https://developer.entur.org/pages-journeyplanner-journeyplanner

url = "https://api.entur.io/journey-planner/v3/graphql" 

# Vi ønsker å hente data for den siste timen.
# Tvinger GitHub-serveren til å bruke norsk tid (Europe/Oslo) i stedet for serverens UTC-tid.
oslo_tz = ZoneInfo("Europe/Oslo")
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

response = requests.post(url, json={"query": query}, headers=headers)
data = response.json()
estimated_calls = data['data']['stopPlace']['estimatedCalls']

# Parse as JSON - Dette er vår behandling av de dataene vi har bedt om fra API-kallet. 

try:
    data = response.json()
    departures_raw = data["data"]["stopPlace"]["estimatedCalls"]
    rows = []  # <- Make sure this line is included!

    for dep in departures_raw:
        aimed = dep["aimedDepartureTime"]

        ## Håndtere at faktisk avreisetid gir Nonetype hvis den er presis.
        if dep["actualDepartureTime"] is None:
            actual = aimed
        else:
            actual = dep["actualDepartureTime"]

        destination = dep["destinationDisplay"]["frontText"]
        route_id = dep["serviceJourney"]["journeyPattern"]["line"]["id"]
        route_name = dep["serviceJourney"]["journeyPattern"]["line"]["name"]

        # Parser tidspunktene til datetime-objekter for å kunne kalkulere forsinkelse
        aimed_dt = datetime.fromisoformat(aimed)
        actual_dt = datetime.fromisoformat(actual)

        # Kalkuler forsinkelse i sekunder, og marker som forsinket hvis den er mer enn 0 sekunder
        delay_seconds = (actual_dt - aimed_dt).total_seconds()
        is_delayed = int(delay_seconds > 0)  # dummy: delayed if more than 60s
        if destination in ["Skien", "Spikkestad", "Kongsberg", "Drammen", "Asker"]:
            rows.append({
                "scheduledDeparture": aimed,
                "actualDeparture": actual,
                "isDelayed": is_delayed,
                "delaySeconds": delay_seconds,
                "destination": destination,
            })

    df = pd.DataFrame(rows)
    
    
    kildefil = "OsloS_til_Sandvika_reiser_siste_timen.csv"
    masterfil = "Alle_reiser_Oslo_Sandvika.csv"
    
    df.to_csv(kildefil, index=False)

    # Debugger hvis det ikke er noe data.
    if "data" not in data:
        print("Response did not include 'data'. Here's what we got:")
        print(json.dumps(data, indent=2))
        exit()

    with open(kildefil, "r") as src:
        lines = src.readlines()

    # If master file doesn't exist, create it from current data
    if not os.path.exists(masterfil):
        if len(lines) > 1:
            df.to_csv(masterfil, index=False)
            print(f"Created new master file: {masterfil}")
    else:
        # Append to existing master file
        if len(lines) > 1:
            with open(masterfil, "a") as tgt:
                tgt.writelines(lines[1:])
    
    # Fjerner duplikater i masterfilen basert på 'scheduledDeparture' og 'destination'
    df_master = pd.read_csv(masterfil)
    df_master = df_master.loc[:, ~df_master.columns.str.contains('^Unnamed')]
    df_master = df_master.drop_duplicates(subset=['scheduledDeparture', 'destination'])
    df_master.to_csv(masterfil, index=False)

except json.JSONDecodeError:
    print("Failed to decode JSON. Response text:")
    print(response.text)
    exit()
