import socket
from datetime import timedelta
from urllib.parse import urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.connection import create_connection as _orig_create_connection
from kiteconnect import KiteConnect

from backend.shared.helpers.date_time_utils import timestamp_indian
from backend.shared.helpers.decorators import retry_kite_conn
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.singleton_base import SingletonBase
from backend.shared.helpers.utils import generate_totp, secrets, config


class _SourceIPAdapter(HTTPAdapter):
    """Bind outgoing connections to a specific source IP.

    Kite restricts the same IP across multiple apps. Each account can bind
    to a different IPv6 address from the server's /48 subnet so Kite sees
    unique source IPs.

    Usage in secrets.yaml:
        kite_accounts:
          ZG0790:       # default — uses server's primary IPv4
          ZJ6294:
            source_ip: "2a02:4780:12:9e1d::1"
          ZK_NEW:
            source_ip: "2a02:4780:12:9e1d::2"
    """
    def __init__(self, source_ip, **kwargs):
        self._source_ip = source_ip
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs['source_address'] = (self._source_ip, 0)
        super().init_poolmanager(*args, **kwargs)

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
        self._source_ip = credentials.get('source_ip', None)

        self.login_url = secrets['kite_login_url']
        self.twofa_url = secrets['kite_twofa_url']
        self._access_token = None

        self._initialized = True

        self.kite = self._new_kite()

        self.session = requests.Session()
        if self._source_ip:
            adapter = _SourceIPAdapter(self._source_ip)
            self.session.mount('https://', adapter)
            self.session.mount('http://', adapter)

        # track connection creation time
        self._conn_created_at = None

        self.init_kite_conn()

    def _new_kite(self):
        """Create a KiteConnect instance, bound to source_ip if configured."""
        kite = KiteConnect(api_key=self.api_key)
        if self._source_ip and hasattr(kite, 'reqsession'):
            adapter = _SourceIPAdapter(self._source_ip)
            kite.reqsession.mount('https://', adapter)
            kite.reqsession.mount('http://', adapter)
        return kite

    def init_kite_conn(self, test_conn=False):
        """Returns KiteConnect instance, initializing it if necessary."""

        if not test_conn:
            return

        self.kite = self._new_kite()
        request_id = self.login()

        self.totp_authenticate(request_id)

        kite_url = self.kite.login_url()
        logger.info("Kite login URL received.")
        request_token = self._extract_request_token(kite_url)
        if not request_token:
            raise RuntimeError("Failed to extract request_token from Kite redirect")
        logger.info(f"Request Token received: {request_token}")
        self.setup_access_token(request_token)

    def _extract_request_token(self, kite_url):
        """Follow Kite OAuth redirect to extract request_token.
        The redirect_url points to a non-running localhost port, so the
        redirect either fails (ConnectionError) or lands somewhere unexpected.
        We extract the token from:
          1. The final response URL query params
          2. Any intermediate redirect URL in response history
          3. The ConnectionError message (contains the failed URL)
        """
        request_token = None
        try:
            resp = self.session.get(kite_url, allow_redirects=True, timeout=5)
            # Check final URL
            params = parse_qs(urlparse(resp.url).query)
            request_token = params.get('request_token', [None])[0]
            # If not in final URL, check redirect history
            if not request_token:
                for r in resp.history:
                    p = parse_qs(urlparse(r.headers.get('Location', '')).query)
                    tok = p.get('request_token', [None])[0]
                    if tok:
                        request_token = tok
                        break
        except Exception as e:
            # Expected: redirect to localhost fails with ConnectionError.
            # The redirect URL (with request_token) is in the error message.
            err = str(e)
            if 'request_token=' in err:
                try:
                    request_token = err.split("request_token=")[1].split("&")[0].split()[0]
                except (IndexError, ValueError):
                    pass
        return request_token

    @retry_kite_conn(RETRY_COUNT)
    def get_kite_conn(self, test_conn=False):
        """Return kite connection, refreshing if older than 20 hours"""
        now = timestamp_indian()
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
            self.kite = self._new_kite()
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
