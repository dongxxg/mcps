"""Secret scrubbing."""

from __future__ import annotations

from serverops.redaction import redact


def test_url_credentials_scrubbed() -> None:
    assert redact("postgres://alice:s3cr3t@db.host:5432/app") == (
        "postgres://alice:***@db.host:5432/app"
    )


def test_kv_secrets_scrubbed() -> None:
    out = redact("password=hunter2 token=abc123 api_key=xyz")
    assert "hunter2" not in out
    assert "abc123" not in out
    assert "xyz" not in out
    assert out.count("***") == 3


def test_no_credentials_untouched() -> None:
    assert redact("postgres://db.host:5432/app") == "postgres://db.host:5432/app"


def test_empty_input() -> None:
    assert redact("") == ""
