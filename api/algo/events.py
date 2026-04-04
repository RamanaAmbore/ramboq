"""
Agent event dispatcher — sends notifications through configured channels.

Each agent has an `events` list defining which channels to use:
  [{"channel": "telegram", "enabled": true}, {"channel": "email", "enabled": true}]

The alert message always includes the trigger condition text.
"""

import json
from datetime import datetime, timezone

from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import config, is_prod_capable

logger = get_logger(__name__)


async def dispatch(agent, eval_result, broadcast_fn=None):
    """
    Send alert through all enabled channels for an agent.

    Args:
        agent: Agent DB row
        eval_result: EvalResult from conditions.evaluate()
        broadcast_fn: optional WebSocket broadcast function
    """
    message = f"{agent.name}: {eval_result.condition_text}"
    channels = agent.events if isinstance(agent.events, list) else []

    for ch in channels:
        if not ch.get("enabled", False):
            continue
        channel = ch.get("channel", "")

        try:
            if channel == "telegram" and is_prod_capable() and config.get("telegram"):
                await _send_telegram(message)
            elif channel == "email" and is_prod_capable() and config.get("mail"):
                await _send_email(agent.name, message)
            elif channel == "websocket" and broadcast_fn:
                broadcast_fn("agent_alert", {
                    "slug": agent.slug,
                    "message": message,
                    "condition": eval_result.condition_text,
                })
            elif channel == "log":
                logger.warning(f"AGENT [{agent.slug}]: {message}")
        except Exception as e:
            logger.error(f"Agent event dispatch failed ({channel}): {e}")

    # Persist to agent_events table
    await _log_event(agent, "triggered", eval_result.condition_text, eval_result.detail)


async def log_event(agent, event_type: str, condition_text: str = "", detail: dict = None):
    """Convenience wrapper for logging agent events."""
    await _log_event(agent, event_type, condition_text, detail)


async def _log_event(agent, event_type: str, condition_text: str = "", detail: dict = None):
    """Persist event to agent_events table."""
    try:
        from api.database import async_session
        from api.models import AgentEvent

        async with async_session() as session:
            event = AgentEvent(
                agent_id=agent.id,
                event_type=event_type,
                trigger_condition=condition_text,
                detail=json.dumps(detail) if detail else None,
            )
            session.add(event)
            await session.commit()
    except Exception as e:
        logger.error(f"Agent event persist failed: {e}")


async def _send_telegram(message: str):
    """Send Telegram alert using existing infrastructure."""
    from src.helpers.alert_utils import _send_telegram as tg_send
    from concurrent.futures import ThreadPoolExecutor
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, tg_send, message)


async def _send_email(agent_name: str, message: str):
    """Send email alert using existing infrastructure."""
    from src.helpers.mail_utils import send_email
    from src.helpers.utils import secrets
    from concurrent.futures import ThreadPoolExecutor
    import asyncio

    alert_emails = secrets.get("alert_emails", [])
    subject = f"RamboQuant Agent: {agent_name}"
    body = f"<p>{message}</p>"

    loop = asyncio.get_running_loop()
    for email in alert_emails:
        try:
            await loop.run_in_executor(None, send_email, "RamboQuant", email, subject, body)
        except Exception as e:
            logger.error(f"Agent email failed to {email}: {e}")
