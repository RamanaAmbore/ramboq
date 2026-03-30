"""
Alert utilities — market open/close summaries and intra-day loss alerts.

Message type prefixes:
  Telegram subject : Open | Alert | Close
  Email subject    : RamboQuant Open: | RamboQuant Alert: | RamboQuant Close:

Thresholds (config.yaml):
  alert_loss_abs:         alert if day loss > this absolute INR value (0 = disabled)
  alert_loss_pct:         alert if day loss > this % of current value  (0 = disabled)
  alert_cooldown_minutes: minimum minutes between repeat alerts for same account+type

Secrets (secrets.yaml):
  telegram_bot_token:  bot token from @BotFather
  telegram_chat_id:    group chat_id (negative integer for groups)
  alert_emails:        list of email addresses to notify
"""

from datetime import datetime, timedelta

import requests

from src.helpers.mail_utils import send_email
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import secrets, config

logger = get_logger(__name__)

_MSG_TYPES = {
    'open':  ('Open',  'RamboQuant Open: '),
    'alert': ('Alert', 'RamboQuant Alert: '),
    'close': ('Close', 'RamboQuant Close: '),
}


def _send_telegram(message: str):
    token = secrets.get('telegram_bot_token', '')
    chat_id = secrets.get('telegram_chat_id', '')
    if not token or not chat_id:
        logger.warning("Telegram not configured — skipping")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        if resp.ok:
            logger.info("Telegram alert sent")
        else:
            logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")


def _fixed_table(headers, rows):
    """Render a list of string-tuple rows as a fixed-width monospace table."""
    col_widths = [max(len(h), max((len(r[i]) for r in rows), default=0))
                  for i, h in enumerate(headers)]

    def fmt(r):
        return "  ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(r))

    sep = "  ".join("─" * w for w in col_widths)
    return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])


def _dispatch(msg_type: str, ist_display: str, table: str, subject_detail: str):
    """Send Telegram + email with correct prefixes for the message type."""
    tg_prefix, email_prefix = _MSG_TYPES[msg_type]

    telegram_msg = (
        f"<b>{tg_prefix} — {ist_display} IST</b>\n\n"
        f"<code>{table}</code>"
    )
    _send_telegram(telegram_msg)

    alert_emails = secrets.get('alert_emails', [])
    if alert_emails:
        subject = f"{email_prefix}{subject_detail}"
        html_body = (
            f"<html><body>"
            f"<p><b>{tg_prefix} — {ist_display} IST</b></p>"
            f"<pre style='font-family:monospace;font-size:13px'>{table}</pre>"
            f"</body></html>"
        )
        for email in alert_emails:
            try:
                send_email("", email, subject, html_body)
                logger.info(f"{tg_prefix} email sent to {email}")
            except Exception as e:
                logger.error(f"Failed to send {tg_prefix} email to {email}: {e}")


# ---------------------------------------------------------------------------
# Open / Close summary
# ---------------------------------------------------------------------------

def send_summary(sum_holdings, sum_positions, ist_display: str, msg_type: str):
    """
    Send holdings + positions summary at market open or close.
    msg_type: 'open' or 'close'
    """
    # Holdings table: Account | Cur Val | P&L | P&L% | Day Loss | Day Loss%
    h_headers = ("Account", "Cur Val", "P&L", "P&L%", "Day Loss", "Day Loss%")
    h_rows = []
    for _, row in sum_holdings.iterrows():
        account  = str(row.get('account', ''))
        cur_val  = float(row.get('cur_val', 0) or 0)
        pnl      = float(row.get('pnl', 0) or 0)
        pnl_pct  = float(row.get('pnl_percentage', 0) or 0)
        day_val  = float(row.get('day_change_val', 0) or 0)
        day_pct  = float(row.get('day_change_percentage', 0) or 0)
        h_rows.append((
            account,
            f"₹{cur_val:,.0f}",
            f"₹{pnl:,.0f}",
            f"{pnl_pct:.2f}%",
            f"₹{day_val:,.0f}",
            f"{day_pct:.2f}%",
        ))

    # Positions table: Account | P&L
    p_headers = ("Account", "P&L")
    p_rows = []
    for _, row in sum_positions.iterrows():
        account = str(row.get('account', ''))
        pnl     = float(row.get('pnl', 0) or 0)
        p_rows.append((account, f"₹{pnl:,.0f}"))

    holdings_table  = _fixed_table(h_headers, h_rows) if h_rows else "No holdings data"
    positions_table = _fixed_table(p_headers, p_rows) if p_rows else "No positions data"

    table = f"Holdings\n{holdings_table}\n\nPositions\n{positions_table}"
    subject_detail = f"{ist_display} IST"

    _dispatch(msg_type, ist_display, table, subject_detail)
    logger.info(f"Background: {msg_type} summary sent")


