# spec: specs/canvas/agent-canvas-tools.spec.md
"""TDD for the canvas tools (S8). The emitted tag is re-parsed with a Python
port of the frontend's parseCardsFromMessage regex to prove compatibility (I1)."""
import json
import re

from src.tools.canvas import (
    create_timeline_branch,
    execute_business_action,
    manage_canvas_widgets,
)

# Ports of the exact regexes in frontend/src/app/sandbox/page.tsx:103-167.
CREATE_RE = re.compile(
    r'<create_card\s+id="([^"]+)"\s+type="([^"]+)"\s*>([\s\S]*?)</create_card>'
)
UPDATE_RE = re.compile(r'<update_card\s+id="([^"]+)"\s*>([\s\S]*?)</update_card>')
DELETE_RE = re.compile(r'<delete_card\s+id="([^"]+)"\s*/>')


def test_add_emits_parseable_create_tag():
    res = manage_canvas_widgets(
        action="add",
        widget_id="card-sales",
        card_type="kpi",
        widget_config={
            "title": "Ventas Mensuales",
            "macroData": {"value": "$12,450", "trend": "up"},
        },
    )
    assert res["status"] == "ok"

    m = CREATE_RE.search(res["tag"])
    assert m, "emitted tag must match the frontend create_card regex"
    assert m.group(1) == "card-sales"
    assert m.group(2) == "kpi"
    parsed = json.loads(m.group(3).strip())  # frontend does JSON.parse on the body
    assert parsed["title"] == "Ventas Mensuales"
    assert parsed["macroData"]["value"] == "$12,450"


def test_update_emits_update_tag_not_create():
    res = manage_canvas_widgets(
        action="update",
        widget_id="card-sales",
        widget_config={"title": "Ventas (actualizado)", "macroData": {"value": "$1"}},
    )
    assert res["status"] == "ok"
    assert UPDATE_RE.search(res["tag"])
    assert not CREATE_RE.search(res["tag"])  # update, not duplicate


def test_remove_emits_self_closing_delete_tag():
    res = manage_canvas_widgets(action="remove", widget_id="card-sales")
    assert res["status"] == "ok"
    m = DELETE_RE.search(res["tag"])
    assert m and m.group(1) == "card-sales"


def test_add_without_title_is_rejected():
    res = manage_canvas_widgets(
        action="add", widget_id="x", card_type="kpi", widget_config={"macroData": {"value": "1"}}
    )
    assert res["status"] == "error"
    assert "tag" not in res


def test_add_with_invalid_type_is_rejected():
    res = manage_canvas_widgets(
        action="add",
        widget_id="x",
        card_type="hologram",
        widget_config={"title": "t", "macroData": {"value": "1"}},
    )
    assert res["status"] == "error"
    assert "tag" not in res


def test_add_without_macrodata_is_rejected():
    res = manage_canvas_widgets(
        action="add", widget_id="x", card_type="kpi", widget_config={"title": "t"}
    )
    assert res["status"] == "error"


def test_unknown_action_rejected():
    assert manage_canvas_widgets(action="frobnicate", widget_id="x")["status"] == "error"


def test_timeline_branch_and_business_action_basic():
    b = create_timeline_branch("Simulación: caída de stock Sur")
    assert b["status"] == "ok" and b["tag"].startswith("<create_branch")

    a = execute_business_action("send_report_email", {"to": "boss@x.com"})
    assert a["status"] == "pending_confirmation"
    assert a["action_id"] == "send_report_email"


# ── Per-type schema validation (added with the card-repertoire feature) ──


def test_add_kpi_requires_macro_value():
    # macroData present but without the required "value" field → rejected.
    res = manage_canvas_widgets(
        action="add", widget_id="x", card_type="kpi",
        widget_config={"title": "t", "macroData": {"trend": "up"}},
    )
    assert res["status"] == "error" and "tag" not in res


def test_add_inventory_with_reorder_action_roundtrips():
    res = manage_canvas_widgets(
        action="add", widget_id="card-inv", card_type="inventory",
        widget_config={
            "title": "Alertas",
            "macroData": {"value": "2 Alertas"},
            "mesoData": {"bullets": ["Producto A: 1 (min 5)"]},
            "microData": {
                "tableHeaders": ["Ítem", "Acción"],
                "tableRows": [["Producto A", "Reordenar"]],
            },
        },
    )
    assert res["status"] == "ok"
    m = CREATE_RE.search(res["tag"])
    parsed = json.loads(m.group(3).strip())
    assert parsed["microData"]["tableRows"][0][1] == "Reordenar"


def test_add_full_card_with_chartdata_roundtrips():
    res = manage_canvas_widgets(
        action="add", widget_id="card-sales", card_type="kpi",
        widget_config={
            "title": "Ventas",
            "macroData": {"value": "$1", "trend": "up"},
            "mesoData": {"chartData": [{"label": "Sem 1", "value": 10}]},
            "microData": {"tableHeaders": ["A"], "tableRows": [["1"]]},
        },
    )
    assert res["status"] == "ok"
    parsed = json.loads(CREATE_RE.search(res["tag"]).group(3).strip())
    assert parsed["mesoData"]["chartData"][0]["value"] == 10


def test_add_rejects_malformed_chartdata():
    res = manage_canvas_widgets(
        action="add", widget_id="x", card_type="kpi",
        widget_config={
            "title": "t", "macroData": {"value": "1"},
            "mesoData": {"chartData": [{"label": "a"}]},  # missing numeric value
        },
    )
    assert res["status"] == "error" and "tag" not in res


def test_add_rejects_non_string_table_rows():
    res = manage_canvas_widgets(
        action="add", widget_id="x", card_type="kpi",
        widget_config={
            "title": "t", "macroData": {"value": "1"},
            "microData": {"tableRows": [{"bad": 1}]},  # row must be a list of strings
        },
    )
    assert res["status"] == "error" and "tag" not in res


def test_update_partial_allows_missing_macrodata():
    # update is a merge patch: macroData is optional.
    res = manage_canvas_widgets(
        action="update", widget_id="card-x",
        widget_config={"title": "t", "mesoData": {"bullets": ["a"]}},
    )
    assert res["status"] == "ok" and UPDATE_RE.search(res["tag"])


def test_update_still_shape_guards_present_fields():
    res = manage_canvas_widgets(
        action="update", widget_id="card-x",
        widget_config={"title": "t", "mesoData": {"chartData": [{"label": "a"}]}},
    )
    assert res["status"] == "error" and "tag" not in res
