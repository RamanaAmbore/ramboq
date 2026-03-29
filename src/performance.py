from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import streamlit as st

from src.constants import holdings_config, margins_config, positions_config
from src.helpers.date_time_utils import timestamp_est
from src.helpers.utils import get_nearest_time, add_comma_to_df_numbers, config
from src.utils_streamlit import fetch_positions, fetch_holdings, fetch_margins, style_dataframe


def performance():
    with st.container(key="body-container"):
        refresh_time = get_nearest_time(interval=config.get('performance_refresh_interval', 5))
        ist_display = datetime.strptime(refresh_time, "%d-%b-%y %H:%M").strftime("%a, %B %d, %Y, %I:%M %p")
        est_display = timestamp_est().strftime("%a, %B %d, %Y, %I:%M %p")
        st.write(f"**Refreshed at {ist_display} IST | {est_display} EST**")
        # Create tabs
        tabs = st.tabs(["Funds", "Holdings", "Positions"])

        # Fetch margins and positions in parallel; holdings depends on margins result
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_margins = ex.submit(fetch_margins, refresh_time)
            f_positions = ex.submit(fetch_positions, refresh_time)
            df_margins = f_margins.result()
            df_holdings, sum_holdings = fetch_holdings(refresh_time, df_margins)
            df_positions, sum_positions = f_positions.result()

        with tabs[0]:
            st.dataframe(style_dataframe(add_comma_to_df_numbers(df_margins)),
                         hide_index=True, column_config=margins_config)

        with tabs[1]:
            st.write("**Summary**")
            st.dataframe(style_dataframe(add_comma_to_df_numbers(sum_holdings)),
                         hide_index=True, column_config=holdings_config)
            for account in df_holdings['account'].unique():
                st.write(f"**{account}**")
                acct_df = df_holdings[df_holdings['account'] == account]
                st.dataframe(style_dataframe(add_comma_to_df_numbers(acct_df)),
                             hide_index=True, column_config=holdings_config)
            st.write("**All Accounts — Holdings**")
            st.dataframe(style_dataframe(add_comma_to_df_numbers(df_holdings)),
                         hide_index=True, column_config=holdings_config)

        with tabs[2]:
            st.write("**Summary**")
            st.dataframe(style_dataframe(add_comma_to_df_numbers(sum_positions)),
                         hide_index=True, column_config=positions_config)
            for account in df_positions['account'].unique():
                st.write(f"**{account}**")
                acct_df = df_positions[df_positions['account'] == account]
                st.dataframe(style_dataframe(add_comma_to_df_numbers(acct_df)),
                             hide_index=True, column_config=positions_config)
            st.write("**All Accounts — Positions**")
            st.dataframe(style_dataframe(add_comma_to_df_numbers(df_positions)),
                         hide_index=True, column_config=positions_config)
