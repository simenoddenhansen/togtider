import os
import html
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Ruteoversikt", page_icon="🌍", layout="wide")

st.title("🌍 Norske Kollektivruter")
st.caption(
    "Dette er en komplett oversikt over alle registrerte linjer i Entur-systemet.")

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

    operators = sorted(df["operatorName"].dropna().unique(
    ).tolist()) if "operatorName" in df.columns else []
    selected_operators = st.sidebar.multiselect(
        "Operatør (selskap)", operators, default=operators)

    modes = sorted(df["transportMode"].fillna("NA").unique(
    ).tolist()) if "transportMode" in df.columns else ["NA"]
    selected_modes = st.sidebar.multiselect(
        "Transporttype", modes, default=modes)

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Velg ruter (gruppert etter transporttype)**")

    TRANSPORT_COLORS = {
        "TRAIN": "#1f77b4",
        "RAIL": "#1f77b4",
        "METRO": "#ff7f0e",
        "TRAM": "#9467bd",
        "BUS": "#2ca02c",
        "COACH": "#2ca02c",
        "FERRY": "#17becf",
        "WATER": "#17becf",
        "AIR": "#d62728",
        "NA": "#7f7f7f",
    }

    selected_route_ids = []

    if not selected_modes:
        st.sidebar.warning("Velg minst én transporttype for å vise ruter.")
    else:
        for mode in selected_modes:
            mode_str = str(mode)
            mode_safe = html.escape(mode_str)
            mode_color = TRANSPORT_COLORS.get(mode_str, "#7f7f7f")

            st.sidebar.markdown(
                f"<div style='display:inline-block;background:{mode_color};color:white;"
                f"padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700;"
                f"margin:8px 0 4px 0'>{mode_safe}</div>", unsafe_allow_html=True, )

            df_mode = df.copy()

            # Operator-filteret gjelder for hvilke ruter som dukker opp i
            # gruppene
            if selected_operators and "operatorName" in df_mode.columns:
                df_mode = df_mode[df_mode["operatorName"].isin(
                    selected_operators)]

            if "transportMode" in df_mode.columns:
                df_mode = df_mode[df_mode["transportMode"].fillna(
                    "NA") == mode]

            if df_mode.empty:
                st.sidebar.caption(
                    "Ingen ruter i denne gruppen med valgte filtre.")
                continue

            show_all = st.sidebar.checkbox(
                "Vis alle i gruppen",
                value=True,
                key=f"show_all_{mode_str}",
            )

            if show_all:
                selected_route_ids.extend(df_mode["id"].astype(str).tolist())
            else:
                # Lag en stabil visningslabel som også er unik (inkluderer id)
                option_to_id = {}
                options = []
                for _, row in df_mode.iterrows():
                    rid = str(row.get("id"))
                    public = row.get("publicCode")
                    name = row.get("name")
                    op = row.get("operatorName")

                    public_txt = str(public) if pd.notna(
                        public) and str(public).strip() else ""
                    name_txt = str(name) if pd.notna(
                        name) and str(name).strip() else ""
                    op_txt = str(op) if pd.notna(
                        op) and str(op).strip() else ""

                    label_left = " ".join(
                        [x for x in [public_txt, name_txt] if x]).strip()
                    label_mid = f" — {op_txt}" if op_txt else ""
                    label = f"{label_left}{label_mid} ({rid})".strip()

                    options.append(label)
                    option_to_id[label] = rid

                options = sorted(options)
                selected_options = st.sidebar.multiselect(
                    "Ruter",
                    options,
                    default=[],
                    key=f"routes_{mode_str}",
                )
                selected_route_ids.extend(
                    option_to_id[o] for o in selected_options)

    selected_route_ids = sorted(set(selected_route_ids))

    if selected_route_ids:
        df_filtered = df[df["id"].astype(str).isin(selected_route_ids)].copy()
    else:
        df_filtered = df.iloc[0:0].copy()

    # Litt ryddigere kolonnerekkefølge
    for col in ["id", "publicCode", "name", "transportMode", "operatorName"]:
        if col not in df_filtered.columns:
            df_filtered[col] = pd.NA

    df_filtered = df_filtered[["id", "publicCode",
                               "name", "transportMode", "operatorName"]]

    st.metric("Antall ruter i utvalget", len(df_filtered))

    st.dataframe(df_filtered, use_container_width=True, hide_index=True)

# --- ENTUR RETNINGSLINJER OG KREDITERING ---
st.markdown("---")
col_logo, col_text = st.columns([1, 5])

with col_logo:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/e/e0/Entur_logo.svg",
        width=80)

with col_text:
    st.markdown("**Data gjort tilgjengelig av Entur**")
    st.caption("Dataene publiseres under Norsk lisens for offentlige data (NLOD).")
