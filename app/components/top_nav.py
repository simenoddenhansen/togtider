"""Toppnavigasjon for Togforsinkelser-appen."""

import streamlit as st


def render_top_nav(active_page, *, show_icons=True, show_brand_emoji=True):
    """Rendrer horisontal navigasjon på toppen av alle sider."""
    st.markdown('<div class="top-nav-shell">', unsafe_allow_html=True)

    brand_col, home_col, map_col, download_col = st.columns([2.4, 1, 1, 1.2])

    with brand_col:
        brand_text = "🚆 Togforsinkelser" if show_brand_emoji else "Togforsinkelser"
        st.markdown(
            f'<div class="top-nav-brand">{brand_text}</div>',
            unsafe_allow_html=True,
        )
    with home_col:
        if show_icons:
            st.page_link(
                "Togforsinkelser.py",
                label="Oversikt",
                icon="📊",
                use_container_width=True,
            )
        else:
            st.page_link(
                "Togforsinkelser.py",
                label="Oversikt",
                use_container_width=True,
            )
    with map_col:
        if show_icons:
            st.page_link(
                "pages/1_🗺️_Forsinkelseskart.py",
                label="Kart",
                icon="🗺️",
                use_container_width=True,
            )
        else:
            st.page_link(
                "pages/1_🗺️_Forsinkelseskart.py",
                label="Kart",
                use_container_width=True,
            )
    with download_col:
        if show_icons:
            st.page_link(
                "pages/2_📥_Last_ned_data.py",
                label="Last ned",
                icon="📥",
                use_container_width=True,
            )
        else:
            st.page_link(
                "pages/2_📥_Last_ned_data.py",
                label="Last ned",
                use_container_width=True,
            )

    st.markdown(
        f'<div class="top-nav-active">Aktiv side: {active_page}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
