"""
Segment-scoped summary helpers used by the Litestar API background tasks.

Extracted from the legacy background_refresh daemon — these two functions
re-derive per-account + TOTAL rollups from segment-filtered broker DataFrames
(equity/commodity split).
"""

import pandas as pd


def summarise_holdings(seg_holdings, full_sum_holdings, seg_exchanges=None):
    """Re-derive per-account + TOTAL summary from segment-filtered holdings rows."""
    if seg_holdings.empty:
        return seg_holdings

    sum_columns = ["inv_val", "cur_val", "pnl", "day_change_val"]
    grouped = seg_holdings.groupby("account")[sum_columns].sum().reset_index()

    grouped['pnl_percentage']        = grouped['pnl'] / grouped['inv_val'] * 100
    grouped['day_change_percentage'] = grouped['day_change_val'] / grouped['cur_val'] * 100

    if 'cash' in full_sum_holdings.columns:
        cash_df = full_sum_holdings[full_sum_holdings['account'] != 'TOTAL'][['account', 'cash', 'net']]
        grouped = pd.merge(grouped, cash_df, on='account', how='left')

    total = grouped[[c for c in sum_columns if c in grouped.columns]].sum().to_frame().T
    total['account'] = 'TOTAL'
    if 'pnl_percentage' in grouped.columns:
        total['pnl_percentage'] = total['pnl'] / total['inv_val'] * 100
    if 'day_change_percentage' in grouped.columns:
        total['day_change_percentage'] = total['day_change_val'] / total['cur_val'] * 100

    return pd.concat([grouped, total], ignore_index=True)


def summarise_positions(seg_positions):
    """Re-derive per-account + TOTAL summary from segment-filtered positions rows."""
    if seg_positions.empty:
        return seg_positions

    grouped = seg_positions.groupby("account")[["pnl"]].sum().reset_index()
    total = pd.DataFrame([{'account': 'TOTAL', 'pnl': grouped['pnl'].sum()}])
    return pd.concat([grouped, total], ignore_index=True)
