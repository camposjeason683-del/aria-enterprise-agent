"""Unit tests for the notification formatters (pure)."""
from src.tools.notifications import _format_anomaly_alert, _format_brief


def test_format_anomaly_alert():
    assert _format_anomaly_alert({"product": "Café", "description": "ventas -40%"}) == \
        "⚠️ ARIA: Café — ventas -40%"
    # falls back gracefully on missing fields
    assert "un producto" in _format_anomaly_alert({})


def test_format_brief_counts_pending():
    assert "3 decisión" in _format_brief({"pending_count": 3})
    assert "al día" in _format_brief({"pending_count": 0})
    assert "2 decisión" in _format_brief({"pending_proposals": [{}, {}]})
