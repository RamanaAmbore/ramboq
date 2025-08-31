import streamlit as st

from src.helpers.utils import get_cycle_date
from src.utils_streamlit import get_market_update


def market():
    with st.container(key="body-container"):
        with st.container(key='text-container'):
            st.write(get_market_update(get_cycle_date()))
