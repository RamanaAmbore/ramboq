"""
Agent event dispatcher — sends notifications through configured channels.

Each agent has an `events` list defining which channels to use:
  [{"channel": "telegram", "enabled": true}, {"channel": "email", "enabled": true}]

The alert message always includes the trigger condition text.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import config, is_enabled

logger = get_logger(__name__)


@dataclass
class EvalResult:
    """Dispatch payload. The v2 grammar engine builds one of these from each
    fire so the existing dispatch() path keeps working unchanged."""
    triggered: bool
    condition_text: str
    detail: dict


async def dispatch(agent, eval_result, broadcast_fn=None, test_mode: bool = False):
    """
    Send alert through all enabled channels for an agent.

    Args:
        agent: Agent DB row
        eval_result: EvalResult built by the v2 agent engine when a condition fires
        broadcast_fn: optional WebSocket broadcast function
        test_mode:   when True every surface (subjects, preambles, logs) is
                     prefixed with TEST so simulated fires are never confused
                     with real ones.

    Alert message format (same across channels):
        Alert [branch] — <Agent Name>
        Condition: <condition_text>

    The branch tag is shown only on non-main deploys.
    """
    from backend.shared.helpers.date_time_utils import timestamp_display

    branch = config.get("deploy_branch", "main")
    branch_tag = f" [{branch}]" if branch != "main" else ""
    test_tag   = "TEST " if test_mode else ""
    ist_display = timestamp_display()
    condition_text = eval_result.condition_text or ""

    # Single unified content shown across all channels
    body_lines = [
        f"{test_tag}Alert{branch_tag} — {agent.name}",
        f"When: {ist_display}",
        f"Condition: {condition_text}",
    ]
    telegram_body = "\n".join(body_lines)
    email_subject = f"RamboQuant {test_tag}Agent{branch_tag}: {agent.name}"
    email_body = (
        f"<html><body style='font-family:sans-serif'>"
        + ("<p style='padding:8px;background:#fde4e4;border:1px solid #dc3545;"
           "border-radius:4px;color:#721c24'>🚨 <b>TEST RUN</b> — fabricated "
           "market data, not a real alert.</p>" if test_mode else "")
        + (f"<p style='padding:8px;background:#fef3c7;border:1px solid #f59e0b;border-radius:4px'>"
           f"⚠ <b>Branch: {branch}</b></p>" if branch != "main" else "")
        + f"<p><b>{test_tag}Alert{branch_tag} — {agent.name}</b></p>"
        + f"<p style='color:#666'>{ist_display}</p>"
        + f"<p><b>Condition:</b> {condition_text}</p>"
        + f"</body></html>"
    )

    channels = agent.events if isinstance(agent.events, list) else []

    for ch in channels:
        if not ch.get("enabled", False):
            continue
        channel = ch.get("channel", "")

        try:
            if channel == "telegram" and is_enabled("telegram"):
                await _send_telegram(telegram_body)
            elif channel == "email" and is_enabled("mail"):
                await _send_email_raw(email_subject, email_body)
            elif channel == "websocket" and broadcast_fn:
                broadcast_fn("agent_alert", {
                    "slug": agent.slug,
                    "message": telegram_body,
                    "condition": condition_text,
                    "test_mode": test_mode,
                })
            elif channel == "log":
                logger.warning(f"{test_tag}ALERT [{agent.slug}]{branch_tag}: {agent.name} — {condition_text}")
        except Exception as e:
            logger.error(f"Agent event dispatch failed ({channel}): {e}")

    # Persist to agent_events table (test_mode flag flows through)
    await _log_event(agent, "triggered", condition_text, eval_result.detail,
                     test_mode=test_mode)


async def log_event(agent, event_type: str, condition_text: str = "",
                    detail: dict = None, test_mode: bool = False):
    """Convenience wrapper for logging agent events."""
    await _log_event(agent, event_type, condition_text, detail, test_mode=test_mode)


async def _log_event(agent, event_type: str, condition_text: str = "",
                     detail: dict = None, test_mode: bool = False):
    """Persist event to agent_events table. `test_mode` is stored verbatim so
    the `/api/test/events/recent` endpoint can filter cleanly."""
    try:
        from backend.api.database import async_session
        from backend.api.models import AgentEvent

        async with async_session() as session:
            event = AgentEvent(
                agent_id=agent.id,
                event_type=event_type,
                trigger_condition=condition_text,
                detail=json.dumps(detail) if detail else None,
                test_mode=test_mode,
            )
            session.add(event)
            await session.commit()
    except Exception as e:
        logger.error(f"Agent event persist failed: {e}")


async def _send_telegram(message: str):
    """Send Telegram alert using existing infrastructure."""
    from backend.shared.helpers.alert_utils import _send_telegram as tg_send
    from concurrent.futures import ThreadPoolExecutor
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, tg_send, message)


async def _send_email_raw(subject: str, html_body: str):
    """Send an HTML email to all alert recipients."""
    from backend.shared.helpers.mail_utils import send_email
    from backend.shared.helpers.utils import secrets
    import asyncio

    alert_emails = secrets.get("alert_emails", [])
    loop = asyncio.get_running_loop()
    for email in alert_emails:
        try:
            await loop.run_in_executor(None, send_email, "RamboQuant", email, subject, html_body)
        except Exception as e:
            logger.error(f"Agent email failed to {email}: {e}")
