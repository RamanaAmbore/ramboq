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
#
# Design goals (driven by user requirement "wake me up only when something is
# really wrong"):
#   * Prefer fewer, louder alerts over frequent noisy ones.
#   * Every threshold is configurable via backend_config.yaml.
#   * Two orthogonal rule families: static floors (you've lost too much) and
#     rate-of-change (you're losing fast right now).
#   * Suppress re-alerts as long as the loss is roughly the same and the rate
#     isn't worsening — one ping, then quiet until the situation changes.
#
# Bucket key shape -- used for history, last-alert lookup, and dedup:
#   (section, scope, kind)
# where
#   section = 'holdings' | 'positions'
#   scope   = masked account id (e.g. "ZG####") | 'TOTAL'
#   kind    = 'static_pct' | 'static_abs' | 'rate_abs' | 'rate_pct'
#
# alert_state keys we touch (the state dict is owned by _task_performance):
#   alert_state['pnl_history']   {(section, scope): [(ts, pnl_val, pnl_pct), ...]}
#   alert_state['last_alert']    {(section, scope, kind): (ts, pnl_val, pnl_pct)}
#   alert_state['session_date']  date — resets pnl_history once per day
#   alert_state['session_start'] datetime — anchor for the baseline-offset gate
# Any other keys (e.g. the old 'funds_cash_…' ones) are untouched so funds
# negative-balance alerts keep their existing simple cooldown behaviour.
# ---------------------------------------------------------------------------

# Mapping from a bucket key to a human-readable rule label for the alert row.
_KIND_LABEL = {
    'static_pct':      'Static %',
    'static_abs':      'Static ₹',
    'rate_abs':        'Rate ₹/min',
    'rate_pct':        'Rate %/min',
    'negative_cash':   'Cash < 0',
    'negative_margin': 'Margin < 0',
}

# Short section codes for the narrow Telegram layout (mobile-friendly widths).
_SECTION_SHORT = {'Holdings': 'HLD', 'Positions': 'POS', 'Funds': 'FND'}


def _fmt_rupees(n: float) -> str:
    """Human-readable ₹ string with thousands separator and sign."""
    return f"-₹{abs(n):,.0f}" if n < 0 else f"₹{n:,.0f}"


def _fmt_pct(n: float) -> str:
    return f"{n:.2f}%"


def _tg_alert_body(alerts: list) -> str:
    """
    Build the narrow 2-line-per-row Telegram body. Each alert gets:
      line 1:  ▸ <short> <scope>  <current ₹> (<pct>)
      line 2:    <rule>  <extra / threshold>

    Keeps rows under ~32 char so they don't wrap on a phone in portrait.
    """
    lines = []
    for a in alerts:
        short = _SECTION_SHORT.get(a['section'], a['section'][:3].upper())
        head_right = _fmt_rupees(a['pnl'])
        if a.get('pct') is not None and a['pct'] != 0:
            head_right += f" ({_fmt_pct(a['pct'])})"
        lines.append(f"▸ {short} {a['scope']}  {head_right}")

        # Second line varies slightly by rule so the "why" is obvious at a glance.
        k = a['kind']
        label = _KIND_LABEL[k]
        if k == 'static_pct':
            lines.append(f"  {label}  floor {a['threshold']}")
        elif k == 'static_abs':
            lines.append(f"  {label}  floor {a['threshold']}")
        elif k == 'rate_abs':
            lines.append(f"  {label}  now {_fmt_rupees(a['rate_val'])}/min  "
                         f"floor {a['threshold']}")
        elif k == 'rate_pct':
            lines.append(f"  {label}  now {_fmt_pct(a['rate_val'])}/min  "
                         f"floor {a['threshold']}")
        else:
            lines.append(f"  {label}  {a['threshold']}")
        lines.append("")  # blank line between alerts for easy scanning
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _email_alert_body(alerts: list) -> str:
    """
    Build a proper HTML table for email. Columns: Type, Account, Rule,
    Current (₹/%), Rate (when applicable), Threshold. Rows are colored by
    severity kind so rate alerts pop visually.
    """
    th = (
        "background-color:#1a3a5c;color:#ffffff;padding:8px 12px;"
        "text-align:left;font-size:13px;white-space:nowrap"
    )
    td = (
        "padding:7px 12px;font-size:13px;border-bottom:1px solid #dce3ea;"
        "white-space:nowrap"
    )
    # Mild color cues per rule family. Static floors: yellow. Rate: red.
    # Funds: grey. Keeps the table scannable without being loud.
    row_bg = {
        'static_pct': '#fff8e1',
        'static_abs': '#fff8e1',
        'rate_abs':   '#fde2e4',
        'rate_pct':   '#fde2e4',
        'negative_cash':   '#eceff1',
        'negative_margin': '#eceff1',
    }

    def cell(v, bg=""):
        style = td + (f";background-color:{bg}" if bg else "")
        return f"<td style='{style}'>{v}</td>"

    header_cells = "".join(
        f"<th style='{th}'>{h}</th>"
        for h in ("Type", "Account", "Rule", "Current P&L", "Rate", "Threshold")
    )
    row_html = ""
    for a in alerts:
        bg = row_bg.get(a['kind'], "")
        current = _fmt_rupees(a['pnl'])
        if a.get('pct') is not None and a['pct'] != 0:
            current += f"<br><span style='color:#555;font-size:11px'>{_fmt_pct(a['pct'])}</span>"
        if a.get('rate_val') is None:
            rate = "—"
        elif a['kind'] == 'rate_abs':
            rate = f"{_fmt_rupees(a['rate_val'])}/min"
        elif a['kind'] == 'rate_pct':
            rate = f"{_fmt_pct(a['rate_val'])}/min"
        else:
            rate = "—"
        row_html += (
            "<tr>"
            + cell(a['section'], bg)
            + cell(a['scope'], bg)
            + cell(_KIND_LABEL[a['kind']], bg)
            + cell(current, bg)
            + cell(rate, bg)
            + cell(a['threshold'], bg)
            + "</tr>"
        )
    return (
        f"<table style='border-collapse:collapse;width:100%'>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{row_html}</tbody>"
        f"</table>"
    )


