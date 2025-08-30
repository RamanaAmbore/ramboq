import streamlit as st

from src.about import about
from src.contact import contact
from src.faq import faq
from src.market import market
from src.performance import performance
from src.post import post
from src.signin import signin


def body(body_container):
    with body_container:
        body_container =st.empty()
        if st.session_state.active_nav == "signin":
            signin(body_container)
        elif st.session_state.active_nav == "about":
            about(body_container)
        elif st.session_state.active_nav == "market":
            market(body_container)
        elif st.session_state.active_nav == "performance":
            performance(body_container)
        elif st.session_state.active_nav == "faq":
            faq(body_container)
        elif st.session_state.active_nav == "post":
            post(body_container)
        elif st.session_state.active_nav == "contact":
            contact(body_container)
