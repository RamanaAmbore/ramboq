import streamlit as st

from src.helpers import broker_apis
from src.helpers.utils import get_image_bin_file as get_image_file


@st.cache_data
def get_image_bin_file(file):
    return get_image_file(file)


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_holdings(dt):
    return broker_apis.fetch_holdings()


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_positions(dt):
    return broker_apis.fetch_positions()


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_margins(dt):
    return broker_apis.fetch_margins()
