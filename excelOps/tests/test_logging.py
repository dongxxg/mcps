"""Tests for the structlog-based diagnostic logging capability (logging.py).

The capability: ``configure(path)`` writes structured JSON lines to a file;
``get_logger(name)`` returns a logger that emits timestamped, leveled,
key-value events. Verified end-to-end, not mocked.
"""

from __future__ import annotations

import json
import logging

import pytest

from excelops.logging import configure, get_logger, reset


@pytest.fixture(autouse=True)
def _clean_logging_state():
    """Each test starts from a clean stdlib + structlog state."""
    reset()
    yield
    reset()


@pytest.fixture
def log_file(tmp_path):
    return tmp_path / "excelops.log"


def read_json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_configure_writes_structured_json_lines(log_file):
    configure(log_file, level="DEBUG")
    log = get_logger("excelops.test")
    log.info("read_sheet.start", path="/tmp/x.xlsx", sheet="orders")

    rows = read_json_lines(log_file)
    assert len(rows) == 1
    ev = rows[0]
    assert ev["event"] == "read_sheet.start"
    assert ev["level"] == "info"
    assert ev["logger"] == "excelops.test"
    assert ev["path"] == "/tmp/x.xlsx"
    assert ev["sheet"] == "orders"
    assert "timestamp" in ev  # ISO-8601 from TimeStamper


def test_level_filtering_respected(log_file):
    configure(log_file, level="WARNING")
    log = get_logger("excelops.test")
    log.info("ignored")   # below WARNING -> dropped
    log.warning("kept")   # at WARNING -> kept

    rows = read_json_lines(log_file)
    assert [r["event"] for r in rows] == ["kept"]


def test_multiple_events_preserve_order(log_file):
    configure(log_file)
    log = get_logger("excelops.test")
    for i in range(5):
        log.info("step", i=i)

    rows = read_json_lines(log_file)
    assert [r["i"] for r in rows] == [0, 1, 2, 3, 4]


def test_configure_is_idempotent_reconfigures_clean(log_file, tmp_path):
    other = tmp_path / "other.log"
    configure(log_file)
    configure(other)  # reconfigure onto a different file

    log = get_logger("excelops.test")
    log.info("only-here")

    assert not log_file.exists() or log_file.read_text() == ""
    assert read_json_lines(other)[0]["event"] == "only-here"


def test_invalid_level_raises(log_file):
    with pytest.raises(ValueError, match="invalid log level"):
        configure(log_file, level="LOUD")


def test_reset_clears_state(log_file):
    configure(log_file)
    log = get_logger("excelops.test")
    log.info("before-reset")
    assert log_file.exists()

    reset()
    # After reset, stdlib handlers are cleared and structlog is back to default.
    assert logging.getLogger().handlers == []
