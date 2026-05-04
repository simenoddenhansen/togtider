"""
kpi.py — KPI-kort med visuell ramme.
"""

import streamlit as st


def styled_kpi(label, value, delta=None, delta_color="normal", caption=None):
    """Rendrer en metrikkverdi i en rammet container for visuell separasjon."""
    with st.container(border=True):
        st.metric(label, value, delta=delta, delta_color=delta_color)
        if caption:
            st.caption(caption)
