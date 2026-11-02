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


# ---------------------------------------------------------------------------
# Redis command gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "GET key",
        "MGET a b c",
        "HGETALL hash",
        "HMGET hash f1 f2",
        "LRANGE list 0 -1",
        "SMEMBERS set",
        "ZRANGE zset 0 -1 WITHSCORES",
        "ZRANGEBYSCORE z 0 10",
        "SCAN 0 MATCH x*",
        "TTL key",
        "PTTL key",
        "EXISTS key",
        "TYPE key",
        "STRLEN key",
        "DBSIZE",
        "INFO",
        "PING",
        "TIME",
        "XLEN stream",
        "XRANGE stream - +",
        "LPOS list 5",
        "XPENDING stream",
        "SMISMEMBER set a b",
        "BITFIELD_RO key GET u8 0",
    ],
)
def test_redis_read_commands_pass_when_readonly(command: str) -> None:
    pol = SafetyPolicy(Settings(read_only=True))
    pol.check_redis_command(profile_read_only=True, command=command)  # no raise


@pytest.mark.parametrize(
    "command",
    [
        "SET key value",
        "DEL key",
        "FLUSHALL",
        "FLUSHDB",
        "INCR counter",
        "EXPIRE key 10",
        "HSET hash field value",
        "LPUSH list value",
        "SADD set value",
        "ZADD zset 1 member",
        # compound families: first token alone cannot prove read intent
        "CONFIG SET maxmemory 0",
        "CONFIG GET maxmemory",
        "CLIENT KILL id 12",
        "CLIENT GETNAME",
        "SCRIPT LOAD 'return 1'",
        "MEMORY PURGE",
        "SORT mylist STORE dst",
    ],
)
def test_redis_write_and_compound_commands_blocked_when_readonly(command: str) -> None:
    pol = SafetyPolicy(Settings(read_only=True))
    with pytest.raises(SafetyError):
        pol.check_redis_command(profile_read_only=True, command=command)


def test_redis_unknown_command_treated_as_write() -> None:
    ro = SafetyPolicy(Settings(read_only=True))
    with pytest.raises(SafetyError):
        ro.check_redis_command(profile_read_only=True, command="WHATEVER key")
    rw = SafetyPolicy(Settings(read_only=False))
    rw.check_redis_command(profile_read_only=False, command="WHATEVER key")  # no raise
