import random

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
def fetch_holdings(dt, df_sum_margins=None):
    df = pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
    lst = list(holdings_config.keys())
    lst.remove('cash')
    lst.remove('net')
    df = df[lst]

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

    if df_sum_margins is not None:
        grouped_sums = pd.merge(grouped_sums, df_sum_margins[["account", "avail opening_balance"]], on="account",
                                how="inner")
        grouped_sums.rename(columns={"avail opening_balance": "cash"}, inplace=True)
        grouped_sums["net"] = grouped_sums['cur_val'] + grouped_sums['cash']

        # Calculate total sums for whole dataframe (all accounts)
        total_sums = grouped_sums[[*sum_columns, 'net', 'cash']].sum().to_frame().T
    else:
        total_sums = grouped_sums[sum_columns].sum().to_frame().T

    total_sums["account"] = "TOTAL"
    total_columns = []
    # Append total sums as a row to grouped sums
    total_df = pd.concat([grouped_sums, total_sums], ignore_index=True)
    total_df['pnl_percentage'] = total_df['pnl'] / total_df['inv_val'] * 100
    # print(total_df)
    total_df['day_change_percentage'] = (total_df['day_change_val'] / total_df['cur_val']) * 100

    return df, total_df


@st.cache_data(show_spinner="Connecting to broker platform and loading data…")
def fetch_positions(dt, df_sum_margins=None):
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


def style_dataframe(df: pd.DataFrame):
    # Detect numeric columns
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()

    # Apply background + alignment
    styler = (
        df.style
        .set_properties(**{"background-color": "#fcfeff"})  # background
        .set_properties(subset=num_cols, **{"text-align": "right"})  # right align numbers
    )

    return styler


@st.dialog("📨 Email Status")
def show_status_dialog(success: bool, msg="✅ Your message has been sent successfully!"):
    if success:
        st.success(msg)
    else:
        st.error(f"❌ Failed to send your message. {msg}")

    if st.button("Close"):
        for fld in ['reset_clear', 'signin_clear', 'signup_clear', 'contact_clear']:
            st.session_state[fld] = True
        st.rerun()


def reset_form_state_vars(field_names, clear, captcha_min=1, captcha_max=9):
    for fld in ['reset_clear', 'signin_clear', 'signup_clear', 'contact_clear']:
        if clear != fld: st.session_state[fld] = True

    if clear not in st.session_state or st.session_state[clear]:
        st.session_state[clear] = False
        for field in field_names:
            if field != 'ph_country':
                st.session_state[field] = ""

        st.session_state['captcha_num1'] = random.randint(captcha_min, captcha_max)
        st.session_state['captcha_num2'] = random.randint(captcha_min, captcha_max)
        st.session_state['captcha_result'] = st.session_state['captcha_num1'] + st.session_state['captcha_num2']
    else:
        st.session_state['captcha_result'] = st.session_state['captcha_num1'] + st.session_state['captcha_num2']
        st.session_state['captcha_num1'] = random.randint(captcha_min, captcha_max)
        st.session_state['captcha_num2'] = random.randint(captcha_min, captcha_max)
    return
