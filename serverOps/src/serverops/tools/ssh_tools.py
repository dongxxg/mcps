"""SSH tools: ssh_exec / ssh_script / ssh_upload / ssh_download."""

from __future__ import annotations

import os

from ..errors import ServerOpsError
from ._common import redacted


def _safe_local_path(path: str) -> str:
    """Normalize a local path. Rejects empty / null-byte paths.

    Note: for v1 upload/download operate on full paths chosen by the operator.
    A future revision may add a ``transfer_dir`` jail (set via env) to constrain
    them further.
    """
    if not path or "\x00" in path:
        raise ServerOpsError("Invalid local path.")
    return os.path.abspath(os.path.expanduser(path))


def register(mcp, registry) -> None:
    def _require_ssh(connection: str):
        profile = registry.get_profile(connection)
        if profile.kind != "ssh":
            raise ServerOpsError(
                f"Connection '{connection}' is kind='{profile.kind}', not 'ssh'."
            )
        return profile

    @mcp.tool
    @redacted
    async def ssh_exec(connection: str, command: str, timeout: int = 30) -> dict:
        """Run a single shell command on an SSH host.

        Subject to read-only gating and the SSH command deny/allow lists.
        Returns exit_status, stdout, stderr.
        """
        profile = _require_ssh(connection)
        registry.safety.check_write(profile.read_only, "ssh_exec")
        registry.safety.check_ssh_command(command)
        connector = await registry.get(connection)
        result = await connector.exec(command, timeout=timeout)
        registry.audit.record(
            connection=connection,
            operation="ssh_exec",
            status="ok" if result["exit_status"] == 0 else f"exit:{result['exit_status']}",
            detail=command[:200],
        )
        return result

    @mcp.tool
    @redacted
    async def ssh_script(connection: str, script: str, timeout: int = 60) -> dict:
        """Run a multi-line shell script (a string) on an SSH host via ``sh -s``.

        Same read-only/denylist policy as ssh_exec.
        """
        profile = _require_ssh(connection)
        registry.safety.check_write(profile.read_only, "ssh_script")
        registry.safety.check_ssh_command(script)
        connector = await registry.get(connection)
        result = await connector.run_script(script, timeout=timeout)
        registry.audit.record(
            connection=connection,
            operation="ssh_script",
            status="ok" if result["exit_status"] == 0 else f"exit:{result['exit_status']}",
        )
        return result

    @mcp.tool
    @redacted
    async def ssh_upload(connection: str, local_path: str, remote_path: str) -> dict:
        """Upload a local file to an SSH host via SFTP."""
        _require_ssh(connection)
        local_path = _safe_local_path(local_path)
        connector = await registry.get(connection)
        result = await connector.upload(local_path, remote_path)
        registry.audit.record(
            connection=connection,
            operation="ssh_upload",
            status="ok",
            detail=f"{local_path} -> {remote_path}",
        )
        return result

    @mcp.tool
    @redacted
    async def ssh_download(connection: str, remote_path: str, local_path: str) -> dict:
        """Download a file from an SSH host to the local machine via SFTP."""
        _require_ssh(connection)
        local_path = _safe_local_path(local_path)
        connector = await registry.get(connection)
        result = await connector.download(remote_path, local_path)
        registry.audit.record(
            connection=connection,
            operation="ssh_download",
            status="ok",
            detail=f"{remote_path} -> {local_path}",
        )
        return result
