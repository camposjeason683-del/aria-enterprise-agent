"""
ARIA-OS: Canvas tools (Fase 2 — Estado Pasivo).

Lets the agent build/modify the user's canvas by emitting the SAME text-tag
protocol the frontend already parses (parseCardsFromMessage in
frontend/src/app/sandbox/page.tsx): <create_card>, <update_card>, <delete_card>.
The agent must include the returned `tag` verbatim in its final message; the
frontend regex turns it into a live card.

These tools are UI-only and tenant-agnostic: the DATA inside a card comes from
the analyst tools (which run under RLS), never from here.

# spec: specs/canvas/agent-canvas-tools.spec.md
"""
from __future__ import annotations

import json
from typing import Any

# Card types the frontend ContentRenderer knows how to draw.
CARD_TYPES = ("kpi", "inventory", "saif-tracker")


def _err(message: str) -> dict:
    return {"status": "error", "error": message}


# Per-type required macro fields. Kept minimal on purpose: the frontend renderer
# (Macro/Meso/MicroBody) is tolerant (optional chaining everywhere), so over-strict
# validation here would be the only thing that could reject a card the UI can draw.
# Canonical schema: CardState in frontend/src/app/sandbox/timelineReducer.ts.
_CARD_SCHEMAS: dict = {
    "kpi": {"macro_required": ("value",)},
    "inventory": {"macro_required": ("value",)},
    "saif-tracker": {"macro_required": ("value",)},
}


def _validate_card(card_type: str, widget_config: dict, *, partial: bool = False) -> str | None:
    """Return an error message, or None if the card payload is shape-valid.

    partial=True (update): it's a merge patch, so macroData is optional; we only
    shape-guard whatever is present. partial=False (add): macroData + its per-type
    required fields are enforced.
    """
    macro = widget_config.get("macroData")
    if not partial:
        if not isinstance(macro, dict):
            return "widget_config.macroData (dict) is required to add a card"
        for field in _CARD_SCHEMAS.get(card_type, {}).get("macro_required", ()):
            if not macro.get(field):
                return f"widget_config.macroData.{field} is required for card_type '{card_type}'"
    elif macro is not None and not isinstance(macro, dict):
        return "widget_config.macroData must be an object"

    meso = widget_config.get("mesoData")
    if meso is not None:
        if not isinstance(meso, dict):
            return "widget_config.mesoData must be an object"
        chart = meso.get("chartData")
        if chart is not None and (
            not isinstance(chart, list)
            or not all(
                isinstance(p, dict)
                and isinstance(p.get("label"), str)
                and isinstance(p.get("value"), (int, float))
                and not isinstance(p.get("value"), bool)
                for p in chart
            )
        ):
            return "mesoData.chartData must be a list of {label: str, value: number}"
        bullets = meso.get("bullets")
        if bullets is not None and (
            not isinstance(bullets, list) or not all(isinstance(b, str) for b in bullets)
        ):
            return "mesoData.bullets must be a list of strings"

    micro = widget_config.get("microData")
    if micro is not None:
        if not isinstance(micro, dict):
            return "widget_config.microData must be an object"
        rows = micro.get("tableRows")
        if rows is not None and (
            not isinstance(rows, list)
            or not all(isinstance(r, list) and all(isinstance(c, str) for c in r) for r in rows)
        ):
            return "microData.tableRows must be a list of string arrays"
        headers = micro.get("tableHeaders")
        if headers is not None and (
            not isinstance(headers, list) or not all(isinstance(h, str) for h in headers)
        ):
            return "microData.tableHeaders must be a list of strings"
    return None


def manage_canvas_widgets(
    action: str,
    widget_id: str,
    widget_config: dict | None = None,
    card_type: str = "kpi",
) -> dict:
    """Create, update or remove a card on the user's canvas (Estado Pasivo).

    Args:
        action: "add" | "update" | "remove".
        widget_id: stable id for the card (e.g. "card-sales"). Reused on update/remove.
        widget_config: card payload. For "add"/"update": a dict with at least
            "title" (str) and "macroData" (dict with "value"). May also include
            "mesoData", "microData", "position", "changeSummary" — see CardState.
        card_type: one of CARD_TYPES (only used on "add").

    Returns:
        dict with `status` and, on success, `tag` (the text-tag the agent must
        echo verbatim into its reply so the frontend renders the change).
    """
    if not widget_id or not isinstance(widget_id, str):
        return _err("widget_id is required")

    action = (action or "").lower()

    if action == "remove":
        return {"status": "ok", "action": "remove", "tag": f'<delete_card id="{widget_id}"/>'}

    if action not in ("add", "update"):
        return _err("action must be one of: add, update, remove")

    if not isinstance(widget_config, dict):
        return _err("widget_config (dict) is required for add/update")
    if not widget_config.get("title"):
        return _err("widget_config.title is required")

    if action == "add":
        if card_type not in CARD_TYPES:
            return _err(f"card_type must be one of {CARD_TYPES}")
        err = _validate_card(card_type, widget_config)
        if err:
            return _err(err)
        body = json.dumps(widget_config, ensure_ascii=False)
        tag = f'<create_card id="{widget_id}" type="{card_type}">\n{body}\n</create_card>'
        return {"status": "ok", "action": "add", "tag": tag}

    # update (partial patch — macroData optional; only shape-guard what's present)
    err = _validate_card(card_type, widget_config, partial=True)
    if err:
        return _err(err)
    body = json.dumps(widget_config, ensure_ascii=False)
    tag = f'<update_card id="{widget_id}">\n{body}\n</update_card>'
    return {"status": "ok", "action": "update", "tag": tag}


def create_timeline_branch(name: str, from_node_id: str | None = None) -> dict:
    """Fork the timeline to explore a "what-if" scenario without altering main.

    Basic Estado-Pasivo version: emits a forward-compatible <create_branch> tag.
    Frontend parsing of branch tags is hardened in a later phase (see ROADMAP
    "Fuera de alcance"). For now the agent can announce a branch intent.
    """
    if not name or not isinstance(name, str):
        return _err("branch name is required")
    attrs = f'name="{name}"'
    if from_node_id:
        attrs += f' from="{from_node_id}"'
    return {"status": "ok", "action": "branch", "tag": f"<create_branch {attrs}/>"}


def execute_business_action(action_id: str, payload: dict | None = None) -> dict:
    """Bridge for real-world actions (send email, approve budget, ...).

    Basic version: validates and echoes the intent for confirmation. The real
    dispatch (HITL approval + side effects) is hardened in a later phase.
    """
    if not action_id or not isinstance(action_id, str):
        return _err("action_id is required")
    return {
        "status": "pending_confirmation",
        "action_id": action_id,
        "payload": payload or {},
        "note": "Action validated. Real dispatch requires explicit HITL approval (later phase).",
    }
