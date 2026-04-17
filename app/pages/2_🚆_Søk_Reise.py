import streamlit as st
import requests
import datetime

st.set_page_config(page_title="Reisesøk", page_icon="🚆", layout="centered")
st.title("🚆 Finn neste reise")
st.markdown("Søk etter reiser i hele Norge, direkte fra Entur.")

# --- API Konfigurasjon ---
GEOCODER_API_URL = "https://api.entur.io/geocoder/v1/autocomplete"
JOURNEY_API_URL = "https://api.entur.io/journey-planner/v3/graphql"
HEADERS = {
    "ET-Client-Name": "simenoddenhansen-togtider_dev",
    "Content-Type": "application/json"
}

# --- Hjelpefunksjoner ---


@st.cache_data(ttl=300)
def get_station_suggestions(query_text: str):
    """Søker opp stasjoner/steder basert på tekst og returnerer en ordbok med forslag."""
    if not query_text.strip():
        return {}

    params = {"text": query_text, "size": 15, "lang": "no"}
    try:
        response = requests.get(
            GEOCODER_API_URL, params=params, headers={
                "ET-Client-Name": HEADERS["ET-Client-Name"]})
        data = response.json()

        suggestions = {}
        for feature in data.get("features", []):
            label = feature["properties"]["label"]
            station_id = feature["properties"]["id"]
            if label not in suggestions:
                suggestions[label] = station_id
        return suggestions
    except Exception as e:
        st.error(f"Feil ved oppslag av stasjoner: {e}")
        return {}


TRIP_QUERY = """
query GetTrip($fromId: String!, $toId: String!) {
  trip(
    from: {place: $fromId}
    to: {place: $toId}
    numTripPatterns: 5
  ) {
    tripPatterns {
      expectedStartTime
      expectedEndTime
      duration
      legs {
        mode
        distance
        line {
          id
          publicCode
          name
        }
        fromPlace {
          name
        }
        toPlace {
          name
        }
        situations {
          summary {
            value
          }
          description {
            value
          }
        }
      }
    }
  }
}
"""


def fetch_journeys(from_id: str, to_id: str):
    """Henter reiseforslag mellom to ID-er."""
    payload = {
        "query": TRIP_QUERY,
        "variables": {
            "fromId": from_id,
            "toId": to_id
        }
    }
    try:
        response = requests.post(
            JOURNEY_API_URL,
            json=payload,
            headers=HEADERS)
        return response.json()
    except Exception as e:
        st.error(f"Feil ved henting av reise: {e}")
        return None


# --- UI Layout ---
st.markdown("### 1. Velg stasjoner")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Fra:**")
    from_query = st.text_input(
        "Søk (trykk Enter for å hente forslag)",
        value="Oslo S",
        key="from_query")
    from_suggestions = get_station_suggestions(from_query)
    from_options = list(from_suggestions.keys())
    if from_options:
        from_label = st.selectbox(
            "Velg eksakt sted:",
            options=from_options,
            key="from_select")
        from_id = from_suggestions.get(from_label)
    else:
        from_label = None
        from_id = None
        st.info("Ingen forslag funnet. Prøv et annet søk.")

with col2:
    st.markdown("**Til:**")
    to_query = st.text_input(
        "Søk (trykk Enter for å hente forslag)",
        value="Sandvika",
        key="to_query")
    to_suggestions = get_station_suggestions(to_query)
    to_options = list(to_suggestions.keys())
    if to_options:
        to_label = st.selectbox(
            "Velg eksakt sted:",
            options=to_options,
            key="to_select")
        to_id = to_suggestions.get(to_label)
    else:
        to_label = None
        to_id = None
        st.info("Ingen forslag funnet. Prøv et annet søk.")

st.markdown("---")

# --- Logikk når søkeknapp trykkes ---
if st.button("Søk etter reiser 🔍", type="primary"):
    if not from_id or not to_id:
        st.warning(
            "Vennligst velg både et 'Fra'- og 'Til'-sted fra nedtrekksmenyene.")
    else:
        with st.spinner("Leter etter reiser..."):
            st.success(f"Søker reise: **{from_label}** ➡️ **{to_label}**")

            # Hent reise
            data = fetch_journeys(from_id, to_id)

            if data:
                trips = data.get(
                    "data",
                    {}).get(
                    "trip",
                    {}).get(
                    "tripPatterns",
                    [])

                if not trips:
                    st.info(
                        "Fant ingen reiser på denne strekningen i nærmeste fremtid.")
                else:
                    for i, trip in enumerate(trips):
                        # Tidsformatering
                        start_dt = datetime.datetime.fromisoformat(
                            trip["expectedStartTime"])
                        end_dt = datetime.datetime.fromisoformat(
                            trip["expectedEndTime"])
                        start_time = start_dt.strftime("%H:%M")
                        end_time = end_dt.strftime("%H:%M")
                        duration_minutes = trip["duration"] // 60

                        # Ekstraher transportmidler for overskriften
                        modes_used = []
                        for leg in trip["legs"]:
                            mode = leg.get("mode", "Gå")
                            if mode == "foot" or mode == "Gå":
                                if "🚶‍♂️" not in modes_used:
                                    modes_used.append("🚶‍♂️")
                            elif mode == "bus":
                                if "🚌" not in modes_used:
                                    modes_used.append("🚌")
                            elif mode == "rail":
                                if "🚆" not in modes_used:
                                    modes_used.append("🚆")
                            elif mode == "tram":
                                if "🚋" not in modes_used:
                                    modes_used.append("🚋")
                            elif mode == "metro":
                                if "🚇" not in modes_used:
                                    modes_used.append("🚇")
                            elif mode == "water":
                                if "⛴️" not in modes_used:
                                    modes_used.append("⛴️")
                            else:
                                if "🚏" not in modes_used:
                                    modes_used.append("🚏")

                        modes_str = " ".join(modes_used)

                        # Kort med reise-detaljer
                        with st.expander(f"Avgang kl {start_time} - Ankomst {end_time} ({duration_minutes} min) {modes_str}", expanded=(i == 0)):
                            for leg in trip["legs"]:
                                mode_raw = leg.get("mode", "Gå")

                                # Oversett mode til norsk
                                mode_translations = {
                                    "foot": "Gå",
                                    "bus": "Buss",
                                    "rail": "Tog",
                                    "tram": "Trikk",
                                    "metro": "T-bane",
                                    "water": "Båt",
                                    "air": "Fly"}
                                mode = mode_translations.get(
                                    mode_raw, mode_raw.capitalize())

                                line = leg.get(
                                    "line", {}).get(
                                    "publicCode", "") if leg.get("line") else ""

                                from_name = leg["fromPlace"]["name"]
                                to_name = leg["toPlace"]["name"]

                                # Vis etappe
                                if mode == "Gå":
                                    distance = int(leg.get("distance", 0))
                                    st.markdown(
                                        f"🚶‍♂️ **Gå** {distance} meter fra {from_name} til {to_name}")
                                else:
                                    st.markdown(
                                        f"🚆 **{mode} {line}**: {from_name} ➡️ {to_name}")

                                # Vis eventuelle avvik/situasjoner
                                situations = leg.get("situations", [])
                                for sit in situations:
                                    summary = sit.get("summary", [])
                                    if summary:
                                        st.warning(
                                            f"⚠️ **Avvik:** {summary[0].get('value')}")

                            st.markdown("---")
