import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import urllib3.util.connection
import requests
from requests.adapters import HTTPAdapter
from kiteconnect import KiteConnect

# Force IPv4 for all outgoing connections. The server has IPv6 addresses
# but outbound IPv6 to external hosts (kite.zerodha.com, api.kite.trade)
# hangs. Python's requests/urllib3 tries IPv6 first when available.
urllib3.util.connection.HAS_IPV6 = False

from backend.shared.helpers.date_time_utils import timestamp_indian
from backend.shared.helpers.decorators import retry_kite_conn
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.singleton_base import SingletonBase
from backend.shared.helpers.utils import generate_totp, secrets, config

# Token cache — JSON file per environment (lives in .log/ which is gitignored)
_TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent.parent.parent / '.log' / 'kite_tokens.json'



RETRY_COUNT = config['retry_count']
CONN_RESET_HOURS = int(config['conn_reset_hours'])

logger = get_logger(__name__)


def _load_cached_token(account: str) -> tuple[str | None, datetime | None]:
    """Load a cached access token for an account. Returns (token, created_at) or (None, None)."""
    try:
        if not _TOKEN_CACHE_PATH.exists():
            return None, None
        data = json.loads(_TOKEN_CACHE_PATH.read_text())
        entry = data.get(account)
        if not entry:
            return None, None
        created = datetime.fromisoformat(entry['created_at'])
        age = datetime.now(timezone.utc) - created
        if age > timedelta(hours=CONN_RESET_HOURS):
            return None, None  # expired
        return entry['access_token'], created
    except Exception as e:
        logger.debug(f"Token cache read failed for {account}: {e}")
        return None, None


def _save_cached_token(account: str, access_token: str) -> None:
    """Persist an access token for an account."""
    try:
        data = {}
        if _TOKEN_CACHE_PATH.exists():
            data = json.loads(_TOKEN_CACHE_PATH.read_text())
        data[account] = {
            'access_token': access_token,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE_PATH.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.debug(f"Token cache write failed for {account}: {e}")


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

        # Login session uses plain requests (no source_ip binding).
        # Login goes to kite.zerodha.com which doesn't need IP whitelisting.
        # Only KiteConnect API calls (api.kite.trade) need the source IP.
        self.session = requests.Session()

        # track connection creation time
        self._conn_created_at = None

        # Try to restore from cached token (avoids full login on restart)
        self._try_restore_token()

    def _try_restore_token(self):
        """Try to restore access token from cache. If valid, skip full login."""
        token, created = _load_cached_token(self.account)
        if token:
            self.kite = self._new_kite()
            self.kite.set_access_token(token)
            self._access_token = token
            self._conn_created_at = timestamp_indian()
            logger.info(f"Restored cached token for {self.account} (age: "
                        f"{(datetime.now(timezone.utc) - created).seconds // 3600}h)")

    def _new_kite(self):
        """Create a KiteConnect instance."""
        return KiteConnect(api_key=self.api_key)

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
        """Extract request_token from Kite OAuth redirect.

        The Kite redirect URL must point to a non-running port (e.g.
        http://localhost:8080) so the redirect always fails with a
        ConnectionError. The request_token is extracted from the error
        message which contains the full redirect URL.

        IMPORTANT: The Kite redirect URL in the developer console MUST use
        a port that is NOT running on the server (8080 recommended).
        Using a port that IS running (e.g. 8000/8001) causes SSL hangs.
        """
        try:
            self.session.get(kite_url)
        except Exception as e:
            err = str(e)
            if 'request_token=' in err:
                try:
                    return err.split("request_token=")[1].split("&")[0].split()[0]
                except (IndexError, ValueError):
                    pass
        return None

    @retry_kite_conn(RETRY_COUNT)
    def get_kite_conn(self, test_conn=False):
        """Return kite connection, refreshing if older than CONN_RESET_HOURS."""
        now = timestamp_indian()
        expired = (
            self._conn_created_at is None
            or now - self._conn_created_at > timedelta(hours=CONN_RESET_HOURS)
        )

        if expired or test_conn:
            if expired:
                self._conn_created_at = now
                formatted = self._conn_created_at.strftime('%A, %B %d, %Y, %I:%M %p')
                logger.info(f'Kite connection refreshed at {formatted}')

            # Try cached token first — avoids full login/2FA
            if not self._access_token:
                self._try_restore_token()
            if self._access_token:
                return self.kite

            # No cached token — do full login
            self.init_kite_conn(test_conn=True)

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
            _save_cached_token(self.account, self._access_token)
            logger.info(f"Token cached for {self.account}")
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
