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

# --- Transport type config ---
TRANSPORT_CONFIG = {
    "bus":    {"label": "🚌 Buss",            "color": "#2ca02c"},
    "coach":  {"label": "🚌 Buss (ekspress)",  "color": "#2ca02c"},
    "rail":   {"label": "🚆 Tog",             "color": "#1f77b4"},
    "tram":   {"label": "🚋 Trikk",           "color": "#9467bd"},
    "metro":  {"label": "🚇 T-bane",          "color": "#ff7f0e"},
    "ferry":  {"label": "⛴️ Ferge",           "color": "#17becf"},
    "water":  {"label": "⛴️ Båt",            "color": "#17becf"},
    "air":    {"label": "✈️ Fly",             "color": "#d62728"},
    "taxi":   {"label": "🚕 Taxi",            "color": "#e7ba52"},
    "NA":     {"label": "❓ Ukjent",          "color": "#7f7f7f"},
}

# Canonical display order
MODE_ORDER = ["bus", "coach", "rail", "tram", "metro", "ferry", "water", "air", "taxi", "NA"]


if df.empty:
    st.info("Fant ikke rutedata ennå. Kjør 'hent_alle_ruter.py' først.")
else:
    # --- Sidebar ---
    st.sidebar.header("🔎 Filtre")

    # --- Operatør filter (compact expander) ---
    operators = sorted(df["operatorName"].dropna().unique().tolist()) if "operatorName" in df.columns else []

    with st.sidebar.expander("🏢 Operatør (selskap)", expanded=False):
        col_all, col_none = st.columns(2)
        if col_all.button("Alle", key="op_all", use_container_width=True):
            st.session_state["selected_ops"] = operators
        if col_none.button("Ingen", key="op_none", use_container_width=True):
            st.session_state["selected_ops"] = []

        if "selected_ops" not in st.session_state:
            st.session_state["selected_ops"] = operators

        selected_operators = []
        for op in operators:
            checked = op in st.session_state["selected_ops"]
            if st.checkbox(op, value=checked, key=f"op_{op}"):
                selected_operators.append(op)

    # --- Transport type toggle panel ---
    modes_in_data = sorted(df["transportMode"].fillna("NA").unique().tolist()) if "transportMode" in df.columns else ["NA"]
    # Sort by canonical order
    modes_sorted = [m for m in MODE_ORDER if m in modes_in_data] + [m for m in modes_in_data if m not in MODE_ORDER]

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🚦 Transporttype")

    # "Velg alle / Ingen" shortcut buttons at top level
    col_a, col_b = st.sidebar.columns(2)
    if col_a.button("✅ Alle typer", key="mode_all", use_container_width=True):
        for m in modes_sorted:
            st.session_state[f"mode_{m}"] = True
    if col_b.button("❌ Ingen typer", key="mode_none", use_container_width=True):
        for m in modes_sorted:
            st.session_state[f"mode_{m}"] = False

    selected_modes = []
    for mode in modes_sorted:
        cfg = TRANSPORT_CONFIG.get(mode, {"label": mode, "color": "#7f7f7f"})
        key = f"mode_{mode}"
        if key not in st.session_state:
            st.session_state[key] = True
        checked = st.sidebar.checkbox(
            cfg["label"],
            value=st.session_state[key],
            key=key,
        )
        if checked:
            selected_modes.append(mode)

    # --- Route selection per group (expanders) ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🗂️ Velg ruter per gruppe")

    selected_route_ids = []

    if not selected_modes:
        st.sidebar.warning("Velg minst én transporttype for å vise ruter.")
    else:
        for mode in modes_sorted:
            if mode not in selected_modes:
                continue

            cfg = TRANSPORT_CONFIG.get(mode, {"label": mode, "color": "#7f7f7f"})
            mode_label = cfg["label"]
            mode_color = cfg["color"]

            # Filter df for this mode (and selected operators)
            df_mode = df.copy()
            if selected_operators and "operatorName" in df_mode.columns:
                df_mode = df_mode[df_mode["operatorName"].isin(selected_operators)]
            if "transportMode" in df_mode.columns:
                df_mode = df_mode[df_mode["transportMode"].fillna("NA") == mode]

            if df_mode.empty:
                continue

            with st.sidebar.expander(f"{mode_label} ({len(df_mode)} ruter)", expanded=False):
                col_a2, col_b2 = st.columns(2)
                show_all_key = f"show_all_{mode}"
                if show_all_key not in st.session_state:
                    st.session_state[show_all_key] = True

                if col_a2.button("Alle", key=f"all_{mode}", use_container_width=True):
                    st.session_state[show_all_key] = True
                    for _, row in df_mode.iterrows():
                        st.session_state[f"route_{row['id']}"] = True
                if col_b2.button("Ingen", key=f"none_{mode}", use_container_width=True):
                    st.session_state[show_all_key] = False
                    for _, row in df_mode.iterrows():
                        st.session_state[f"route_{row['id']}"] = False

                for _, row in df_mode.sort_values("publicCode" if "publicCode" in df_mode.columns else "id").iterrows():
                    rid = str(row.get("id"))
                    public = str(row.get("publicCode", "")).strip() if pd.notna(row.get("publicCode")) else ""
                    name = str(row.get("name", "")).strip() if pd.notna(row.get("name")) else ""
                    op = str(row.get("operatorName", "")).strip() if pd.notna(row.get("operatorName")) else ""

                    label_parts = [x for x in [public, name] if x]
                    label = " – ".join(label_parts) if label_parts else rid
                    if op:
                        label += f" ({op})"

                    route_key = f"route_{rid}"
                    if route_key not in st.session_state:
                        st.session_state[route_key] = st.session_state.get(show_all_key, True)

                    if st.checkbox(label, value=st.session_state[route_key], key=route_key):
                        selected_route_ids.append(rid)

    selected_route_ids = sorted(set(selected_route_ids))

    if selected_route_ids:
        df_filtered = df[df["id"].astype(str).isin(selected_route_ids)].copy()
    else:
        df_filtered = df.iloc[0:0].copy()

    # Ryddig kolonnerekkefølge
    for col in ["id", "publicCode", "name", "transportMode", "operatorName"]:
        if col not in df_filtered.columns:
            df_filtered[col] = pd.NA

    df_filtered = df_filtered[["id", "publicCode", "name", "transportMode", "operatorName"]]

    st.metric("Antall ruter i utvalget", len(df_filtered))

    # Color-coded transport mode badge in dataframe using column config
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
