import streamlit as st

from src.utils import config


def market(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(config['Market'])
            create_ruler()