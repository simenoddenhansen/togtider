"""
Last ned data – Dedikert nedlastingsside
────────────────────────────────────────
Lar brukeren tilpasse eksporten med kolonnevalg, tidsperiode,
rutefilter og filformat (CSV, Excel, JSON).
Viser en forhåndsvisningstabell med 30 rader der valgte kolonner
er visuelt uthevet.
"""

import io
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# Sørg for at app/-mappen er på path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_loader import (
    OSLO_TZ,
    load_delay_data,
    master_csv_path,
    get_mtime,
    filter_rail_only,
    get_unique_routes,
)
from components.footer import entur_footer
from components.responsive_css import inject_responsive_css

# ─── Norske kolonnenavn med API-variabel i parentes ───────────────
# Komplett mapping for alle kolonner i forsinkelser_master.csv

COLUMN_LABELS_FULL = {
    "stationId": "Stasjons-ID (stationId)",
    "stationName": "Stasjon (stationName)",
    "scheduledDeparture": "Planlagt avgang (scheduledDeparture)",
    "expectedDeparture": "Forventet avgang (expectedDeparture)",
    "actualDeparture": "Faktisk avgang (actualDeparture)",
    "delaySeconds": "Forsinkelse i sekunder (delaySeconds)",
    "isDelayed": "Forsinket 0/1 (isDelayed)",
    "destination": "Destinasjon (destination)",
    "lineId": "Linje-ID (lineId)",
    "lineName": "Linjenavn (lineName)",
    "lineCode": "Linjekode (lineCode)",
    "transportMode": "Transporttype (transportMode)",
    "serviceJourneyId": "Tjenestereise-ID (serviceJourneyId)",
    "realtime": "Sanntidsdata (realtime)",
    "delaySource": "Forsinkelseskilde (delaySource)",
    "scrapedAt": "Innsamlet kl. (scrapedAt)",
}


# ─── Sidekonfigurasjon ────────────────────────────────────────────

st.set_page_config(page_title="Last ned data", page_icon="📥", layout="wide")

inject_responsive_css()

st.title("📥 Last ned data")
st.markdown(
    "Tilpass eksporten av togforsinkelsesdata. Velg kolonner, "
    "tidsperiode, ruter og filformat før nedlasting."
)

# ─── Last data ────────────────────────────────────────────────────

MASTER_PATH = master_csv_path()
master_mtime = get_mtime(MASTER_PATH)
now_oslo = datetime.now(OSLO_TZ)

df_master = load_delay_data(MASTER_PATH, master_mtime)
df_master = filter_rail_only(df_master)

if df_master.empty:
    st.warning("Ingen data tilgjengelig ennå — vent på neste scraper-kjøring.")
    entur_footer()
    st.stop()

# ─── Eksportkonfigurasjon ─────────────────────────────────────────

st.markdown("---")

col_left, col_right = st.columns(2)

# ── Kolonnevalg ──
with col_left:
    st.subheader("📋 Velg kolonner")
    all_columns = df_master.columns.tolist()

    # Formateringsfunksjon som viser norsk label + API-variabel
    def format_column(col):
        return COLUMN_LABELS_FULL.get(col, col)

    selected_columns = st.multiselect(
        "Hvilke kolonner skal inkluderes i nedlastingen?",
        options=all_columns,
        default=all_columns,
        format_func=format_column,
        key="download_columns",
    )

    if not selected_columns:
        st.warning("⚠️ Velg minst én kolonne.")
    else:
        st.caption(f"{len(selected_columns)} av {len(all_columns)} kolonner valgt")

# ── Tidsperiode ──
with col_right:
    st.subheader("📅 Tidsperiode")

    # Hurtigvalg for tidshorisont
    time_horizon = st.radio(
        "Velg tidshorisont",
        options=["Siste 24 timer", "Siste 7 dager", "Siste 30 dager", "Egendefinert periode", "Alle data"],
        index=2,
        key="download_time_horizon",
    )

    if "scheduledDeparture" in df_master.columns:
        min_date = df_master["scheduledDeparture"].min()
        max_date = df_master["scheduledDeparture"].max()

        if pd.notna(min_date) and pd.notna(max_date):
            if time_horizon == "Siste 24 timer":
                date_start = (now_oslo - timedelta(hours=24)).date()
                date_end = now_oslo.date()
                st.caption(f"📆 {date_start} → {date_end}")
            elif time_horizon == "Siste 7 dager":
                date_start = (now_oslo - timedelta(days=7)).date()
                date_end = now_oslo.date()
                st.caption(f"📆 {date_start} → {date_end}")
            elif time_horizon == "Siste 30 dager":
                date_start = (now_oslo - timedelta(days=30)).date()
                date_end = now_oslo.date()
                st.caption(f"📆 {date_start} → {date_end}")
            elif time_horizon == "Egendefinert periode":
                date_start = st.date_input(
                    "Fra dato",
                    value=min_date.date(),
                    min_value=min_date.date(),
                    max_value=max_date.date(),
                    key="download_date_start",
                )
                date_end = st.date_input(
                    "Til dato",
                    value=max_date.date(),
                    min_value=min_date.date(),
                    max_value=max_date.date(),
                    key="download_date_end",
                )
                if date_start > date_end:
                    st.error("❌ Startdato kan ikke være etter sluttdato.")
            else:  # Alle data
                date_start = min_date.date()
                date_end = max_date.date()
                st.caption(f"📆 Hele perioden: {date_start} → {date_end}")
        else:
            date_start = None
            date_end = None
            st.info("Ingen datoinformasjon tilgjengelig i datasettet.")
    else:
        date_start = None
        date_end = None
        st.info("Kolonnen 'scheduledDeparture' finnes ikke i datasettet.")

