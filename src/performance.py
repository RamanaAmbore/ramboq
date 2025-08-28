import streamlit as st

from src.constants import holdings_config, margins_config, positions_config
from src.helpers.utils import get_cycle_date, add_comma_to_number, style_dataframe, add_comma_to_df_numbers
from src.utils_streamlit import fetch_positions, fetch_holdings, fetch_margins


def performance(body_container):
    with body_container:
        # Apply custom styles
        def style_dataframe(df):
            return (
                df.style
                .set_properties(**{"background-color": "#fcfeff"})  # cell background
            )

        # --- Streamlit UI ---
        tabs = st.tabs(["Funds", "Holdings", "Positions"])
        with tabs[0]:
            df = fetch_margins(get_cycle_date())
            fetch_holdings(get_cycle_date(), df)
            fetch_positions(get_cycle_date())

            st.dataframe(style_dataframe(add_comma_to_df_numbers(df)), hide_index=True,
                     column_config=margins_config)

        with tabs[1]:
            df, sum_df = fetch_holdings(get_cycle_date(), fetch_margins(get_cycle_date()))

            st.dataframe(style_dataframe(add_comma_to_df_numbers(sum_df)), hide_index=True,
                         column_config=holdings_config)
            st.dataframe(style_dataframe(add_comma_to_df_numbers(df)), hide_index=True,
                         column_config=holdings_config)

        with tabs[2]:
            df, sum_df = fetch_positions(get_cycle_date())
            st.dataframe(style_dataframe(add_comma_to_df_numbers(sum_df)), hide_index=True,
                         column_config=positions_config)
            st.dataframe(style_dataframe(add_comma_to_df_numbers(df)), hide_index=True,
                         column_config=positions_config)
