import streamlit as st

from src.utils import config


def about(body_container):
    with body_container:
        with st.container(key='about-container'):
            st.write(config['About'])
