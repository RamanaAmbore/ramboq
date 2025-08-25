import streamlit as st

from src.constants import holdings_config, margins_config, positions_config
from src.helpers import broker_apis
from src.helpers.utils import get_image_bin_file as get_image_file
import pandas as pd


@st.cache_data
def get_image_bin_file(file):
    return get_image_file(file)


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_holdings(dt):
    df= pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
    df = df[list(holdings_config.keys())]

    sum_columns = [
        "inv_val",
        "cur_val",
        "pnl",
        # "day_change_val"
    ]

    # Group by 'account' and sum
    grouped_sums = df.groupby("account")[sum_columns].sum().reset_index()

    # Calculate total sums for whole dataframe (all accounts)
    total_sums = df[sum_columns].sum().to_frame().T
    total_sums["account"] = "TOTAL"

    # Append total sums as a row to grouped sums
    summary_df = pd.concat([grouped_sums, total_sums], ignore_index=True)
    summary_df['pnl_percentage'] = summary_df['pnl']/summary_df['inv_val'] * 100
    # summary_df['day_change_percentage'] = summary_df['day_change_val'] / summary_df['cur_val'] * 100

    return df, summary_df


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_positions(dt):
    df = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
    df = df[list(positions_config.keys())]
    return df


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_margins(dt):
    df= pd.concat(broker_apis.fetch_margins(), ignore_index=True)
    df = df[list(margins_config.keys())]
    return df
