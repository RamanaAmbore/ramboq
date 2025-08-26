import pandas as pd
import streamlit as st

from src.constants import holdings_config, margins_config, positions_config
from src.helpers import broker_apis
from src.helpers import genai_api
from src.helpers.utils import get_image_bin_file as get_image_file, mask_column


@st.cache_data
def get_image_bin_file(file):
    return get_image_file(file)


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_holdings(dt):
    df = pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
    df = df[list(holdings_config.keys())]
    # print(df)
    df['account'] = mask_column(df['account'])

    sum_columns = [
        "inv_val",
        "cur_val",
        "pnl",
        "day_change_val"
    ]

    # Group by 'account' and sum
    grouped_sums = df.groupby("account")[sum_columns].sum().reset_index()

    # Calculate total sums for whole dataframe (all accounts)
    total_sums = df[sum_columns].sum().to_frame().T
    total_sums["account"] = "TOTAL"

    # Append total sums as a row to grouped sums
    total_df = pd.concat([grouped_sums, total_sums], ignore_index=True)
    total_df['pnl_percentage'] = total_df['pnl'] / total_df['inv_val'] * 100
    # print(total_df)
    total_df['day_change_percentage'] = (total_df['day_change_val'] / total_df['cur_val']) * 100

    return df, total_df


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_positions(dt):
    df = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
    df = df[list(positions_config.keys())]
    df['account'] = mask_column(df['account'])
    sum_columns = [
        "pnl"
    ]
    # Group by 'account' and sum
    grouped_sums = df.groupby("account")[sum_columns].sum().reset_index()

    # Calculate total sums for whole dataframe (all accounts)
    total_sums = df[sum_columns].sum().to_frame().T
    total_sums["account"] = "TOTAL"

    # Append total sums as a row to grouped sums
    total_df = pd.concat([grouped_sums, total_sums], ignore_index=True)
    return df, total_df


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_margins(dt):
    df = pd.concat(broker_apis.fetch_margins(), ignore_index=True)
    df = df[list(margins_config.keys())]
    df['account'] = mask_column(df['account'])
    # Sum all numeric columns except 'account'
    total_row = df.select_dtypes(include='number').sum()

    # Add the 'account' column with value 'TOTAL'
    total_row['account'] = 'TOTAL'

    # Append this new row to the existing dataframe
    df = pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)
    return df


@st.cache_data(show_spinner="Connecting to GenAI for market update…")
def get_market_update(dt):
    return genai_api.get_market_update()
