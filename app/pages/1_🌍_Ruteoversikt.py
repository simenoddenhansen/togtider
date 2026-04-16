import os
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Ruteoversikt", page_icon="🌍", layout="wide")

st.title("🌍 Norske Kollektivruter")
st.caption("Dette er en komplett oversikt over alle registrerte linjer i Entur-systemet.")

# Finn stien til CSV-filen (ligger i roten av prosjektet under ruteData/)
current_dir = os.path.dirname(os.path.abspath(__file__))
# current_dir er app/pages, så vi må to hakk opp:
project_root = os.path.dirname(os.path.dirname(current_dir))
csv_path = os.path.join(project_root, "ruteData", "Alle ruter.csv")

@st.cache_data
def load_routes(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)

df = load_routes(csv_path)

if df.empty:
    st.info("Fant ikke rutedata ennå. Kjør 'hent_alle_ruter.py' først.")
else:
    st.sidebar.header("Filtre")
    
    # Filter for Transport Mode
    modes = sorted(df["transportMode"].dropna().unique().tolist())
    selected_modes = st.sidebar.multiselect("Transportmiddel", modes, default=["rail"])
    
    # Filter for Operator
    operators = sorted(df["operatorName"].dropna().unique().tolist())
    selected_operators = st.sidebar.multiselect("Operatør (Selskap)", operators, default=operators)
    
    df_filtered = df.copy()
    
    if selected_modes:
        df_filtered = df_filtered[df_filtered["transportMode"].isin(selected_modes)]
        
    if selected_operators:
        df_filtered = df_filtered[df_filtered["operatorName"].isin(selected_operators)]

    st.metric("Antall ruter i utvalget", len(df_filtered))
    
    # Vis tabell
    st.dataframe(df_filtered, use_container_width=True, hide_index=True)

# --- ENTUR RETNINGSLINJER OG KREDITERING ---
st.markdown("---")
col_logo, col_text = st.columns([1, 5])

with col_logo:
    st.image("https://upload.wikimedia.org/wikipedia/commons/e/e0/Entur_logo.svg", width=80)

with col_text:
    st.markdown("**Data gjort tilgjengelig av Entur**")
    st.caption("Dataene publiseres under Norsk lisens for offentlige data (NLOD).")
