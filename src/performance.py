import streamlit as st
from src.helpers.utils import get_closing_date
from src.helpers import kite_connect
import pandas as pd

@st.cache_resource
def get_books(dt):
    return kite_connect.get_books()

def performance(body_container):
    with body_container:
        with st.container(key="perf-container"):
            df_books, df_positions, df_holdings, df_margin = get_books(get_closing_date())

            tabs = st.tabs(["Portfolio", "Holdings", "Positions", "Cash", "F & O"])

            with tabs[0]:
                st.dataframe(df_books)

            with tabs[1]:
                st.write(df_holdings)

            with tabs[2]:
                st.dataframe(df_positions)

            with tabs[3]:
                st.dataframe(df_margin)
            with tabs[4]:
                st.dataframe(df_margin)

