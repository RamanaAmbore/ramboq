import streamlit as st
from src.helpers.utils import get_closing_date
from src.helpers.constants import holdings_map
from src.utils_streamlit import fetch_books


def performance(body_container):
    with body_container:
        # Apply custom styles
        def style_dataframe(df):
            return (
                df.style
                .set_properties(**{"background-color": "#fcfeff"})  # cell background
            )

        tabs = st.tabs(["P & L", "Portfolio", "Holdings", "Positions", "Cash"])
        df_books, df_positions, df_holdings, df_margin = fetch_books(get_closing_date())

        with tabs[0]:
            st.dataframe(style_dataframe(df_books), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                        df_books.columns})

        with tabs[1]:
            st.dataframe(style_dataframe(df_books), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                        df_books.columns})

        with tabs[2]:
            st.dataframe(style_dataframe(df_holdings), use_container_width=True,
                         column_order=holdings_map['rename'].keys(),
                         column_config=holdings_map['column_config'])

        with tabs[3]:
            st.dataframe(style_dataframe(df_positions), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                        df_positions.columns})

        with tabs[4]:
            st.dataframe(style_dataframe(df_margin), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in
                                        df_margin.columns})
