import streamlit as st

from src.utils import config


def about(body_container):
    with body_container:
        col,_ = st.columns([1, .1],vertical_alignment="center")
        with col:
            st.write(config['About'])
