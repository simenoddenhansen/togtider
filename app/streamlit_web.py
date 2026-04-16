import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os

st.set_page_config(page_title="Togforsinkelser Oslo-Sandvika", layout="wide")

st.title("Togforsinkelser: Oslo S ➔ Sandvika 🚂")

# Finn riktig sti til CSV-filen
# Vi bruker ../ for å gå opp fra /app/-mappen til rotmappen
CSV_PATH = "Alle_reiser_Oslo_Sandvika.csv"

@st.cache_data(ttl=600)
def load_data():
    if not os.path.exists(CSV_PATH):
        st.error(f"Fant ikke filen: {CSV_PATH}. Sjekk at banen er riktig!")
        return pd.DataFrame()
    
    df = pd.read_csv(CSV_PATH)
    df['scheduledDeparture'] = pd.to_datetime(df['scheduledDeparture'])
    return df

df = load_data()

if not df.empty:
    # Nøkkeltall i kolonner
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Totale avganger", len(df))
    with col2:
        st.metric("Forsinkede tog", int(df['isDelayed'].sum()))
    with col3:
        avg_delay = round(df['delaySeconds'].mean() / 60, 1)
        st.metric("Snitt forsinkelse", f"{avg_delay} min")

    # Diagram
    st.subheader("Gjennomsnittlig forsinkelse per destinasjon")
    chart_data = df.groupby('destination')['delaySeconds'].mean() / 60
    st.bar_chart(chart_data)

    # Tabell
    st.subheader("Siste registrerte avganger")
    st.dataframe(df.sort_values(by='scheduledDeparture', ascending=False), use_container_width=True)
else:
    st.info("Venter på første datainnsamling eller feil i filsti.")
