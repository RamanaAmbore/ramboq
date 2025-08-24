import streamlit as st

from src.helpers.broker_apis import fetch_books
from src.helpers.utils import get_image_bin_file as get_image_file


@st.cache_data
def get_image_bin_file(file):
    return get_image_file(file)


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_books(dt):
    return fetch_books()
