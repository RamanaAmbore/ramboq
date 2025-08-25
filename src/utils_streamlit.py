import streamlit as st

from src.constants import holdings_config, margins_config, positions_config
from src.helpers import broker_apis
from src.helpers.utils import get_image_bin_file as get_image_file
import pandas as pd


@st.cache_data
def get_image_bin_file(file):
    return get_image_file(file)


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_holdings(dt):
    df= pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
    df = df[list(holdings_config.keys())]

    return df


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_positions(dt):
    df = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
    df = df[list(positions_config.keys())]
    return df


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_margins(dt):
    df= pd.concat(broker_apis.fetch_margins(), ignore_index=True)
    df = df[list(margins_config.keys())]
    return df
