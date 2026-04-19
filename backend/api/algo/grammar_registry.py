"""
Grammar Registry — in-memory dispatch table loaded from the grammar_tokens DB.

The registry is the bridge between token names the operator types into an
agent's condition / notify / action spec and the Python callables that
actually run them. At app startup:

  1. seed_grammar_tokens() (in grammar.py) ensures the DB has the full
     system catalog.
  2. REGISTRY.reload() pulls every active row and imports each resolver by
     dotted path, caching the callable in a typed dispatch dict.

Runtime code (condition evaluator, notify dispatcher, action runner) asks
the registry for a token by (grammar_kind, token_kind, token) and gets back
either a callable or a template body. If the admin UI adds or flips tokens
while the service is running, calling REGISTRY.reload() picks up the change
with no restart.

The registry holds no business logic — it is a pure name → callable map.
"""

from __future__ import annotations

import importlib
import threading
from typing import Any, Callable, Optional

from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


def _import_dotted(path: str) -> Any:
    """Import 'pkg.mod.name' and return the attribute 'name'."""
    module_path, _, attr = path.rpartition(".")
    if not module_path:
        raise ValueError(f"invalid resolver path: {path}")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


class GrammarRegistry:
    """
    Thread-safe dispatch table. Reloadable at runtime.

    Each `kind_<x>` dict maps a token string to its resolver/handler. Tokens
    that live purely in the schema (e.g. operators, channels, formats) carry
    inert callables the engine can use directly; metric/scope/action_type
    tokens carry their Python resolver.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # condition
        self.metrics:    dict[str, Callable] = {}
        self.scopes:     dict[str, Callable] = {}
        self.operators:  dict[str, Callable] = {}
        # notify
        self.channels:   dict[str, Callable] = {}
        self.formats:    dict[str, Callable] = {}
        self.templates:  dict[str, str]      = {}
        # action
        self.actions:    dict[str, dict]     = {}   # {token: {"fn": callable, "params_schema": {...}}}

    # ── Accessors ──────────────────────────────────────────────────────────
    def metric(self, token: str) -> Optional[Callable]:
        return self.metrics.get(token)

    def scope(self, token: str) -> Optional[Callable]:
        return self.scopes.get(token)

    def op(self, token: str) -> Optional[Callable]:
        return self.operators.get(token)

    def channel(self, token: str) -> Optional[Callable]:
        return self.channels.get(token)

    def fmt(self, token: str) -> Optional[Callable]:
        return self.formats.get(token)

    def template(self, token: str) -> Optional[str]:
        return self.templates.get(token)

    def action(self, token: str) -> Optional[dict]:
        return self.actions.get(token)

    # ── Loader ─────────────────────────────────────────────────────────────
    async def reload(self) -> None:
        """
        Re-read the full catalog from grammar_tokens and rebuild the dispatch
        table. Idempotent; safe to call at startup, after admin edits, or on
        demand from an operator API endpoint.
        """
        from sqlalchemy import select
        from backend.api.database import async_session
        from backend.api.models import GrammarToken
        # Operators live in code — kept here so even a fully-empty DB still
        # has a comparator set available while seeding completes.
        from backend.api.algo.grammar import OPERATORS

        new_metrics:   dict[str, Callable] = {}
        new_scopes:    dict[str, Callable] = {}
        new_operators: dict[str, Callable] = dict(OPERATORS)
        new_channels:  dict[str, Callable] = {}
        new_formats:   dict[str, Callable] = {}
        new_templates: dict[str, str]      = {}
        new_actions:   dict[str, dict]     = {}

        async with async_session() as s:
            rows = (await s.execute(
                select(GrammarToken).where(GrammarToken.is_active == True)  # noqa: E712
            )).scalars().all()

        loaded = skipped = 0
        for r in rows:
            try:
                if r.grammar_kind == 'condition':
                    if r.token_kind == 'metric':
                        new_metrics[r.token] = _import_dotted(r.resolver) if r.resolver else None
                        loaded += 1
                    elif r.token_kind == 'scope':
                        new_scopes[r.token] = _import_dotted(r.resolver) if r.resolver else None
                        loaded += 1
                    elif r.token_kind == 'operator':
                        # Operators are already in new_operators from code; any
                        # DB override pointing to a custom resolver wins.
                        if r.resolver:
                            new_operators[r.token] = _import_dotted(r.resolver)
                        loaded += 1
                elif r.grammar_kind == 'notify':
                    if r.token_kind == 'channel' and r.resolver:
                        new_channels[r.token] = _import_dotted(r.resolver)
                        loaded += 1
                    elif r.token_kind == 'format' and r.resolver:
                        new_formats[r.token] = _import_dotted(r.resolver)
                        loaded += 1
                    elif r.token_kind == 'template':
                        new_templates[r.token] = r.template_body or ''
                        loaded += 1
                elif r.grammar_kind == 'action' and r.token_kind == 'action_type':
                    new_actions[r.token] = {
                        'fn': _import_dotted(r.resolver) if r.resolver else None,
                        'params_schema': r.params_schema or {},
                    }
                    loaded += 1
            except Exception as e:
                skipped += 1
                logger.warning(
                    f"Grammar registry: failed to load "
                    f"{r.grammar_kind}/{r.token_kind}/{r.token} "
                    f"(resolver={r.resolver}): {e}"
                )

        with self._lock:
            self.metrics   = new_metrics
            self.scopes    = new_scopes
            self.operators = new_operators
            self.channels  = new_channels
            self.formats   = new_formats
            self.templates = new_templates
            self.actions   = new_actions

        logger.info(
            f"Grammar registry reloaded — "
            f"metrics={len(self.metrics)} scopes={len(self.scopes)} "
            f"ops={len(self.operators)} channels={len(self.channels)} "
            f"formats={len(self.formats)} templates={len(self.templates)} "
            f"actions={len(self.actions)} (skipped={skipped})"
        )


# Module-level singleton; import as `from backend.api.algo.grammar_registry import REGISTRY`.
REGISTRY = GrammarRegistry()
