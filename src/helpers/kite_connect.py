import os
import sys
import pandas as pd

# parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
# sys.path.insert(0, parent_dir)
# print('syspath: ', sys.path)
#
# os.chdir("../..")
# print("cwd:", os.getcwd())

import requests
from kiteconnect import KiteConnect
from src.helpers.logger import get_logger
from src.helpers.utils import generate_totp, secrets
from functools import wraps

logger = get_logger(__name__)


def retry_kite_conn(max_attempts):
    """
    Decorator to retry a function on failure.

    :param max_attempts: Maximum retry attempts.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.warning(f"{func.__name__}: Attempt {attempt + 1} of {max_attempts} failed: {e}...")
                    if attempt == max_attempts - 1:
                        logger.error(f"{func.__name__}: Operation failed after {max_attempts} attempts.")
                        raise

        return wrapper

    return decorator


class KiteConnection():
    """Singleton class to handle Kite API authentication and access token management."""

    def __init__(self, account, secrets):

        self.account = account
        credentials = secrets['kite_accounts'][account]

        self._password = credentials['password']
        self.api_key = credentials["api_key"]
        self._api_secret = credentials["api_secret"]
        self.totp_token = credentials['totp_token']

        self.login_url = secrets['kite_login_url']
        self.twofa_url = secrets['kite_twofa_url']

        self._initialized = True

        self.kite = KiteConnect(api_key=self.api_key)

        self.session = requests.Session()

        # Object variables (DataFrames)
        self.holdings = pd.DataFrame()
        self.positions = pd.DataFrame()
        self.margins = pd.DataFrame()

        self._access_token = None
        self.books = None

        self.init_kite_conn()

    def init_kite_conn(self, test_conn=False):
        """Returns KiteConnect instance, initializing it if necessary."""

        request_id = self.login()

        self.totp_authenticate(request_id)

        try:
            kite_url = self.kite.login_url()
            logger.info("Kite login URL received.")
            self.session.get(kite_url)
            request_token = ""
        except Exception as e:
            # Extract request token from URL exception
            try:
                request_token = str(e).split("request_token=")[1].split("&")[0].split()[0]
                logger.info(f"Request Token received: {request_token}")
            except Exception:
                logger.error("Failed to extract request token.")
                raise

        self.setup_access_token(request_token)


    @retry_kite_conn(3)
    def get_kite_conn(self, test_conn=True):
        self.init_kite_conn(test_conn=test_conn)
        return self.kite


    @retry_kite_conn(3)
    def login(self):

        try:
            response = self.session.post(self.login_url, data={"user_id": self.account, "password": self._password})
            response.raise_for_status()
            request_id = response.json()["data"]["request_id"]
            logger.info(f"Login successful, Request ID: {request_id}")
        except Exception as e:
            logger.error(f"Login failed: {e}")
            raise
        return request_id


    @retry_kite_conn(3)
    def totp_authenticate(self, request_id):
        try:
            totp = generate_totp(self.totp_token)
            response = self.session.post(self.twofa_url,
                                    data={"user_id": self.account, "request_id": request_id, "twofa_value": totp})
            response.raise_for_status()
            logger.info("2FA authentication successful")
        except Exception as e:
            logger.error(f"2FA authentication failed: {e}")
            raise


    @retry_kite_conn(3)
    def setup_access_token(self, request_token):
        try:
            self.kite = KiteConnect(api_key=self.api_key)
            session_data = self.kite.generate_session(request_token, api_secret=self._api_secret)
            self._access_token = session_data["access_token"]
            self.kite.set_access_token(self._access_token)

            self.fetch_data()

        except Exception as e:
            logger.error(f"Failed to generate access token for account {self.account}: {e}")
            raise


    def get_access_token(self):
        return self._access_token

    def fetch_data(self):
        """Fetch holdings, positions, and margins as DataFrames with indicators and account column."""

        # ✅ Holdings
        try:
            holdings = self.kite.holdings()
            self.holdings = pd.DataFrame(holdings)
            if not self.holdings.empty:
                self.holdings["account"] = self.account
                self.holdings["type"] = "H"
        except Exception as e:
            logger.info(f"[{self.account}] Failed to fetch holdings: {e}")

        # ✅ Positions
        try:
            positions = self.kite.positions()["net"]  # "day" also available
            self.positions = pd.DataFrame(positions)
            if not self.positions.empty:
                self.positions["account"] = self.account
                self.positions["type"] = "P"
        except Exception as e:
            logger.info(f"[{self.account}] Failed to fetch positions: {e}")

        # ✅ Margins (Cash)
        try:
            margins = self.kite.margins(segment="equity")
            self.margins = pd.DataFrame([margins])  # wrap dict into list → DF
            if not self.margins.empty:
                self.margins["account"] = self.account
                self.margins["type"] = "C"
        except Exception as e:
            logger.info(f"[{self.account}] Failed to fetch margins: {e}")
        self.update_books()

    def update_books(self):
        """Return all data combined into one DataFrame (optional)."""
        dfs = [self.holdings, self.positions, self.margins]
        dfs = [df for df in dfs if not df.empty]
        self.books =  pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def get_connections():
    return [KiteConnection(account, secrets) for account in secrets['kite_accounts'].keys()]

def get_books():
    connections = get_connections()
    # Collect all get_all() dataframes into a list
    holdings = [obj.holdings for obj in connections]
    positions = [obj.positions for obj in connections]
    margins= [obj.margins for obj in connections]
    books = [obj.books for obj in connections]

    # Union/concat them into one dataframe
    df_books = pd.concat(books, ignore_index=True)
    df_positions = pd.concat(positions, ignore_index=True)
    df_holdings = pd.concat(holdings, ignore_index=True)
    df_margin = pd.concat(margins, ignore_index=True)

    # Column mapping: original → renamed
    rename_map = {
        "tradingsymbol": "Symbol",
        "opening_quantity": "Qty",
        "average_price": "I Price",
        "pnl": "P&L",
        "close_price": "C Price",
        "day_change": "ΔPrice",
        "day_change_percentage": "ΔPrice%",
        "authorised_date": "Date",
        "account": "Account"
    }

    # Extract required columns and rename
    df_holdings = df_holdings[list(rename_map.keys())].rename(columns=rename_map)

    # Add calculated columns
    df_holdings["Inv Val"] = df_holdings["I Price"] * df_holdings["Qty"]
    df_holdings["Cur Val"] = df_holdings["Inv Val"] + df_holdings["P&L"]

    # Δ calculation (delta value)
    df_holdings["Δ Val"] = df_holdings["ΔPrice"] * df_holdings["Qty"]

    # Round numeric columns to 2 decimals
    for col in ["Qty", "I Price", "P&L", "C Price", "Δ Val", "ΔPrice", "ΔPrice%", "Inv Val", "Cur Val"]:
        df_holdings[col] = df_holdings[col].round(2)

    # Format Date column
    df_holdings["Date"] = pd.to_datetime(df_holdings["Date"]).dt.strftime("%d%b%y")

    # Compute totals row: sum for P&L, Δ Val, Inv Val, Cur Val; other columns blank
    totals = {col: "" for col in df_holdings.columns}  # default blank for all
    totals["Symbol"] = "TOTAL"
    totals["P&L"] = df_holdings["P&L"].sum().round(2)
    totals["Δ Val"] = df_holdings["Δ Val"].sum().round(2)
    totals["Inv Val"] = df_holdings["Inv Val"].sum().round(2)
    totals["Cur Val"] = df_holdings["Cur Val"].sum().round(2)

    # Prepend totals row
    df_holdings = pd.concat([pd.DataFrame([totals]), df_holdings], ignore_index=True)



    # Apply formatting to all columns
    for col in df_holdings.columns:
        df_holdings[col] = df_holdings[col].apply(format_number_indian)

    return df_books, df_positions, df_holdings, df_margin
def format_number_indian(x):
    if isinstance(x, (int, float)):
        sign = "+" if x >= 0 else "-"
        x_abs = abs(x)

        # Split integer and decimal parts
        int_part, dec_part = f"{x_abs:.2f}".split(".")

        # Indian-style grouping
        if len(int_part) > 3:
            # Last 3 digits remain as is
            last3 = int_part[-3:]
            rest = int_part[:-3]
            # Group remaining digits in pairs
            rest_groups = []
            while len(rest) > 2:
                rest_groups.insert(0, rest[-2:])
                rest = rest[:-2]
            if rest:
                rest_groups.insert(0, rest)
            int_part_formatted = ",".join(rest_groups + [last3])
        else:
            int_part_formatted = int_part

        return f"{sign}{int_part_formatted}.{dec_part}"

    return str(x)

if __name__ == "__main__":
    connections = get_connections()
    # Collect all get_all() dataframes into a list
    dfs = [obj.books for obj in connections]

    # Union/concat them into one dataframe
    all_data = pd.concat(dfs, ignore_index=True)

    print(all_data)
