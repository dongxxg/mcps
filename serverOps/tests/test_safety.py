"""Safety policy: read-only gating + SSH command deny/allow lists."""

from __future__ import annotations

import pytest

from serverops.errors import SafetyError
from serverops.models import Settings
from serverops.safety import SafetyPolicy


def test_write_allowed_when_not_readonly() -> None:
    pol = SafetyPolicy(Settings(read_only=False))
    pol.check_write(profile_read_only=False, operation="db_execute")  # no raise


def test_global_readonly_blocks_writes() -> None:
    pol = SafetyPolicy(Settings(read_only=True))
    with pytest.raises(SafetyError):
        pol.check_write(profile_read_only=False, operation="db_execute")


def test_per_profile_readonly_blocks_writes() -> None:
    pol = SafetyPolicy(Settings(read_only=False))
    with pytest.raises(SafetyError):
        pol.check_write(profile_read_only=True, operation="db_execute")


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf / 2>/dev/null",
        "sudo mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda bs=1M",
        "shutdown -h now",
        "reboot",
    ],
)
def test_denylist_blocks_dangerous_commands(command: str) -> None:
    pol = SafetyPolicy(Settings())
    with pytest.raises(SafetyError):
        pol.check_ssh_command(command)


@pytest.mark.parametrize(
    "command",
    ["ls -la /var", "uptime", "df -h", "cat /etc/hostname", "ps aux | grep nginx"],
)
def test_denylist_allows_safe_commands(command: str) -> None:
    pol = SafetyPolicy(Settings())
    pol.check_ssh_command(command)  # no raise


def test_allowlist_blocks_unlisted() -> None:
    pol = SafetyPolicy(Settings(ssh_command_allowlist=[r"\bls\b"]))
    pol.check_ssh_command("ls -la")
    with pytest.raises(SafetyError):
        pol.check_ssh_command("uptime")
