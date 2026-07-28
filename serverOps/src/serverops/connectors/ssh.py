"""SSH connector (asyncssh). The library is imported lazily at connect time."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from ..connectors.base import AsyncConnector, HealthStatus
from ..errors import ConnectionFailed, MissingDependency

#: quick command used by the health probe.
_HEALTH_CMD = "true"


def _asyncssh() -> Any:
    try:
        import asyncssh  # type: ignore[import-not-found]
    except ImportError as e:  # optional extra not installed
        raise MissingDependency(
            "SSH support requires the 'ssh' extra: pip install 'serverops[ssh]'"
        ) from e
    return asyncssh


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


class SSHConnector(AsyncConnector):
    kind = "ssh"

    def __init__(self, name: str, profile: Any) -> None:
        super().__init__(name, profile)
        self._conn: Any = None

    # -- connection ------------------------------------------------------

    def _connect_kwargs(self) -> dict[str, Any]:
        profile = self.profile
        kwargs: dict[str, Any] = {}
        if profile.known_hosts == "ignore":
            # accept any host key — insecure, opt-in only
            kwargs["known_hosts"] = ()
        # "strict" / "accept-new" -> default known_hosts resolution (~/.ssh/known_hosts)
        if profile.key_path:
            kwargs["client_keys"] = [os.path.expanduser(profile.key_path)]
        if profile.password_env:
            password = os.environ.get(profile.password_env)
            if password:
                kwargs["password"] = password
        return kwargs

    async def connect(self) -> None:
        asyncssh = _asyncssh()
        profile = self.profile
        try:
            self._conn = await asyncssh.connect(
                profile.host,
                port=profile.port,
                username=profile.user,
                **self._connect_kwargs(),
            )
        except (OSError, asyncssh.Error) as e:
            raise ConnectionFailed(
                f"SSH connect to {profile.user}@{profile.host}:{profile.port} failed: {e}"
            ) from e

    async def health(self) -> HealthStatus:
        if self._conn is None:
            return HealthStatus(healthy=False, detail="not connected")
        try:
            await self._conn.run(_HEALTH_CMD, check=True, timeout=5)
            return HealthStatus(healthy=True)
        except Exception as e:  # noqa: BLE001 - probe must not raise
            return HealthStatus(healthy=False, detail=str(e))

    # -- operations ------------------------------------------------------

    async def exec(self, command: str, timeout: int = 30) -> dict[str, Any]:
        result = await self._conn.run(command, check=False, timeout=timeout)
        return {
            "exit_status": result.exit_status,
            "stdout": _to_text(result.stdout),
            "stderr": _to_text(result.stderr),
        }

    async def run_script(self, script: str, timeout: int = 60, interpreter: str = "sh") -> dict[str, Any]:
        # Feed the script to the interpreter's stdin so quoting/multiline work safely.
        result = await self._conn.run(
            f"{interpreter} -s", input=script, check=False, timeout=timeout
        )
        return {
            "exit_status": result.exit_status,
            "stdout": _to_text(result.stdout),
            "stderr": _to_text(result.stderr),
        }

    async def upload(self, local_path: str, remote_path: str) -> dict[str, Any]:
        async with self._conn.start_sftp_client() as sftp:
            await sftp.put(local_path, remote_path)
        return {"remote_path": remote_path, "bytes": os.path.getsize(local_path)}

    async def download(self, remote_path: str, local_path: str) -> dict[str, Any]:
        async with self._conn.start_sftp_client() as sftp:
            await sftp.get(remote_path, local_path)
        return {"remote_path": remote_path, "local_path": local_path}

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            with contextlib.suppress(Exception):
                await self._conn.wait_closed()
            self._conn = None


def build(name: str, profile: Any) -> SSHConnector:
    return SSHConnector(name, profile)
