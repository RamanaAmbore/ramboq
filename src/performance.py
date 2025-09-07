import streamlit as st

from src.constants import holdings_config, margins_config, positions_config
from src.helpers.utils import get_cycle_date, add_comma_to_df_numbers
from src.utils_streamlit import fetch_positions, fetch_holdings, fetch_margins


def performance():
    with st.container(key="body-container"):
        # Apply custom styles
        def style_dataframe(df):
            return (
                df.style
                .set_properties(**{"background-color": "#fcfeff"})  # cell background
            )

        refresh_time = get_cycle_date()
        st.write(f"**Refresh Time: {refresh_time}**")
        # Create tabs
        tabs = st.tabs(["Funds", "Holdings", "Positions"])


        # Create empty placeholders inside each tab for dataframes
        with tabs[0]:
            margin_df_placeholder = st.empty()
        with tabs[1]:
            sum_df_placeholder = st.empty()
            holdings_df_placeholder = st.empty()
        with tabs[2]:
            sum_pos_df_placeholder = st.empty()
            pos_df_placeholder = st.empty()

        # Generate and style data outside the tab context
        df_margins = fetch_margins(refresh_time)
        fetch_holdings(refresh_time, df_margins)
        fetch_positions(refresh_time)

        df_holdings, sum_holdings = fetch_holdings(get_cycle_date(), df_margins)
        df_positions, sum_positions = fetch_positions(get_cycle_date())

        styled_margins = style_dataframe(add_comma_to_df_numbers(df_margins))
        styled_sum_holdings = style_dataframe(add_comma_to_df_numbers(sum_holdings))
        styled_holdings = style_dataframe(add_comma_to_df_numbers(df_holdings))
        styled_sum_positions = style_dataframe(add_comma_to_df_numbers(sum_positions))
        styled_positions = style_dataframe(add_comma_to_df_numbers(df_positions))

        # Update placeholders with generated content
        margin_df_placeholder.dataframe(styled_margins, hide_index=True, column_config=margins_config)
        sum_df_placeholder.dataframe(styled_sum_holdings, hide_index=True, column_config=holdings_config)
        holdings_df_placeholder.dataframe(styled_holdings, hide_index=True, column_config=holdings_config)
        sum_pos_df_placeholder.dataframe(styled_sum_positions, hide_index=True, column_config=positions_config)
        pos_df_placeholder.dataframe(styled_positions, hide_index=True, column_config=positions_config)
