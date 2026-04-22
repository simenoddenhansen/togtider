"""
footer.py — Entur-attribusjon i footer.

Bruker tekstbasert attribusjon i stedet for logo, i tråd med NLOD-lisensen.
Den tidligere Wikimedia-lenken til Entur-logoen ga 403 Forbidden.
"""

import streamlit as st


def entur_footer():
    """Rendrer Entur-attribusjon som ren tekst med lenke."""
    st.markdown("---")
    st.markdown(
        "🚆 **Data levert av [Entur](https://entur.no)** · "
        "Publisert under [NLOD](https://data.norge.no/nlod/no/2.0). "
        "Entur påtar seg intet ansvar for konsekvenser av feil i data eller API-systemene."
    )
