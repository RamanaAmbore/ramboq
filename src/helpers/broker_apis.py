import pandas as pd

from src.helpers.connections import Connections
from src.helpers.decorators import for_all_accounts
from src.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


@for_all_accounts
def fetch_holdings(connections=Connections, account=None, kite=None):
    # ✅ Holdings
    df_holdings = pd.DataFrame()
    try:
        df_holdings = pd.DataFrame(kite.holdings())

        if not holdings.empty:
            holdings["account"] = account
            holdings["type"] = "H"
    except Exception as e:
        logger.error(f"[{account}] Failed to fetch holdings: {e}")

        # Add calculated columns
    df_holdings["inv_val"] = df_holdings["average_price"] * df_holdings["opening_quantity"]
    df_holdings["cur_val"] = df_holdings["inv_val"] + df_holdings["pnl"]

    # Δ calculation (delta value)
    df_holdings["day_change_val"] = df_holdings["day_change"] * df_holdings["average_price"]

    # Format Date column
    df_holdings["Date"] = pd.to_datetime(df_holdings["Date"]).dt.strftime("%d%b%y")

    return df_holdings


@for_all_accounts
def fetch_positions(connections=Connections, account=None, kite=None):
    # ✅ Positions
    df_positions = pd.DataFrame()
    try:
        positions = pd.DataFrame(kite.positions()["net"])  # "day" also available

        if not positions.empty:
            positions["account"] = account
            positions["type"] = "P"
    except Exception as e:
        logger.error(f"[{account}] Failed to fetch positions: {e}")

    return df_positions


@for_all_accounts
def fetch_margins(connections=Connections, account=None, kite=None):
    # ✅ Margins (Cash)
    df_margins = pd.DataFrame()
    try:
        df_margins = pd.DataFrame([kite.margins(segment="equity")])

        # Flatten 'utilised' if it exists
        if "utilised" in df_margins.columns:
            utilised_df = pd.json_normalize(df_margins["utilised"])
            # Optional: prefix column names
            utilised_df = utilised_df.add_prefix("util ")
            # Drop original nested column and concat flattened
            df_margins = pd.concat([df_margins.drop(columns=["utilised"]), utilised_df], axis=1)

        # Flatten 'available' if needed
        if "available" in df_margins.columns:
            available_df = pd.json_normalize(df_margins["available"])
            available_df = available_df.add_prefix("avail ")
            df_margins = pd.concat([df_margins.drop(columns=["available"]), available_df], axis=1)

        if not df_margins.empty:
            df_margins["account"] = account
            df_margins["type"] = "C"
    except Exception as e:
        logger.error(f"[{account}] Failed to fetch margins: {e}")

    return df_margins


def update_books(holdings, positions, margins):
    """Return all data combined into one DataFrame (optional)."""
    dfs = [holdings, positions, margins]
    dfs = [df for df in dfs if not df.empty]
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


# def fetch_books(holdings, positions, margins):
#     books = [obj.books for obj in connections]
#
#     # Union/concat them into one dataframe
#     df_books = pd.concat(books, ignore_index=True)
#     df_positions = pd.concat(positions, ignore_index=True)
#     df_holdings = pd.concat(holdings, ignore_index=True)
#     df_margin = pd.concat(margins, ignore_index=True)
#
#     # Add calculated columns
#     df_holdings["inv_val"] = df_holdings["average_price"] * df_holdings["opening_quantity"]
#     df_holdings["cur_val"] = df_holdings["inv_val"] + df_holdings["pnl"]
#
#     # Δ calculation (delta value)
#     df_holdings["day_change_val"] = df_holdings["day_change"] * df_holdings["average_price"]
#
#     # Format Date column
#     df_holdings["Date"] = pd.to_datetime(df_holdings["Date"]).dt.strftime("%d%b%y")
#
#     total_pnl = df_holdings["P&L"].sum().round(2)
#     total_day_change_val = df_holdings["day_change_val"].sum().round(2)
#     total_inv_val = df_holdings["inv_val"].sum().round(2)
#     total_cur_val = df_holdings["cur_val"].sum().round(2)
#
#     # Prepend totals row
#     df_holdings = pd.concat([pd.DataFrame([totals]), df_holdings], ignore_index=True)
#
#     return df_books, df_positions, df_holdings, df_margin
#
#
# def fetch_all_holdings(connections):
#     all_holdings = pd.concat([fetch_holdings(conn) for conn in connections.connections])
#
#
# def fetch_all_positions(connections):
#     all_positions = pd.concat([fetch_holdings(conn) for conn in connections.connections])
#
#
# def fetch_all_margins(connections):
#     all_margins = pd.concat([fetch_holdings(conn) for conn in connections.connections])
#
#
# def fetch_data(conn):
#     """Fetch holdings, positions, and margins as DataFrames with indicators and account column."""
#     conn = Connections().conn
#     holdings, total_holdings = fetch_holdings()
#
#     positions, total_positions = fetch_positions()
#
#     margins, total_margins = fetch_margins()
#
#     books = update_books(holdings, positions, margins)


if __name__ == "__main__":
    # print(pd.concat(fetch_holdings(), ignore_index=True))
    # print(pd.concat(fetch_positions(), ignore_index=True))
    print(pd.concat(fetch_margins(), ignore_index=True))