st.markdown("---")

col_routes, col_format = st.columns(2)

# ── Rutefilter ──
with col_routes:
    st.subheader("🚆 Velg ruter")
    all_routes = get_unique_routes(df_master, sort_by="traffic")

    selected_routes = st.multiselect(
        "Hvilke ruter skal inkluderes?",
        options=all_routes,
        default=[],
        placeholder="Alle ruter (ingen filter)",
        key="download_routes",
    )

    if selected_routes:
        st.caption(f"{len(selected_routes)} av {len(all_routes)} ruter valgt")
    else:
        st.caption(f"Alle {len(all_routes)} ruter inkludert")

# ── Filformat ──
with col_format:
    st.subheader("💾 Filformat")
    file_format = st.radio(
        "Velg eksportformat",
        options=["CSV", "Excel (.xlsx)", "JSON"],
        index=0,
        key="download_format",
    )


# ─── Bygg eksport-DataFrame ──────────────────────────────────────

df_export = df_master.copy()

# Filtrer på tidsperiode
if (
    date_start is not None
    and date_end is not None
    and "scheduledDeparture" in df_export.columns
):
    start_dt = pd.Timestamp(date_start, tz=OSLO_TZ)
    end_dt = pd.Timestamp(date_end, tz=OSLO_TZ) + timedelta(days=1)
    df_export = df_export[
        (df_export["scheduledDeparture"] >= start_dt)
        & (df_export["scheduledDeparture"] < end_dt)
    ]

# Filtrer på ruter
if selected_routes and "lineName" in df_export.columns:
    df_export = df_export[df_export["lineName"].isin(selected_routes)]


# ─── Forhåndsvisningstabell (30 rader, alle kolonner, visuell markering) ──

st.markdown("---")
st.subheader("👀 Forhåndsvisning av data")

if df_export.empty:
    st.warning("Ingen data matcher filtervalgene dine. Juster filtrene og prøv igjen.")
else:
    # Vis de siste 30 datapunktene med ALLE kolonner synlige
    if "scheduledDeparture" in df_export.columns:
        df_preview = df_export.sort_values("scheduledDeparture", ascending=False).head(30)
    else:
        df_preview = df_export.tail(30)

    n_total = len(df_export)
    n_preview = len(df_preview)

    selected_set = set(selected_columns) if selected_columns else set()

    st.caption(
        f"Viser de **{n_preview} nyeste** datapunktene av totalt "
        f"**{n_total:,}** rader. ".replace(",", " ")
        + "Kolonner markert med ✅ er valgt for nedlasting, ⬜ er ekskludert."
    )

    # Gi kolonnene norske overskrifter med ✅/⬜ markering for valgt/ikke-valgt
    preview_labels = {}
    for col in df_preview.columns:
        norsk = COLUMN_LABELS_FULL.get(col, col)
        # Fjern den engelske variabelen fra visningen — bruk kort norsk label
        short_label = norsk.split(" (")[0] if " (" in norsk else norsk
        marker = "✅" if col in selected_set else "⬜"
        preview_labels[col] = f"{marker} {short_label}"

    df_display = df_preview.rename(columns=preview_labels)

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        height=min(n_preview * 38 + 40, 800),
    )

    # Vis info om hva som faktisk lastes ned
    if selected_columns:
        cols_in = len(selected_columns)
        cols_out = len(all_columns) - cols_in
        st.info(
            f"📦 **Nedlastingen vil inneholde:** {n_total:,} rader × "
            f"{cols_in} kolonner".replace(",", " ")
            + (f" (ekskluderer {cols_out} kolonner)" if cols_out > 0 else "")
        )


# ─── Nedlasting ──────────────────────────────────────────────────

st.markdown("---")

if not df_export.empty and selected_columns:
    # Filtrer til kun valgte kolonner for selve eksporten
    valid_cols = [c for c in selected_columns if c in df_export.columns]
    df_download = df_export[valid_cols]

    now_str = now_oslo.strftime("%Y%m%d_%H%M")

    if file_format == "CSV":
        data_bytes = df_download.to_csv(index=False).encode("utf-8")
        file_name = f"togforsinkelser_{now_str}.csv"
        mime_type = "text/csv"

    elif file_format == "Excel (.xlsx)":
        buffer = io.BytesIO()
        try:
            df_download.to_excel(buffer, index=False, engine="openpyxl")
            data_bytes = buffer.getvalue()
            file_name = f"togforsinkelser_{now_str}.xlsx"
            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        except ImportError:
            st.error(
                "❌ Excel-eksport krever `openpyxl`-pakken. "
                "Installer med: `pip install openpyxl`"
            )
            data_bytes = None
            file_name = None
            mime_type = None

    elif file_format == "JSON":
        df_json = df_download.copy()
        for col in df_json.select_dtypes(include=["datetimetz", "datetime64"]).columns:
            df_json[col] = df_json[col].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        data_bytes = df_json.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
        file_name = f"togforsinkelser_{now_str}.json"
        mime_type = "application/json"

    if data_bytes is not None:
        st.download_button(
            label=f"📥 Last ned {file_format} ({len(df_download):,} rader)".replace(",", " "),
            data=data_bytes,
            file_name=file_name,
            mime=mime_type,
            type="primary",
        )
else:
    if not selected_columns:
        st.warning("Velg minst én kolonne for å aktivere nedlasting.")
    else:
        st.warning("Ingen data å laste ned med gjeldende filtre.")


# ─── Footer ──────────────────────────────────────────────────────

entur_footer()
