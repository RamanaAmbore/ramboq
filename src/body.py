import streamlit as st

from src.about import about
from src.contact import contact
from src.market import market
from src.performance import performance
from src.update import update


def body(body_container):
    with body_container:

        if st.session_state.active_nav == "About":
            about(body_container)
        elif st.session_state.active_nav == "Market":
            market(body_container)
        elif st.session_state.active_nav == "Performance":
            performance(body_container)
        elif st.session_state.active_nav == "Update":
            update(body_container)
        elif st.session_state.active_nav == "Contact":
            contact(body_container)
