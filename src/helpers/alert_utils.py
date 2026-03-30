"""
Loss alert utilities — checks day P&L thresholds after each background refresh
and fires email + Telegram notifications when breached.

Thresholds (config.yaml):
  alert_loss_abs:        alert if day loss > this absolute INR value (0 = disabled)
  alert_loss_pct:        alert if day loss > this % of current value  (0 = disabled)
  alert_cooldown_minutes: minimum minutes between repeat alerts for same account

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


def check_and_alert(sum_holdings, sum_positions, alert_state: dict, ist_display: str):
    """
    Check day P&L thresholds for holdings and positions.

    alert_state: dict persisted across calls in background_refresh, keyed by account.
                 Stores datetime of last alert to enforce cooldown.

    Returns alert_state (modified in place, also returned for clarity).
    """
    alert_loss_abs = config.get('alert_loss_abs', 0)
    alert_loss_pct = config.get('alert_loss_pct', 0)
    cooldown_mins = config.get('alert_cooldown_minutes', 30)
    alert_emails = secrets.get('alert_emails', [])

    if not alert_loss_abs and not alert_loss_pct:
        return alert_state  # both thresholds disabled

    now = datetime.now()
    triggered = []

    # --- Check holdings day change ---
    for _, row in sum_holdings.iterrows():
        account = str(row.get('account', ''))
        day_val = float(row.get('day_change_val', 0) or 0)
        day_pct = float(row.get('day_change_percentage', 0) or 0)
        cur_val = float(row.get('cur_val', 0) or 0)

        reasons = []
        if alert_loss_abs > 0 and day_val < -alert_loss_abs:
            reasons.append(f"Day loss ₹{abs(day_val):,.0f} exceeds threshold ₹{alert_loss_abs:,.0f}")
        if alert_loss_pct > 0 and day_pct < -alert_loss_pct:
            reasons.append(f"Day loss {abs(day_pct):.2f}% exceeds threshold {alert_loss_pct:.2f}%")

        if not reasons:
            continue

        key = f"holdings_{account}"
        last_alert = alert_state.get(key)
        if last_alert and (now - last_alert) < timedelta(minutes=cooldown_mins):
            logger.info(f"Loss alert suppressed for {account} (cooldown)")
            continue

        alert_state[key] = now
        triggered.append({
            'source': 'Holdings',
            'account': account,
            'day_val': day_val,
            'day_pct': day_pct,
            'cur_val': cur_val,
            'reasons': reasons,
        })

    # --- Check positions P&L ---
    for _, row in sum_positions.iterrows():
        account = str(row.get('account', ''))
        pnl = float(row.get('pnl', 0) or 0)

        reasons = []
        if alert_loss_abs > 0 and pnl < -alert_loss_abs:
            reasons.append(f"Positions P&L ₹{abs(pnl):,.0f} exceeds threshold ₹{alert_loss_abs:,.0f}")

        if not reasons:
            continue

        key = f"positions_{account}"
        last_alert = alert_state.get(key)
        if last_alert and (now - last_alert) < timedelta(minutes=cooldown_mins):
            logger.info(f"Position loss alert suppressed for {account} (cooldown)")
            continue

        alert_state[key] = now
        triggered.append({
            'source': 'Positions',
            'account': account,
            'day_val': pnl,
            'day_pct': None,
            'cur_val': None,
            'reasons': reasons,
        })

    if not triggered:
        return alert_state

    # --- Build messages ---
    header = f"⚠️ <b>RamboQuant Loss Alert — {ist_display} IST</b>"
    lines = [header, ""]
    for t in triggered:
        lines.append(f"<b>{t['source']} | Account: {t['account']}</b>")
        if t['day_pct'] is not None:
            lines.append(f"  Day Change: ₹{t['day_val']:,.0f}  ({t['day_pct']:.2f}%)")
        else:
            lines.append(f"  P&L: ₹{t['day_val']:,.0f}")
        for r in t['reasons']:
            lines.append(f"  • {r}")
        lines.append("")

    telegram_msg = "\n".join(lines)
    plain_msg = telegram_msg.replace("<b>", "").replace("</b>", "")

    _send_telegram(telegram_msg)

    if alert_emails:
        subject = f"RamboQuant Loss Alert — {ist_display}"
        html_body = f"<html><body><pre style='font-family:monospace'>{plain_msg}</pre></body></html>"
        for email in alert_emails:
            try:
                send_email("", email, subject, html_body)
                logger.info(f"Loss alert email sent to {email}")
            except Exception as e:
                logger.error(f"Failed to send loss alert email to {email}: {e}")

    logger.warning(f"Loss alerts fired for: {[t['account'] for t in triggered]}")
    return alert_state
