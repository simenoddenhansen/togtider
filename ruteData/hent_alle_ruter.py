import requests
import pandas as pd
import os

url = "https://api.entur.io/journey-planner/v3/graphql"
headers = {
    "ET-Client-Name": "vy-delay-checker",
    "Content-Type": "application/json"
}

# Spørringen henter alle linjer (ruter) fra Entur API. Vi inkluderer transportMode, 
# operator, name og publicCode, som er svært nyttig informasjon i togdata-sammenheng.
query = """
query {
  lines {
    id
    name
    publicCode
    transportMode
    operator {
      name
    }
  }
}
"""

print("Henter alle ruter (linjer) fra Entur API...")
response = requests.post(url, json={"query": query}, headers=headers)

if response.status_code == 200:
    data = response.json()
    lines = data.get("data", {}).get("lines", [])
    print(f"Fant {len(lines)} ruter totalt.")

    # Prossesser data inn i en liste av dicts for DataFrame
    rows = []
    for line in lines:
        operator_name = line.get("operator", {}).get(
            "name") if line.get("operator") else None
        rows.append({
            "id": line.get("id"),
            "name": line.get("name"),
            "publicCode": line.get("publicCode"),
            "transportMode": line.get("transportMode"),
            "operatorName": operator_name
        })

    # Lager DataFrame
    df = pd.DataFrame(rows)

    # Lagrer df til CSV i samme mappe som scriptet ligger i
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "Alle ruter.csv")
    df.to_csv(file_path, index=False, encoding='utf-8')
    print(f"Data lagret vellykket til {file_path}")

else:
    print(f"Kunne ikke hente data. Statuskode: {response.status_code}")
    print(response.text)
