"""
Demo fixtures + helpers — what an anonymous visitor on the prod (main)
branch sees instead of the real broker book.

The fixtures are hardcoded Python data structures (not DB rows) so:
  - operators tweak the curated demo book by editing one file
  - no migration / nightly cron needed for the read-path data
  - demo data can never leak into the prod book by accident — it
    lives in its own module, not the same tables

Visitor *writes* (paper orders placed via the OrderTicket, sim runs)
do go to the same DB tables they normally would — they're isolated by
their `account` column starting with `DEMO`. A periodic sweep can
clean those if accumulation becomes an issue.
"""

from backend.api.algo.demo.fixtures import (
    DEMO_ACCOUNTS,
    get_positions_response,
    get_holdings_response,
    get_funds_response,
)

__all__ = [
    "DEMO_ACCOUNTS",
    "get_positions_response",
    "get_holdings_response",
    "get_funds_response",
]
