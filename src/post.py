import streamlit as st

from src.helpers.utils import ramboq_config


def post(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(ramboq_config['post'])
