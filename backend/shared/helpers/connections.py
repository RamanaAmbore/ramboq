import json
import socket
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import urllib3.util.connection
import requests
from requests.adapters import HTTPAdapter
from kiteconnect import KiteConnect

# Force IPv4 globally. Server's outbound IPv6 hangs for most hosts.
# KiteConnect API sessions for accounts with source_ip get a per-session
# override to use IPv6 (api.kite.trade supports IPv6 and it works).
urllib3.util.connection.HAS_IPV6 = False

from backend.shared.helpers.date_time_utils import timestamp_indian
from backend.shared.helpers.decorators import retry_kite_conn
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.singleton_base import SingletonBase
from backend.shared.helpers.utils import generate_totp, secrets, config

# Token cache — JSON file per environment (lives in .log/ which is gitignored)
_TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent.parent.parent / '.log' / 'kite_tokens.json'


class _IPv6SourceAdapter(HTTPAdapter):
    """Force IPv6 with a specific source address for KiteConnect API calls.
    Used when an account needs a different IP than the server's default IPv4.
    Only applied to KiteConnect.reqsession (api.kite.trade), never to login.
    """
    def __init__(self, source_ip, **kwargs):
        self._source_ip = source_ip
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs['source_address'] = (self._source_ip, 0)
        super().init_poolmanager(*args, **kwargs)

    def send(self, request, *args, **kwargs):
        # Temporarily re-enable IPv6 for this request
        old = urllib3.util.connection.HAS_IPV6
        urllib3.util.connection.HAS_IPV6 = True
        try:
            return super().send(request, *args, **kwargs)
        finally:
            urllib3.util.connection.HAS_IPV6 = old



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
    """Persist an access token for an account. Empty token removes the entry."""
    try:
        data = {}
        if _TOKEN_CACHE_PATH.exists():
            data = json.loads(_TOKEN_CACHE_PATH.read_text())
        if not access_token:
            data.pop(account, None)
        else:
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

        # Serialises re-auth so two threads that discover the cached
        # token is invalid at the same moment don't race to log in —
        # Kite rejects parallel login()s for the same app key and can
        # invalidate BOTH tokens, which then forces a full re-auth
        # cycle (~5 min per account) for every caller in the window.
        self._login_lock = threading.Lock()

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
        """Create a KiteConnect instance, with IPv6 source binding if configured."""
        kite = KiteConnect(api_key=self.api_key)
        if self._source_ip and ':' in self._source_ip and hasattr(kite, 'reqsession'):
            adapter = _IPv6SourceAdapter(self._source_ip)
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
        """Return kite connection, refreshing if older than CONN_RESET_HOURS.

        Re-auth (cache-probe + full login) runs under `_login_lock` so
        concurrent callers can't race two login() + 2FA flows at once.
        Kite rejects parallel logins for the same app and invalidates
        both tokens — the symptom was ~5 min of 401s on every request
        until the retry loop cleared.
        """
        now = timestamp_indian()
        expired = (
            self._conn_created_at is None
            or now - self._conn_created_at > timedelta(hours=CONN_RESET_HOURS)
        )

        if not (expired or test_conn):
            return self.kite

        with self._login_lock:
            # Double-check under the lock — another thread may have
            # just refreshed while we were waiting.
            now = timestamp_indian()
            expired = (
                self._conn_created_at is None
                or now - self._conn_created_at > timedelta(hours=CONN_RESET_HOURS)
            )
            if not (expired or test_conn):
                return self.kite

            if expired:
                self._conn_created_at = now
                formatted = self._conn_created_at.strftime('%A, %B %d, %Y, %I:%M %p')
                logger.info(f'Kite connection refreshed at {formatted}')

            # Try cached token first — avoids full login/2FA
            if not self._access_token:
                self._try_restore_token()
            if self._access_token:
                # Validate token with a lightweight API call
                try:
                    self.kite.profile()
                    return self.kite
                except Exception as e:
                    logger.warning(f"Cached token invalid for {self.account}: {e}")
                    self._access_token = None
                    _save_cached_token(self.account, '')  # clear stale cache

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
    # Serialises the one-time init — SingletonBase's own lock protects
    # the _instances dict, not the body of this __init__. Two concurrent
    # Connections() callers could otherwise both see `_singleton_initialized`
    # as False and both run the KiteConnection dict build, which would
    # kick off parallel logins and race Kite's session tracker.
    _init_lock = threading.Lock()

    def __init__(self):
        # SingletonBase.__new__ returns the same instance on every call,
        # but Python always re-invokes __init__ after __new__. Without
        # this guard we'd rebuild KiteConnection per account on every
        # Connections() access — which re-does the token-cache restore
        # (+2 Kite calls each) and was adding ~14 s of latency to every
        # /api/holdings · /positions · /funds request.
        if getattr(self, '_singleton_initialized', False):
            return
        with Connections._init_lock:
            # Double-check under the lock — another thread may have
            # completed the init while we were waiting.
            if getattr(self, '_singleton_initialized', False):
                return
            self.conn = {account: KiteConnection(account, secrets)
                         for account in secrets['kite_accounts'].keys()}
            self._singleton_initialized = True


if __name__ == "__main__":
    Connections()
