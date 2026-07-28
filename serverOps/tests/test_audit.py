"""Audit log writes one JSONL line per recorded operation."""

from __future__ import annotations

import json

from serverops.audit import AuditLog


def test_disabled_audit_is_noop(tmp_path) -> None:
    log = AuditLog(None)
    log.record(connection="x", operation="op", status="ok")  # must not raise / not write
    assert not any(tmp_path.iterdir())


def test_record_appends_jsonl(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path))
    log.record(connection="web1", operation="ssh_exec", status="ok", detail="uptime")
    log.record(connection="web1", operation="ssh_exec", status="exit:2")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["connection"] == "web1"
    assert first["operation"] == "ssh_exec"
    assert first["status"] == "ok"
    assert first["detail"] == "uptime"
    assert "ts" in first and "pid" in first


def test_record_creates_parent_dirs(tmp_path) -> None:
    path = tmp_path / "deep" / "nested" / "audit.jsonl"
    AuditLog(str(path)).record(connection="x", operation="op", status="ok")
    assert path.exists()


def test_record_never_raises_on_bad_path() -> None:
    # an unwritable path must not break the calling operation
    AuditLog("/no/such/allowed/dir/audit.jsonl").record(
        connection="x", operation="op", status="ok"
    )
