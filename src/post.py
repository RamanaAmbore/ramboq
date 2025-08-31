import streamlit as st

from src.helpers.utils import ramboq_config


def post():
    with st.container(key="body-container"):
        with st.container(key='text-container'):
            st.write(ramboq_config['post'])
