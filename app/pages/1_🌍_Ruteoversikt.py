import os
import html
import json
import requests
import pandas as pd
import streamlit as st
import pydeck as pdk

st.set_page_config(page_title="Ruteoversikt", page_icon="🌍", layout="wide")

st.title("🌍 Norske Kollektivruter")
st.caption(
    "Dette er en komplett oversikt over alle registrerte linjer i Entur-systemet.")

# Finn stien til CSV-filen (ligger i roten av prosjektet under ruteData/)
current_dir = os.path.dirname(os.path.abspath(__file__))
# current_dir er app/pages, så vi må to hakk opp:
project_root = os.path.dirname(os.path.dirname(current_dir))
csv_path = os.path.join(project_root, "ruteData", "Alle ruter.csv")

# --- API config ---
API_URL = "https://api.entur.io/journey-planner/v3/graphql"
API_HEADERS = {
    "ET-Client-Name": "simenoddenhansen-togtider_dev",
    "Content-Type": "application/json",
}

MAX_MAP_ROUTES = 15  # Begrens antall ruter på kart for ytelse


@st.cache_data
def load_routes(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


@st.cache_data(ttl=600)
def fetch_route_geometry(line_id):
    """Henter stoppesteder (quays) for en linje fra Entur API."""
    query = """
    query ($lineId: ID!) {
      line(id: $lineId) {
        id
        name
        transportMode
        journeyPatterns {
          quays {
            name
            latitude
            longitude
          }
        }
      }
    }
    """
    try:
        r = requests.post(
            API_URL,
            json={"query": query, "variables": {"lineId": line_id}},
            headers=API_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        line = data.get("data", {}).get("line")
        if not line:
            return None

        # Velg journey pattern med flest stopp (typisk lengst rute)
        best_pattern = None
        best_count = 0
        for jp in line.get("journeyPatterns", []):
            quays = jp.get("quays", [])
            valid = [q for q in quays if q.get("latitude") and q.get("longitude")]
            if len(valid) > best_count:
                best_count = len(valid)
                best_pattern = valid

        if not best_pattern or best_count < 2:
            return None

        return {
            "name": line.get("name", ""),
            "mode": line.get("transportMode", ""),
            "stops": best_pattern,
        }
    except Exception:
        return None


df = load_routes(csv_path)

# --- Transport type config ---
TRANSPORT_CONFIG = {
    "bus":    {"label": "🚌 Buss",            "color": "#2ca02c",  "rgb": [44, 160, 44]},
    "coach":  {"label": "🚌 Buss (ekspress)",  "color": "#2ca02c",  "rgb": [44, 160, 44]},
    "rail":   {"label": "🚆 Tog",             "color": "#1f77b4",  "rgb": [31, 119, 180]},
    "tram":   {"label": "🚋 Trikk",           "color": "#9467bd",  "rgb": [148, 103, 189]},
    "metro":  {"label": "🚇 T-bane",          "color": "#ff7f0e",  "rgb": [255, 127, 14]},
    "ferry":  {"label": "⛴️ Ferge",           "color": "#17becf",  "rgb": [23, 190, 207]},
    "water":  {"label": "⛴️ Båt",            "color": "#17becf",  "rgb": [23, 190, 207]},
    "air":    {"label": "✈️ Fly",             "color": "#d62728",  "rgb": [214, 39, 40]},
    "taxi":   {"label": "🚕 Taxi",            "color": "#e7ba52",  "rgb": [231, 186, 82]},
    "NA":     {"label": "❓ Ukjent",          "color": "#7f7f7f",  "rgb": [127, 127, 127]},
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
        cfg = TRANSPORT_CONFIG.get(mode, {"label": mode, "color": "#7f7f7f", "rgb": [127, 127, 127]})
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

            cfg = TRANSPORT_CONFIG.get(mode, {"label": mode, "color": "#7f7f7f", "rgb": [127, 127, 127]})
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

    # ─────────────────────────────────────────────────────────────
    # 🗺️ Rutekart — viser valgte ruter på kart
    # ─────────────────────────────────────────────────────────────

    st.markdown("---")
    st.subheader("🗺️ Rutekart")

    if df_filtered.empty:
        st.info("Velg ruter i filterpanelet for å vise dem på kartet.")
    elif len(df_filtered) > MAX_MAP_ROUTES:
        st.warning(
            f"For mange ruter valgt ({len(df_filtered)}). "
            f"Velg maksimalt {MAX_MAP_ROUTES} ruter for å vise dem på kartet. "
            f"Bruk filtrene i sidepanelet for å begrense utvalget."
        )
    else:
        with st.spinner("Henter rutegeometri fra Entur …"):
            path_data = []    # for lines
            scatter_data = [] # for stop markers

            for _, row in df_filtered.iterrows():
                line_id = str(row["id"])
                mode = str(row.get("transportMode", "NA"))
                cfg = TRANSPORT_CONFIG.get(mode, {"rgb": [127, 127, 127], "label": mode})
                rgb = cfg["rgb"]

                geometry = fetch_route_geometry(line_id)
                if geometry is None:
                    continue

                stops = geometry["stops"]
                route_label = geometry["name"] or line_id

                # Build line segments between consecutive stops
                for i in range(len(stops) - 1):
                    s1 = stops[i]
                    s2 = stops[i + 1]
                    path_data.append({
                        "from_lat": s1["latitude"],
                        "from_lng": s1["longitude"],
                        "to_lat": s2["latitude"],
                        "to_lng": s2["longitude"],
                        "color": rgb,
                        "route": route_label,
                    })

                # Stop markers
                for s in stops:
                    scatter_data.append({
                        "lat": s["latitude"],
                        "lng": s["longitude"],
                        "name": s.get("name", ""),
                        "route": route_label,
                        "color": rgb + [200],
                        "mode": mode,
                    })

        if not path_data:
            st.info("Kunne ikke hente rutegeometri for valgte ruter.")
        else:
            # Build pydeck layers
            line_layer = pdk.Layer(
                "LineLayer",
                data=path_data,
                get_source_position=["from_lng", "from_lat"],
                get_target_position=["to_lng", "to_lat"],
                get_color="color",
                get_width=3,
                width_min_pixels=2,
                pickable=True,
            )

            scatter_layer = pdk.Layer(
                "ScatterplotLayer",
                data=scatter_data,
                get_position=["lng", "lat"],
                get_fill_color="color",
                get_radius=300,
                radius_min_pixels=3,
                radius_max_pixels=8,
                pickable=True,
            )

            # Center the map on the data
            all_lats = [d["lat"] for d in scatter_data]
            all_lngs = [d["lng"] for d in scatter_data]
            center_lat = sum(all_lats) / len(all_lats)
            center_lng = sum(all_lngs) / len(all_lngs)

            # Estimate zoom from spread
            lat_spread = max(all_lats) - min(all_lats)
            lng_spread = max(all_lngs) - min(all_lngs)
            spread = max(lat_spread, lng_spread)
            if spread > 10:
                zoom = 4
            elif spread > 5:
                zoom = 5
            elif spread > 2:
                zoom = 6
            elif spread > 1:
                zoom = 7
            elif spread > 0.5:
                zoom = 8
            elif spread > 0.1:
                zoom = 10
            else:
                zoom = 12

            view_state = pdk.ViewState(
                latitude=center_lat,
                longitude=center_lng,
                zoom=zoom,
                pitch=0,
            )

            deck = pdk.Deck(
                layers=[line_layer, scatter_layer],
                initial_view_state=view_state,
                tooltip={
                    "html": "<b>{name}</b><br/>Rute: {route}",
                    "style": {
                        "backgroundColor": "#1a1a2e",
                        "color": "white",
                        "fontSize": "12px",
                        "padding": "8px",
                        "borderRadius": "6px",
                    },
                },
                map_style="mapbox://styles/mapbox/dark-v11",
            )

            st.pydeck_chart(deck, use_container_width=True)

            st.caption(
                f"Viser {len(df_filtered)} ruter med "
                f"{len(scatter_data)} stoppesteder og "
                f"{len(path_data)} linjestrekninger."
            )


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
