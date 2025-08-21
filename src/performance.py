import pandas as pd
import streamlit as st
from src.helpers import kite_connect
from src.helpers.utils import get_closing_date


@st.cache_data
def get_books(dt):
    return kite_connect.get_books()


def performance(body_container):
    with body_container:
        df_books, df_positions, df_holdings, df_margin = get_books(get_closing_date())

        tabs = st.tabs(["Portfolio", "Holdings", "Positions", "Cash"])

        with tabs[0]:
            st.dataframe(df_books, use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                        df_books.columns})

        with tabs[1]:
            st.write(df_holdings, use_container_width=True,
                     column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                    df_holdings.columns})

        with tabs[2]:
            st.dataframe(df_positions, use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                        df_positions.columns})

        with tabs[3]:
            st.dataframe(df_margin, use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                        df_margin.columns})
