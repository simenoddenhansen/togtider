"""
hent_alle_stasjoner.py
──────────────────────
Henter alle stoppestedsdata (StopPlace) fra Entur Journey Planner API
ved å bruke stopPlacesByBbox over hele Norge.

Lagrer resultatet som CSV: data_collection/alle_stasjoner.csv

Kjør:  python data_collection/hent_alle_stasjoner.py
"""

import os
import requests
import pandas as pd

API_URL = "https://api.entur.io/journey-planner/v3/graphql"
HEADERS = {
    "ET-Client-Name": "simenoddenhansen-togtider_dev",
    "Content-Type": "application/json",
}

# Bounding box som dekker hele Norge (inkl. Svalbard er utenfor,
# men fastlandet + Finnmark er innenfor)
NORWAY_BBOX = {
    "minimumLatitude": 57.5,
    "minimumLongitude": 4.0,
    "maximumLatitude": 71.5,
    "maximumLongitude": 31.5,
}

QUERY = """
{
  stopPlacesByBbox(
    minimumLatitude: %(minimumLatitude)s
    minimumLongitude: %(minimumLongitude)s
    maximumLatitude: %(maximumLatitude)s
    maximumLongitude: %(maximumLongitude)s
    filterByInUse: true
  ) {
    id
    name
    latitude
    longitude
    transportMode
  }
}
""" % NORWAY_BBOX


def fetch_all_stop_places():
    """Henter alle stoppesteder fra Entur bbox-API."""
    print("Henter alle stoppesteder i Norge fra Entur API …")
    response = requests.post(
        API_URL,
        json={"query": QUERY},
        headers=HEADERS,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    stops = data.get("data", {}).get("stopPlacesByBbox", [])
    print(f"Mottok {len(stops)} stoppesteder.")

    rows = []
    for stop in stops:
        transport_mode = stop.get("transportMode")
        # Noen steder har transportMode som liste, andre som streng
        if isinstance(transport_mode, list):
            transport_mode = ",".join(str(m) for m in transport_mode)

        rows.append({
            "id": stop.get("id"),
            "name": stop.get("name"),
            "latitude": stop.get("latitude"),
            "longitude": stop.get("longitude"),
            "transportMode": transport_mode,
        })

    return pd.DataFrame(rows)


def main():
    df = fetch_all_stop_places()

    if df.empty:
        print("Ingen stoppesteder funnet. Avslutter.")
        return

    # Oppsummering per transporttype
    print("\nStoppesteder per transporttype:")
    for mode, count in df["transportMode"].value_counts().items():
        print(f"  {mode}: {count}")

    # Lagre til CSV
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "alle_stasjoner.csv")
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"\nLagret {len(df)} stoppesteder til {out_path}")


if __name__ == "__main__":
    main()
