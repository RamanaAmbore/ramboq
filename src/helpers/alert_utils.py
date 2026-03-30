"""
Loss alert utilities — checks day P&L thresholds after each background refresh
and fires email + Telegram notifications when breached.

One row per triggered threshold. If both abs and pct breach for the same
account/type, two rows are emitted.

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


def _build_rows(sum_holdings, sum_positions, alert_loss_abs, alert_loss_pct,
                alert_state, cooldown_mins):
    """
    Returns (rows, alert_state).
    Each row: (type, account, day_loss_str, day_pct_str, abs_str, pct_str)
    Cooldown is per account+type — if either threshold fires, both share the cooldown key.
    """
    now = datetime.now()
    rows = []

    def _cooldown_ok(key):
        last = alert_state.get(key)
        return not last or (now - last) >= timedelta(minutes=cooldown_mins)

    # --- Holdings ---
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

    # --- Positions ---
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


def _format_table(rows):
    """Render rows as a fixed-width monospace table string."""
    headers = ("Type", "Account", "Day Loss", "Day Loss%", "Abs", "Pct")
    col_widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def fmt_row(r):
        return "  ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(r))

    sep = "  ".join("─" * w for w in col_widths)
    lines = [fmt_row(headers), sep]
    for r in rows:
        lines.append(fmt_row(r))
    return "\n".join(lines)


def _build_subject(rows):
    """Concise email subject line summarising triggered rows."""
    parts = []
    for typ, account, day_loss, day_pct, abs_thr, pct_thr in rows:
        thr = "+".join(t for t in [
            f"Abs {abs_thr}" if abs_thr != "—" else "",
            f"Pct {pct_thr}" if pct_thr != "—" else "",
        ] if t)
        parts.append(f"{typ} {account} {day_loss} ({day_pct}) [{thr}]")
    return "RamboQuantAlert: " + " | ".join(parts)


def check_and_alert(sum_holdings, sum_positions, alert_state: dict, ist_display: str):
    """
    Check day P&L thresholds. Fires Telegram + email for each breached threshold row.
    Returns alert_state (modified in place).
    """
    alert_loss_abs = config.get('alert_loss_abs', 0)
    alert_loss_pct = config.get('alert_loss_pct', 0)
    cooldown_mins  = config.get('alert_cooldown_minutes', 30)
    alert_emails   = secrets.get('alert_emails', [])

    if not alert_loss_abs and not alert_loss_pct:
        return alert_state

    rows, alert_state = _build_rows(
        sum_holdings, sum_positions,
        alert_loss_abs, alert_loss_pct,
        alert_state, cooldown_mins
    )

    if not rows:
        return alert_state

    table = _format_table(rows)
    subject = _build_subject(rows)
    header = f"⚠️ <b>RamboQuant Loss Alert — {ist_display} IST</b>"

    # Telegram — header bold, table in monospace code block
    telegram_msg = f"{header}\n\n<code>{table}</code>"
    _send_telegram(telegram_msg)

    # Email — monospace table in HTML
    if alert_emails:
        html_body = f"""<html><body>
<p><b>RamboQuant Loss Alert — {ist_display} IST</b></p>
<pre style="font-family:monospace;font-size:13px">{table}</pre>
</body></html>"""
        for email in alert_emails:
            try:
                send_email("", email, subject, html_body)
                logger.info(f"Loss alert email sent to {email}")
            except Exception as e:
                logger.error(f"Failed to send loss alert email to {email}: {e}")

    logger.warning(f"Loss alerts fired: {[(r[0], r[1]) for r in rows]}")
    return alert_state
