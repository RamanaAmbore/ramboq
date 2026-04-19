"""
Alert utilities — market open/close summaries and intra-day loss alerts.

Message type prefixes:
  Telegram subject : Open | Alert | Close
  Email subject    : RamboQuant Open: | RamboQuant Alert: | RamboQuant Close:

Thresholds (backend_config.yaml):
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

from backend.shared.helpers.mail_utils import send_email
from backend.shared.helpers.ramboq_logger import get_logger
import urllib3.util.connection
urllib3.util.connection.HAS_IPV6 = False  # Server IPv6 outbound hangs

from backend.shared.helpers.utils import secrets, config, is_enabled

logger = get_logger(__name__)

_MSG_TYPES = {
    'open':  ('Open Summary',  'RamboQuant Open Summary: '),
    'alert': ('Alert',          'RamboQuant Alert: '),
    'close': ('Close Summary',  'RamboQuant Close Summary: '),
}


def _send_telegram(message: str):
    import logging
    _log = logging.getLogger('backend.api.background')
    if not is_enabled('telegram'):
        _log.info("Telegram skipped — disabled for this environment")
        return
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
            _log.info("Telegram alert sent")
        else:
            _log.error(f"Telegram send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        _log.error(f"Telegram error: {e}")


def _fixed_table(headers, rows):
    """Render a list of string-tuple rows as a fixed-width monospace table (for Telegram)."""
    col_widths = [max(len(h), max((len(r[i]) for r in rows), default=0))
                  for i, h in enumerate(headers)]

    def fmt(r):
        return "  ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(r))

    sep = "  ".join("─" * w for w in col_widths)
    return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])


def _html_table(headers, rows):
    """Render a list of string-tuple rows as an HTML table for email."""
    th_style = (
        "background-color:#1a3a5c;color:#ffffff;padding:8px 12px;"
        "text-align:left;font-family:monospace;font-size:13px;white-space:nowrap"
    )
    td_style = (
        "padding:6px 12px;font-family:monospace;font-size:13px;"
        "border-bottom:1px solid #dce3ea;white-space:nowrap"
    )
    td_alt_style = td_style + ";background-color:#f4f7fa"

    header_cells = "".join(f"<th style='{th_style}'>{h}</th>" for h in headers)
    row_html = ""
    for i, row in enumerate(rows):
        bg = td_alt_style if i % 2 else td_style
        cells = "".join(f"<td style='{bg}'>{v}</td>" for v in row)
        row_html += f"<tr>{cells}</tr>"

    return (
        f"<table style='border-collapse:collapse;width:100%'>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{row_html}</tbody>"
        f"</table>"
    )


def _branch_banner_html(branch: str) -> str:
    """Return a prominent HTML banner for non-main branches."""
    return (
        f"<div style='background-color:#fff3cd;border:1px solid #ffc107;"
        f"border-radius:4px;padding:8px 14px;margin-bottom:12px;"
        f"font-family:sans-serif;font-size:13px;color:#856404'>"
        f"&#9888; <strong>Non-production branch: {branch}</strong>"
        f"</div>"
    )


def _dispatch(msg_type: str, ist_display: str, tg_table: str, email_table_html: str,
              subject_detail: str):
    """Send Telegram + email with correct prefixes for the message type."""
    import logging
    _log = logging.getLogger('backend.api.background')
    _log.info(f"_dispatch called: {msg_type} — {subject_detail}")
    tg_prefix, email_prefix = _MSG_TYPES[msg_type]

    branch = config.get('deploy_branch', 'main')
    branch_tag = f" [{branch}]" if branch != 'main' else ''

    # Telegram: fixed-width monospace table; branch warning line on non-main
    branch_line = f"\n⚠ <b>Branch: {branch}</b>" if branch != 'main' else ''
    telegram_msg = (
        f"<b>{tg_prefix}{branch_tag} — {ist_display}</b>{branch_line}\n\n"
        f"<code>{tg_table}</code>"
    )
    _send_telegram(telegram_msg)

    alert_emails = secrets.get('alert_emails', [])
    if alert_emails:
        subject = f"{email_prefix}{branch_tag}{subject_detail}" if branch_tag else f"{email_prefix}{subject_detail}"
        branch_banner = _branch_banner_html(branch) if branch != 'main' else ''
        html_body = (
            f"<html><body style='font-family:sans-serif'>"
            f"{branch_banner}"
            f"<p style='font-size:14px'><b>{tg_prefix}{branch_tag} — {ist_display}</b></p>"
            f"{email_table_html}"
            f"</body></html>"
        )
        for email in alert_emails:
            try:
                send_email("", email, subject, html_body)
                logger.info(f"{tg_prefix} email sent to {email}")
            except Exception as e:
                logger.error(f"Failed to send {tg_prefix} email to {email}: {e}")


# ---------------------------------------------------------------------------
# Funds table helpers
# ---------------------------------------------------------------------------

def _build_funds_rows(df_margins):
    """Build (Account, Cash, Avail Margin, Used Margin, Collateral) rows from df_margins."""
    rows = []
    if df_margins is None or df_margins.empty:
        return rows
    for _, row in df_margins.iterrows():
        account   = str(row.get('account', ''))
        cash      = float(row.get('avail opening_balance', 0) or 0)
        avail_net = float(row.get('net', 0) or 0)
        used      = float(row.get('util debits', 0) or 0)
        collat    = float(row.get('avail collateral', 0) or 0)
        rows.append((account, f"₹{cash:,.0f}", f"₹{avail_net:,.0f}",
                     f"₹{used:,.0f}", f"₹{collat:,.0f}"))
    return rows


# ---------------------------------------------------------------------------
# Open / Close summary
# ---------------------------------------------------------------------------

def send_summary(sum_holdings, sum_positions, ist_display: str, msg_type: str,
                 label: str = "", df_margins=None):
    """
    Send holdings + positions + funds summary at market open or close.
    msg_type: 'open' or 'close'
    df_margins: full margins dataframe (all accounts + TOTAL); included when provided.
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

    # Funds table: Account | Cash | Avail Margin | Used Margin | Collateral
    f_headers = ("Account", "Cash", "Avail Margin", "Used Margin", "Collateral")
    f_rows = _build_funds_rows(df_margins)

    segment_label = f" — {label}" if label else ""
    subject_detail = f"{label + ' — ' if label else ''}{ist_display}"

    # Telegram: fixed-width monospace
    h_tg = _fixed_table(h_headers, h_rows) if h_rows else "No holdings data"
    p_tg = _fixed_table(p_headers, p_rows) if p_rows else "No positions data"
    tg_table = f"Holdings{segment_label}\n{h_tg}\n\nPositions{segment_label}\n{p_tg}"
    if f_rows:
        f_tg = _fixed_table(f_headers, f_rows)
        tg_table += f"\n\nFunds\n{f_tg}"

    # Email: HTML tables with section headings
    h_email = _html_table(h_headers, h_rows) if h_rows else "<p>No holdings data</p>"
    p_email = _html_table(p_headers, p_rows) if p_rows else "<p>No positions data</p>"
    email_table_html = (
        f"<p style='margin-top:16px;font-weight:bold'>Holdings{segment_label}</p>"
        f"{h_email}"
        f"<p style='margin-top:16px;font-weight:bold'>Positions{segment_label}</p>"
        f"{p_email}"
    )
    if f_rows:
        f_email = _html_table(f_headers, f_rows)
        email_table_html += f"<p style='margin-top:16px;font-weight:bold'>Funds</p>{f_email}"

    _dispatch(msg_type, ist_display, tg_table, email_table_html, subject_detail)
    logger.info(f"Background: {msg_type} summary sent")


