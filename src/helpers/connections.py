from datetime import datetime, timedelta

import requests
from kiteconnect import KiteConnect

from src.helpers.decorators import retry_kite_conn
from src.helpers.ramboq_logger import get_logger
from src.helpers.singleton_base import SingletonBase
from src.helpers.utils import generate_totp, secrets, config

RETRY_COUNT = config['retry_count']
CONN_RESET_HOURS = int(config['conn_reset_hours'])

logger = get_logger(__name__)


class KiteConnection:
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
        self._access_token = None

        self._initialized = True

        self.kite = KiteConnect(api_key=self.api_key)

        self.session = requests.Session()

        # track connection creation time
        self._conn_created_at = None

        self.init_kite_conn()

    def init_kite_conn(self, test_conn=False):
        """Returns KiteConnect instance, initializing it if necessary."""

        if not test_conn:
            return

        self.kite = KiteConnect(api_key=self.api_key)
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

    @retry_kite_conn(RETRY_COUNT)
    def get_kite_conn(self, test_conn=False):
        """Return kite connection, refreshing if older than 20 hours"""
        now = datetime.now()
        if (
                self._conn_created_at is None
                or now - self._conn_created_at > timedelta(hours=CONN_RESET_HOURS)
        ):
            # connection too old → force re-init
            self._conn_created_at = now
            formatted_datetime = self._conn_created_at.strftime('%A, %B %d, %Y, %I:%M %p')
            logger.info(f'Kite connection connection refreshed at {formatted_datetime}')
            test_conn = True

        self.init_kite_conn(test_conn=test_conn)
        return self.kite

    @retry_kite_conn(RETRY_COUNT)
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

    @retry_kite_conn(RETRY_COUNT)
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

    @retry_kite_conn(RETRY_COUNT)
    def setup_access_token(self, request_token):
        try:
            self.kite = KiteConnect(api_key=self.api_key)
            session_data = self.kite.generate_session(request_token, api_secret=self._api_secret)
            self._access_token = session_data["access_token"]
            self.kite.set_access_token(self._access_token)

        except Exception as e:
            logger.error(f"Failed to generate access token for account {self.account}: {e}")
            raise

    def get_access_token(self):
        return self._access_token


class Connections(SingletonBase):
    def __init__(self):
        self.conn = {account: KiteConnection(account, secrets) for account in secrets['kite_accounts'].keys()}


if __name__ == "__main__":
    Connections()
