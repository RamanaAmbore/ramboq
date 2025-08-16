import streamlit as st

from src.utils import config
from src.components import create_ruler_white


def market(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(config['market'])