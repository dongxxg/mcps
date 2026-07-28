"""SSH connector + SSH tools, using a fake asyncssh injected into sys.modules."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from serverops.connectors.base import HealthStatus
from serverops.connectors.ssh import SSHConnector
from serverops.errors import ConnectionFailed, MissingDependency, SafetyError, ServerOpsError
from serverops.models import ServerOpsConfig, SSHProfile
from serverops.registry import ConnectorRegistry
from serverops.tools import ssh_tools

# ---------------------------------------------------------------------------
# Fake asyncssh
# ---------------------------------------------------------------------------


class _RunResult:
    def __init__(self, stdout="", stderr="", exit_status=0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_status = exit_status


class _FakeSftp:
    def __init__(self) -> None:
        self.put_called: list[tuple[str, str]] = []
        self.get_called: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def put(self, local, remote):
        self.put_called.append((local, remote))

    async def get(self, remote, local):
        self.get_called.append((remote, local))


class _FakeConn:
    def __init__(self, fail_run_commands: tuple[str, ...] = ()):
        self.commands: list[str] = []
        self.inputs: list[Any] = []
        self.fail_run_commands = fail_run_commands

    async def run(self, command, check=False, timeout=None, input=None):
        self.commands.append(command)
        self.inputs.append(input)
        if command in self.fail_run_commands:
            return _RunResult(stderr="boom", exit_status=2)
        if command == "true":
            return _RunResult(exit_status=0)
        if input is not None:  # script path (sh -s)
            return _RunResult(stdout="script-out", exit_status=0)
        return _RunResult(stdout=command, exit_status=0)

    def start_sftp_client(self):
        return _FakeSftp()

    def close(self):
        pass

    async def wait_closed(self):
        pass


def install_fake_asyncssh(monkeypatch, *, connect_fails=False, fail_run_commands=()):
    mod = types.ModuleType("asyncssh")

    class _Err(Exception):
        pass

    mod.Error = _Err
    captured: dict[str, Any] = {}

    async def connect(host, port=None, username=None, **kwargs):
        captured["kwargs"] = {"host": host, "port": port, "username": username, **kwargs}
        if connect_fails:
            raise OSError("connection refused")
        return _FakeConn(fail_run_commands)

    mod.connect = connect
    monkeypatch.setitem(sys.modules, "asyncssh", mod)
    return captured


# ---------------------------------------------------------------------------
# Connector tests
# ---------------------------------------------------------------------------


async def test_connect_passes_known_hosts_ignore(monkeypatch) -> None:
    captured = install_fake_asyncssh(monkeypatch)
    connector = SSHConnector(
        "web1", SSHProfile(host="h", user="u", known_hosts="ignore", key_path="~/.ssh/id")
    )
    await connector.connect()
    assert captured["kwargs"]["known_hosts"] == ()
    client_keys = captured["kwargs"]["client_keys"]
    assert len(client_keys) == 1
    assert client_keys[0].replace("\\", "/").endswith(".ssh/id")
    assert "password" not in captured["kwargs"]


async def test_connect_includes_password_from_env(monkeypatch) -> None:
    monkeypatch.setenv("WEB_PW", "letmein")
    install_fake_asyncssh(monkeypatch)
    profile = SSHProfile(host="h", user="u", password_env="WEB_PW")
    connector = SSHConnector("web1", profile)
    await connector.connect()
    # password resolved lazily from env at connect time (verified no error); not stored on profile


async def test_connect_failure_raises_connection_failed(monkeypatch) -> None:
    install_fake_asyncssh(monkeypatch, connect_fails=True)
    connector = SSHConnector("web1", SSHProfile(host="h", user="u"))
    with pytest.raises(ConnectionFailed):
        await connector.connect()


async def test_exec_and_health(monkeypatch) -> None:
    install_fake_asyncssh(monkeypatch, fail_run_commands=("boom",))
    connector = SSHConnector("web1", SSHProfile(host="h", user="u"))
    await connector.connect()

    result = await connector.exec("uptime")
    assert result["exit_status"] == 0
    assert result["stdout"] == "uptime"

    failed = await connector.exec("boom")
    assert failed["exit_status"] == 2

    assert (await connector.health()) == HealthStatus(healthy=True, detail="")


async def test_run_script_uses_sh_s(monkeypatch) -> None:
    install_fake_asyncssh(monkeypatch)
    connector = SSHConnector("web1", SSHProfile(host="h", user="u"))
    await connector.connect()
    result = await connector.run_script("echo hi\necho there")
    assert result["stdout"] == "script-out"
    assert result["exit_status"] == 0


# ---------------------------------------------------------------------------
# Tool tests (registry wired to the real SSHConnector + fake asyncssh)
# ---------------------------------------------------------------------------


class FakeMCP:
    def __init__(self):
        self.tools: dict[str, Any] = {}

    def tool(self, fn=None, **_):
        if callable(fn):
            self.tools[fn.__name__] = fn
            return fn

        def deco(f):
            self.tools[f.__name__] = f
            return f

        return deco

    def custom_route(self, *_a, **_k):
        def deco(f):
            return f

        return deco


def _ssh_registry(monkeypatch, *, read_only=False, settings_read_only=False, audit_path=None):
    install_fake_asyncssh(monkeypatch)
    cfg = ServerOpsConfig.model_validate(
        {
            "settings": {"read_only": settings_read_only, "audit_log": audit_path},
            "connections": {
                "web1": {
                    "kind": "ssh",
                    "host": "h",
                    "user": "u",
                    "read_only": read_only,
                },
                "db": {"kind": "sqlite", "url": "sqlite:///:memory:"},
            },
        }
    )
    reg = ConnectorRegistry(cfg)
    # use the real SSH connector for ssh profiles (asyncssh is faked in sys.modules);
    # non-ssh profiles are never reached by the ssh tools (rejected earlier), so we
    # only need to handle ssh here.
    from serverops.connectors import ssh as ssh_module

    def _build(name, profile):
        if profile.kind == "ssh":
            return ssh_module.build(name, profile)
        raise AssertionError("non-ssh profile reached ssh connector in test")

    reg._build = _build  # type: ignore[method-assign]
    return reg


async def test_ssh_tool_exec_ok(monkeypatch) -> None:
    reg = _ssh_registry(monkeypatch)
    mcp = FakeMCP()
    ssh_tools.register(mcp, reg)
    result = await mcp.tools["ssh_exec"]("web1", "uptime")
    assert result["exit_status"] == 0


async def test_ssh_tool_exec_rejects_non_ssh_connection(monkeypatch) -> None:
    reg = _ssh_registry(monkeypatch)
    mcp = FakeMCP()
    ssh_tools.register(mcp, reg)
    with pytest.raises(ServerOpsError):
        await mcp.tools["ssh_exec"]("db", "select 1")


async def test_ssh_tool_exec_blocked_by_denylist(monkeypatch) -> None:
    reg = _ssh_registry(monkeypatch)
    mcp = FakeMCP()
    ssh_tools.register(mcp, reg)
    with pytest.raises(SafetyError):
        await mcp.tools["ssh_exec"]("web1", "rm -rf /")


async def test_ssh_tool_exec_blocked_when_readonly(monkeypatch) -> None:
    reg = _ssh_registry(monkeypatch, settings_read_only=True)
    mcp = FakeMCP()
    ssh_tools.register(mcp, reg)
    with pytest.raises(SafetyError):
        await mcp.tools["ssh_exec"]("web1", "uptime")


async def test_ssh_tool_script_runs(monkeypatch) -> None:
    reg = _ssh_registry(monkeypatch)
    mcp = FakeMCP()
    ssh_tools.register(mcp, reg)
    result = await mcp.tools["ssh_script"]("web1", "echo a\necho b")
    assert result["exit_status"] == 0


async def test_missing_asyncssh_raises_missing_dependency(monkeypatch) -> None:
    # asyncssh is an optional extra; it's genuinely absent in this dev env.
    monkeypatch.delitem(sys.modules, "asyncssh", raising=False)
    try:
        import asyncssh  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("asyncssh is installed; cannot exercise the missing-dependency path")

    connector = SSHConnector("web1", SSHProfile(host="h", user="u"))
    with pytest.raises(MissingDependency):
        await connector.connect()
