import streamlit as st

from src.helpers.broker_apis import fetch_holdings
from src.helpers.utils import get_closing_date
from src.constants import holdings_map
from src.utils_streamlit import fetch_holdings


def performance(body_container):
    with body_container:
        # Apply custom styles
        def style_dataframe(df):
            return (
                df.style
                .set_properties(**{"background-color": "#fcfeff"})  # cell background
            )

        tabs = st.tabs(["P & L", "Portfolio", "Holdings", "Positions", "Cash"])
        df_holdings = fetch_holdings(get_closing_date())

        with tabs[0]:
            st.dataframe(style_dataframe(df_holdings), use_container_width=True,
                         column_order=holdings_map['rename'].keys(),
                         column_config=holdings_map['column_config'])

        with tabs[1]:
            st.dataframe(style_dataframe(df_holdings), use_container_width=True,
                         column_order=holdings_map['rename'].keys(),
                         column_config=holdings_map['column_config'])

        with tabs[2]:
            st.dataframe(style_dataframe(df_holdings), use_container_width=True,
                         column_order=holdings_map['rename'].keys(),
                         column_config=holdings_map['column_config'])

        with tabs[3]:
            st.dataframe(style_dataframe(df_holdings), use_container_width=True,
                         column_order=holdings_map['rename'].keys(),
                         column_config=holdings_map['column_config'])

        with tabs[4]:
            st.dataframe(style_dataframe(df_holdings), use_container_width=True,
                         column_order=holdings_map['rename'].keys(),
                         column_config=holdings_map['column_config'])