def _alert_cfg():
    """
    Load all alert_* config values into a plain dict once per call. Keeping
    this in one place makes it easy to tune thresholds without hunting through
    call sites, and the defaults here are the last-resort fallback if a key is
    missing from the YAML (defensive; the repo YAML ships every key).
    """
    g = config.get
    return {
        # Static floors — holdings (% only, by design)
        'hold_static_pct_acct':  float(g('alert_hold_static_pct_acct',  3.0)),
        'hold_static_pct_total': float(g('alert_hold_static_pct_total', 5.0)),
        # Static floors — positions (both % and ₹)
        'pos_static_pct_acct':   float(g('alert_pos_static_pct_acct',   2.0)),
        'pos_static_pct_total':  float(g('alert_pos_static_pct_total',  2.0)),
        'pos_static_abs_acct':   float(g('alert_pos_static_abs_acct',   30000)),
        'pos_static_abs_total':  float(g('alert_pos_static_abs_total',  50000)),
        # Rate-of-change window and thresholds
        'rate_window_min':       float(g('alert_rate_window_min', 10)),
        'hold_rate_abs_acct':    float(g('alert_hold_rate_abs_per_min_acct',  2000)),
        'hold_rate_abs_total':   float(g('alert_hold_rate_abs_per_min_total', 4000)),
        'hold_rate_pct':         float(g('alert_hold_rate_pct_per_min',       0.15)),
        'pos_rate_abs_acct':     float(g('alert_pos_rate_abs_per_min_acct',   3000)),
        'pos_rate_abs_total':    float(g('alert_pos_rate_abs_per_min_total',  6000)),
        'pos_rate_pct':          float(g('alert_pos_rate_pct_per_min',        0.25)),
        # Suppression
        'suppress_delta_abs':    float(g('alert_suppress_delta_abs', 15000)),
        'suppress_delta_pct':    float(g('alert_suppress_delta_pct', 0.5)),
        'cooldown_min':          float(g('alert_cooldown_minutes', 30)),
        # Opening-gap gate
        'baseline_offset_min':   float(g('alert_baseline_offset_min', 15)),
    }


def _maintain_session(alert_state: dict, now: datetime) -> None:
    """
    Reset the rolling history once per trading day and anchor `session_start`
    for the baseline-offset gate. Called at the top of every check cycle.
    """
    today = now.date()
    if alert_state.get('session_date') != today:
        alert_state['session_date'] = today
        alert_state['session_start'] = now
        alert_state['pnl_history'] = {}
        # last_alert history also resets so yesterday's ceilings don't suppress
        # today's alerts.
        alert_state['last_alert'] = {}


def _rate_gate_live(alert_state: dict, now: datetime, offset_min: float) -> bool:
    """
    True when enough time has passed since the first tick of the session for
    rate-of-change rules to be meaningful. Before this, the opening gap would
    produce a large per-minute rate that isn't really an "intra-day bleed".
    """
    start = alert_state.get('session_start')
    if not start:
        return False
    return (now - start) >= timedelta(minutes=offset_min)


