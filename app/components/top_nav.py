"""Toppnavigasjon for Togforsinkelser-appen."""

import streamlit as st


# (filsti, etikett, ikon) for navigasjonslenkene, i visningsrekkefølge.
_NAV_ITEMS = [
    ("Togforsinkelser.py", "Kart", "🗺️"),
    ("pages/1_Oversikt.py", "Oversikt", None),
    ("pages/2_Last_ned_data.py", "Last ned", None),
]


def render_top_nav(active_page, *, show_icons=True, show_brand_emoji=True):
    """Rendrer horisontal navigasjon på toppen av alle sider."""
    st.markdown('<div class="top-nav-shell">', unsafe_allow_html=True)

    brand_col, nav1_col, nav2_col, download_col = st.columns([2.4, 1, 1, 1.2])

    with brand_col:
        brand_text = "🚆 Togforsinkelser" if show_brand_emoji else "Togforsinkelser"
        st.markdown(
            f'<div class="top-nav-brand">{brand_text}</div>',
            unsafe_allow_html=True,
        )

    for col, (path, label, icon) in zip([nav1_col, nav2_col, download_col], _NAV_ITEMS):
        with col:
            st.page_link(
                path,
                label=label,
                icon=icon if show_icons else None,
                use_container_width=True,
            )

    st.markdown(
        f'<div class="top-nav-active">Aktiv side: {active_page}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