# ---------------------------------------------------------------------------
# Intra-day loss alerts + negative fund balance alert
# ---------------------------------------------------------------------------

def _build_alert_rows(sum_holdings, sum_positions, df_margins, alert_loss_abs, alert_loss_pct,
                      alert_state, cooldown_mins):
    now = datetime.now()
    rows = []

    def _cooldown_ok(key):
        last = alert_state.get(key)
        return not last or (now - last) >= timedelta(minutes=cooldown_mins)

    # Holdings day-loss alerts
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

    # Positions day-loss alerts
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

    # Negative fund balance alerts (cash or avail margin < 0)
    if df_margins is not None and not df_margins.empty:
        for _, row in df_margins.iterrows():
            account   = str(row.get('account', ''))
            cash      = float(row.get('avail opening_balance', 0) or 0)
            avail_net = float(row.get('net', 0) or 0)

            for field, val, label in [
                ('cash', cash, 'Cash'),
                ('margin', avail_net, 'Avail Margin'),
            ]:
                key = f"funds_{field}_{account}"
                if val < 0 and _cooldown_ok(key):
                    rows.append(("Funds", account, f"₹{val:,.0f}", f"{label} negative",
                                 "—", "—"))
                    alert_state[key] = now
                elif alert_state.get(key) and (now - alert_state[key]) < timedelta(minutes=cooldown_mins):
                    logger.info(f"Funds alert suppressed for {account} {label} (cooldown)")

    return rows, alert_state


def check_and_alert(sum_holdings, sum_positions, alert_state: dict, ist_display: str,
                    df_margins=None):
    """
    Check day P&L thresholds and negative fund balances. One row per breached threshold.
    Returns alert_state (modified in place).
    df_margins: full margins dataframe; used for negative balance checks.
    """
    alert_loss_abs = config.get('alert_loss_abs', 0)
    alert_loss_pct = config.get('alert_loss_pct', 0)
    cooldown_mins  = config.get('alert_cooldown_minutes', 30)

    rows, alert_state = _build_alert_rows(
        sum_holdings, sum_positions, df_margins,
        alert_loss_abs, alert_loss_pct,
        alert_state, cooldown_mins
    )

    if not rows:
        return alert_state

    headers = ("Type", "Account", "Value", "Detail", "Abs Thr", "Pct Thr")

    # Telegram: fixed-width monospace
    tg_table = _fixed_table(headers, rows)

    # Email: HTML table
    email_table_html = _html_table(headers, rows)

    parts = []
    for typ, account, value, detail, abs_thr, pct_thr in rows:
        thr = "+".join(t for t in [
            f"Abs {abs_thr}" if abs_thr != "—" else "",
            f"Pct {pct_thr}" if pct_thr != "—" else "",
            detail if detail not in ("—", "") else "",
        ] if t)
        parts.append(f"{typ} {account} {value} [{thr}]")
    subject_detail = " | ".join(parts)

    _dispatch('alert', ist_display, tg_table, email_table_html, subject_detail)
    logger.warning(f"Loss/fund alerts fired: {[(r[0], r[1]) for r in rows]}")
    return alert_state
