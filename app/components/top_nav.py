"""Toppnavigasjon for Togforsinkelser-appen."""

import streamlit as st


def render_top_nav(active_page):
    """Rendrer horisontal navigasjon på toppen av alle sider."""
    st.markdown('<div class="top-nav-shell">', unsafe_allow_html=True)

    brand_col, home_col, map_col, download_col = st.columns([2.4, 1, 1, 1.2])

    with brand_col:
        st.markdown(
            '<div class="top-nav-brand">🚆 Togforsinkelser</div>',
            unsafe_allow_html=True,
        )
    with home_col:
        st.page_link(
            "Togforsinkelser.py",
            label="Oversikt",
            icon="📊",
            use_container_width=True,
        )
    with map_col:
        st.page_link(
            "pages/1_🗺️_Forsinkelseskart.py",
            label="Kart",
            icon="🗺️",
            use_container_width=True,
        )
    with download_col:
        st.page_link(
            "pages/2_📥_Last_ned_data.py",
            label="Last ned",
            icon="📥",
            use_container_width=True,
        )

    st.markdown(
        f'<div class="top-nav-active">Aktiv side: {active_page}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
