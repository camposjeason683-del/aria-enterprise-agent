"""Unit tests for the multimodal helpers (mime resolution + classification). The actual
Gemini upload is exercised in the live smoke."""
from src.tools.multimodal import classify, resolve_mime


def test_resolve_mime_prefers_declared_content_type():
    assert resolve_mime("x.bin", "audio/mpeg") == "audio/mpeg"


def test_resolve_mime_extension_fallback_when_missing_or_octet():
    assert resolve_mime("nota.mp3", "application/octet-stream") == "audio/mpeg"
    assert resolve_mime("clip.mp4", None) == "video/mp4"
    assert resolve_mime("informe.pdf", "") == "application/pdf"
    assert resolve_mime("grab.m4a", None) == "audio/mp4"
    assert resolve_mime("x.desconocido", None) == "application/octet-stream"


def test_resolve_mime_strips_charset():
    assert resolve_mime("a.txt", "text/plain; charset=utf-8") == "text/plain"


def test_classify_media_text_unsupported():
    for m in ("image/png", "audio/mpeg", "video/mp4", "video/quicktime", "application/pdf"):
        assert classify(m) == "media"
    assert classify("text/plain") == "text"
    assert classify("text/csv") == "text"
    # office binary → not natively analysable
    assert classify("application/vnd.openxmlformats-officedocument.wordprocessingml.document") == "unsupported"