def _trim_history(hist: list, now: datetime, window_min: float) -> None:
    """
    Drop samples older than ~3x the rate window (enough to smooth over restarts
    but small enough to stay cheap). In-place so the caller's list reference
    stays valid.
    """
    cutoff = now - timedelta(minutes=window_min * 3)
    hist[:] = [s for s in hist if s[0] >= cutoff]


def _compute_rate(hist: list, window_min: float, now: datetime):
    """
    Return (rate_abs_per_min, rate_pct_per_min) over the last `window_min`
    minutes, or (None, None) if there isn't enough data.

    A NEGATIVE rate means we're losing money (pnl shrinking). Callers compare
    the returned rate to a NEGATIVE threshold to decide whether to fire.
    """
    if len(hist) < 2:
        return (None, None)
    cutoff = now - timedelta(minutes=window_min)
    window = [s for s in hist if s[0] >= cutoff]
    if len(window) < 2:
        return (None, None)
    oldest_ts, oldest_pnl, oldest_pct = window[0]
    latest_ts, latest_pnl, latest_pct = window[-1]
    mins = (latest_ts - oldest_ts).total_seconds() / 60.0
    if mins <= 0:
        return (None, None)
    return ((latest_pnl - oldest_pnl) / mins,
            (latest_pct - oldest_pct) / mins if latest_pct is not None and oldest_pct is not None
            else None)


def _suppress(alert_state: dict, key: tuple, now: datetime,
              pnl_now: float, pct_now: float, cfg: dict) -> bool:
    """
    Return True to SKIP this alert, False to fire.

    The user-stated goal is "alerts signal a change — if loss is flat, stay
    quiet, even for hours". So both gates must clear before we re-fire:

      1. Cooldown — at least `cooldown_min` minutes must have elapsed since
         the last alert for this bucket. This is a hard minimum gap.
      2. Material change — loss must have deepened by at least
         `suppress_delta_abs` ₹ or `suppress_delta_pct` %.

    Both-true ⇒ fire. Either one short ⇒ suppress. Consequence: if you hit
    a threshold and then P&L hovers there, you get exactly ONE alert for
    that bucket, then silence until something actually gets worse (or the
    session rolls over the next day and state is wiped).
    """
    last = alert_state.get('last_alert', {}).get(key)
    if not last:
        return False  # first time we've seen this bucket in this session
    last_ts, last_pnl, last_pct = last

    # Gate 1: cooldown must have elapsed.
    if (now - last_ts) < timedelta(minutes=cfg['cooldown_min']):
        return True

    # Gate 2: at least one of the deltas must be breached.
    abs_moved = (pnl_now is not None and last_pnl is not None
                 and abs(pnl_now - last_pnl) >= cfg['suppress_delta_abs'])
    pct_moved = (pct_now is not None and last_pct is not None
                 and abs(pct_now - last_pct) >= cfg['suppress_delta_pct'])
    if abs_moved or pct_moved:
        return False

    return True  # cooldown passed but loss is flat → stay quiet


def _record_alert(alert_state: dict, key: tuple, now: datetime,
                  pnl_now: float, pct_now: float) -> None:
    alert_state.setdefault('last_alert', {})[key] = (now, pnl_now, pct_now)


def _alert_row(section: str, scope: str, kind: str,
               pnl: float, pct, rate_val, threshold: str) -> dict:
    """
    Structured alert row. `pnl`/`pct` carry raw values so formatters can style
    them independently. `rate_val` is None for static-rule alerts.
    """
    return dict(
        section=section, scope=scope, kind=kind,
        pnl=pnl, pct=pct, rate_val=rate_val, threshold=threshold,
    )


def _used_margin_for(df_margins, scope):
    """
    Return the used-margin denominator for positions % computation. Scope is
    either a masked account id or 'TOTAL'. Returns 0 if not found — caller
    must guard against divide-by-zero.
    """
    if df_margins is None or df_margins.empty:
        return 0.0
    match = df_margins[df_margins['account'].astype(str) == str(scope)]
    if match.empty:
        return 0.0
    try:
        return float(match.iloc[0].get('util debits', 0) or 0)
    except Exception:
        return 0.0


