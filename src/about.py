import streamlit as st

from src.utils import config


def about(body_container):
    with body_container:
        st.write(config['About'])
