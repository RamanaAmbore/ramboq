import streamlit as st

from src.helpers.utils import get_closing_date
from src.utils_streamlit import get_market_update


def market(body_container):
    with body_container:
        with st.container(key='text-container'):
            st.write(get_market_update(get_closing_date()))