def _eval_holdings(sum_holdings, alert_state, df_margins_unused, now, cfg, gate_live):
    """
    Walk the holdings summary. For every account row (individual + TOTAL):
      * Append the day-loss snapshot to the rolling history (for rate calc).
      * Test static-% floor (scope-aware threshold).
      * Test rate-₹/min and rate-%/min triggers (if the baseline gate is live).
      * Apply suppression and collect triggered rows.
    """
    rows = []
    for _, row in sum_holdings.iterrows():
        scope    = str(row.get('account', ''))
        is_total = (scope == 'TOTAL')
        day_val  = float(row.get('day_change_val',        0) or 0)
        day_pct  = float(row.get('day_change_percentage', 0) or 0)

        hist_key = ('holdings', scope)
        hist = alert_state.setdefault('pnl_history', {}).setdefault(hist_key, [])
        hist.append((now, day_val, day_pct))
        _trim_history(hist, now, cfg['rate_window_min'])

        pct_floor = cfg['hold_static_pct_total'] if is_total else cfg['hold_static_pct_acct']
        rate_abs_thr = cfg['hold_rate_abs_total']  if is_total else cfg['hold_rate_abs_acct']
        rate_pct_thr = cfg['hold_rate_pct']

        val_str = f"₹{day_val:,.0f}"
        pct_str = f"{day_pct:.2f}%"

        # --- Static %
        if pct_floor > 0 and day_pct <= -pct_floor:
            key = ('holdings', scope, 'static_pct')
            if not _suppress(alert_state, key, now, day_val, day_pct, cfg):
                rows.append(_alert_row('Holdings', scope, 'static_pct',
                                       day_val, day_pct, None,
                                       f"-{pct_floor:.1f}%"))
                _record_alert(alert_state, key, now, day_val, day_pct)

        # --- Rate (only once enough session has elapsed)
        if gate_live:
            r_abs, r_pct = _compute_rate(hist, cfg['rate_window_min'], now)
            if r_abs is not None and rate_abs_thr > 0 and r_abs <= -rate_abs_thr:
                key = ('holdings', scope, 'rate_abs')
                if not _suppress(alert_state, key, now, day_val, day_pct, cfg):
                    rows.append(_alert_row('Holdings', scope, 'rate_abs',
                                           day_val, day_pct, r_abs,
                                           f"-₹{rate_abs_thr:,.0f}/min"))
                    _record_alert(alert_state, key, now, day_val, day_pct)
            if r_pct is not None and rate_pct_thr > 0 and r_pct <= -rate_pct_thr:
                key = ('holdings', scope, 'rate_pct')
                if not _suppress(alert_state, key, now, day_val, day_pct, cfg):
                    rows.append(_alert_row('Holdings', scope, 'rate_pct',
                                           day_val, day_pct, r_pct,
                                           f"-{rate_pct_thr:.2f}%/min"))
                    _record_alert(alert_state, key, now, day_val, day_pct)
    return rows


def _eval_positions(sum_positions, alert_state, df_margins, now, cfg, gate_live):
    """
    Walk the positions summary. Similar structure to holdings, but:
      * Position % uses |pnl| / used_margin (read from df_margins per scope).
      * Positions also has an absolute-₹ static floor.
    """
    rows = []
    for _, row in sum_positions.iterrows():
        scope    = str(row.get('account', ''))
        is_total = (scope == 'TOTAL')
        pnl      = float(row.get('pnl', 0) or 0)
        used_margin = _used_margin_for(df_margins, scope)
        # Positive when losing, 0 when flat. Percentage of deployed margin.
        pnl_pct = (pnl / used_margin * 100.0) if used_margin > 0 else 0.0

        hist_key = ('positions', scope)
        hist = alert_state.setdefault('pnl_history', {}).setdefault(hist_key, [])
        hist.append((now, pnl, pnl_pct))
        _trim_history(hist, now, cfg['rate_window_min'])

        pct_floor = cfg['pos_static_pct_total'] if is_total else cfg['pos_static_pct_acct']
        abs_floor = cfg['pos_static_abs_total'] if is_total else cfg['pos_static_abs_acct']
        rate_abs_thr = cfg['pos_rate_abs_total']  if is_total else cfg['pos_rate_abs_acct']
        rate_pct_thr = cfg['pos_rate_pct']

        val_str = f"₹{pnl:,.0f}"
        pct_str = f"{pnl_pct:.2f}%" if used_margin > 0 else "—"

        # --- Static %  (requires used_margin > 0 to be meaningful)
        if pct_floor > 0 and used_margin > 0 and pnl_pct <= -pct_floor:
            key = ('positions', scope, 'static_pct')
            if not _suppress(alert_state, key, now, pnl, pnl_pct, cfg):
                rows.append(_alert_row('Positions', scope, 'static_pct',
                                       pnl, pnl_pct, None,
                                       f"-{pct_floor:.1f}%"))
                _record_alert(alert_state, key, now, pnl, pnl_pct)

        # --- Static ₹
        if abs_floor > 0 and pnl <= -abs_floor:
            key = ('positions', scope, 'static_abs')
            if not _suppress(alert_state, key, now, pnl, pnl_pct, cfg):
                rows.append(_alert_row('Positions', scope, 'static_abs',
                                       pnl, pnl_pct if used_margin > 0 else None, None,
                                       f"-₹{abs_floor:,.0f}"))
                _record_alert(alert_state, key, now, pnl, pnl_pct)

        # --- Rate (gated by baseline offset)
        if gate_live:
            r_abs, r_pct = _compute_rate(hist, cfg['rate_window_min'], now)
            if r_abs is not None and rate_abs_thr > 0 and r_abs <= -rate_abs_thr:
                key = ('positions', scope, 'rate_abs')
                if not _suppress(alert_state, key, now, pnl, pnl_pct, cfg):
                    rows.append(_alert_row('Positions', scope, 'rate_abs',
                                           pnl, pnl_pct if used_margin > 0 else None, r_abs,
                                           f"-₹{rate_abs_thr:,.0f}/min"))
                    _record_alert(alert_state, key, now, pnl, pnl_pct)
            if r_pct is not None and rate_pct_thr > 0 and used_margin > 0 and r_pct <= -rate_pct_thr:
                key = ('positions', scope, 'rate_pct')
                if not _suppress(alert_state, key, now, pnl, pnl_pct, cfg):
                    rows.append(_alert_row('Positions', scope, 'rate_pct',
                                           pnl, pnl_pct, r_pct,
                                           f"-{rate_pct_thr:.2f}%/min"))
                    _record_alert(alert_state, key, now, pnl, pnl_pct)
    return rows


