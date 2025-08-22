import pandas as pd
import streamlit as st
from src.helpers import kite_connect
from src.helpers.utils import get_closing_date


@st.cache_data (show_spinner="Connecting to broker platform and loading data…")
def get_books(dt):
    return kite_connect.get_books()


def performance(body_container):
    with body_container:


        # Apply custom styles
        def style_dataframe(df):
            return (
                df.style
                .set_properties(**{"background-color": "#fcfeff"})  # cell background
                .set_table_styles(
                    [{
                        "selector": "thead th",
                        "props": [("background-color", "#F2FBFF"), ("color", "red")]
                    }]
                )
            )

        tabs = st.tabs(["P & L", "Portfolio", "Holdings", "Positions", "Cash"])
        df_books, df_positions, df_holdings, df_margin = get_books(get_closing_date())

        with tabs[0]:
            st.dataframe(style_dataframe(df_books), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in df_books.columns})

        with tabs[1]:
            st.dataframe(style_dataframe(df_books), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in df_books.columns})

        with tabs[2]:
            st.dataframe(style_dataframe(df_holdings), use_container_width=True,
                         column_order=("Symbol",	"P&L", "Δ Val", "Inv Val", "Cur Val", "Qty",	"I Price",		"C Price",	"ΔPrice",	"ΔPrice%",	"Date",	"Account"			),
                         column_config={col: st.column_config.TextColumn(col, width=None ) for col in df_holdings.columns})

        with tabs[3]:
            st.dataframe(style_dataframe(df_positions), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in df_positions.columns})

        with tabs[4]:
            st.dataframe(style_dataframe(df_margin), use_container_width=True,
                         column_config={col: st.column_config.TextColumn(col, width="small") for col in df_margin.columns})