# ---------------------------------------------------------------------------
# Intra-day loss alerts
# ---------------------------------------------------------------------------

def _build_alert_rows(sum_holdings, sum_positions, alert_loss_abs, alert_loss_pct,
                      alert_state, cooldown_mins):
    now = datetime.now()
    rows = []

    def _cooldown_ok(key):
        last = alert_state.get(key)
        return not last or (now - last) >= timedelta(minutes=cooldown_mins)

    # Holdings
    for _, row in sum_holdings.iterrows():
        account = str(row.get('account', ''))
        day_val = float(row.get('day_change_val', 0) or 0)
        day_pct = float(row.get('day_change_percentage', 0) or 0)

        day_loss_str = f"₹{day_val:,.0f}"
        day_pct_str  = f"{day_pct:.2f}%"
        key = f"holdings_{account}"
        fired = False

        if alert_loss_abs > 0 and day_val < -alert_loss_abs and _cooldown_ok(key):
            rows.append(("Holdings", account, day_loss_str, day_pct_str,
                         f"₹{alert_loss_abs:,.0f}", "—"))
            fired = True

        if alert_loss_pct > 0 and day_pct < -alert_loss_pct and _cooldown_ok(key):
            rows.append(("Holdings", account, day_loss_str, day_pct_str,
                         "—", f"{alert_loss_pct:.1f}%"))
            fired = True

        if fired:
            alert_state[key] = now
        elif alert_state.get(key) and (now - alert_state[key]) < timedelta(minutes=cooldown_mins):
            logger.info(f"Holdings alert suppressed for {account} (cooldown)")

    # Positions
    for _, row in sum_positions.iterrows():
        account = str(row.get('account', ''))
        pnl = float(row.get('pnl', 0) or 0)
        key = f"positions_{account}"

        if alert_loss_abs > 0 and pnl < -alert_loss_abs and _cooldown_ok(key):
            rows.append(("Positions", account, f"₹{pnl:,.0f}", "—",
                         f"₹{alert_loss_abs:,.0f}", "—"))
            alert_state[key] = now
        elif alert_state.get(key) and (now - alert_state[key]) < timedelta(minutes=cooldown_mins):
            logger.info(f"Positions alert suppressed for {account} (cooldown)")

    return rows, alert_state


def check_and_alert(sum_holdings, sum_positions, alert_state: dict, ist_display: str):
    """
    Check day P&L thresholds. One row per breached threshold.
    Returns alert_state (modified in place).
    """
    alert_loss_abs = config.get('alert_loss_abs', 0)
    alert_loss_pct = config.get('alert_loss_pct', 0)
    cooldown_mins  = config.get('alert_cooldown_minutes', 30)

    if not alert_loss_abs and not alert_loss_pct:
        return alert_state

    rows, alert_state = _build_alert_rows(
        sum_holdings, sum_positions,
        alert_loss_abs, alert_loss_pct,
        alert_state, cooldown_mins
    )

    if not rows:
        return alert_state

    headers = ("Type", "Account", "Day Loss", "Day Loss%", "Abs", "Pct")
    table = _fixed_table(headers, rows)

    parts = []
    for typ, account, day_loss, day_pct, abs_thr, pct_thr in rows:
        thr = "+".join(t for t in [
            f"Abs {abs_thr}" if abs_thr != "—" else "",
            f"Pct {pct_thr}" if pct_thr != "—" else "",
        ] if t)
        parts.append(f"{typ} {account} {day_loss} ({day_pct}) [{thr}]")
    subject_detail = " | ".join(parts)

    _dispatch('alert', ist_display, table, subject_detail)
    logger.warning(f"Loss alerts fired: {[(r[0], r[1]) for r in rows]}")
    return alert_state