def _eval_negative_funds(df_margins, alert_state, now, cooldown_min):
    """
    Unchanged semantics from the previous implementation: fire on cash < 0 or
    avail margin < 0 with a simple per-bucket cooldown. Kept separate from
    P&L rules because this is a different class of problem (operational, not
    market).
    """
    rows = []
    if df_margins is None or df_margins.empty:
        return rows
    for _, row in df_margins.iterrows():
        scope     = str(row.get('account', ''))
        cash      = float(row.get('avail opening_balance', 0) or 0)
        avail_net = float(row.get('net', 0) or 0)
        for field, val, kind in (('cash',   cash,       'negative_cash'),
                                  ('margin', avail_net,  'negative_margin')):
            key = f"funds_{field}_{scope}"
            if val < 0:
                last_ts = alert_state.get(key)
                if not last_ts or (now - last_ts) >= timedelta(minutes=cooldown_min):
                    rows.append(_alert_row('Funds', scope, kind,
                                           val, None, None, "< 0"))
                    alert_state[key] = now
    return rows


def check_and_alert(sum_holdings, sum_positions, alert_state: dict, ist_display: str,
                    df_margins=None):
    """
    Main entry point — evaluates every rule for every scope, applies
    suppression, and emits one consolidated alert (Telegram + email) if any
    rows survived.

    Signature is unchanged from the previous static-only implementation; the
    state dict is the long-lived dict owned by _task_performance. Returns the
    mutated state dict for caller convenience (not required — it's mutated in
    place).
    """
    cfg = _alert_cfg()
    now = datetime.now()
    _maintain_session(alert_state, now)
    gate_live = _rate_gate_live(alert_state, now, cfg['baseline_offset_min'])

    rows = []
    rows.extend(_eval_holdings(sum_holdings, alert_state, df_margins, now, cfg, gate_live))
    rows.extend(_eval_positions(sum_positions, alert_state, df_margins, now, cfg, gate_live))
    rows.extend(_eval_negative_funds(df_margins, alert_state, now, cfg['cooldown_min']))

    if not rows:
        return alert_state

    # Group logically: Holdings first, then Positions, then Funds. Within each
    # section, account-level rows before TOTAL so the reader can scan per-acct
    # before seeing the aggregate.
    section_order = {'Holdings': 0, 'Positions': 1, 'Funds': 2}
    rows.sort(key=lambda r: (section_order.get(r['section'], 9),
                              0 if r['scope'] != 'TOTAL' else 1,
                              r['scope']))

    tg_body    = _tg_alert_body(rows)
    email_html = _email_alert_body(rows)

    # Compact subject for push notifications / inbox previews.
    parts = [
        f"{_SECTION_SHORT.get(r['section'], r['section'])} {r['scope']} {_KIND_LABEL[r['kind']]}"
        for r in rows
    ]
    subject_detail = " | ".join(parts)

    _dispatch('alert', ist_display, tg_body, email_html, subject_detail)
    logger.warning(f"Loss/fund alerts fired: "
                   f"{[(r['section'], r['scope'], r['kind']) for r in rows]}")
    return alert_state
