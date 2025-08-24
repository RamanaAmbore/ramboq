import streamlit as st

from src.helpers.utils import ramboq_config


def market(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(ramboq_config['market'])
