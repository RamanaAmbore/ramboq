import streamlit as st

from src.constants import holdings_config, margins_config, positions_config
from src.helpers.utils import get_closing_date
from src.utils_streamlit import fetch_positions, fetch_holdings, fetch_margins


def performance(body_container):
    with body_container:
        # Apply custom styles
        def style_dataframe(df):
            return (
                df.style
                .set_properties(**{"background-color": "#fcfeff"})  # cell background
            )

        tabs = st.tabs(["Funds", "Holdings", "Positions"])
        with tabs[0]:
            df = fetch_margins(get_closing_date())
            st.dataframe(style_dataframe(df), hide_index=True,
                         column_config=margins_config)

        with tabs[1]:
            df, sum_df = fetch_holdings(get_closing_date())
            st.dataframe(style_dataframe(sum_df), hide_index=True,
                         column_config=holdings_config)
            st.dataframe(style_dataframe(df), hide_index=True,
                         column_config=holdings_config)

        with tabs[3]:
            df = fetch_positions(get_closing_date())
            st.dataframe(style_dataframe(df), hide_index=True,
                         column_config=positions_config)
