"""Safety policy: read-only enforcement + SSH command allow/deny lists +
Redis command gating.

Applied by tool functions before they touch a remote service.
"""

from __future__ import annotations

import re

from .errors import SafetyError
from .models import Settings

#: Redis verbs that only read state. Deliberately excludes compound families
#: whose subcommands split between reads and writes (CONFIG GET vs CONFIG SET,
#: CLIENT GETNAME vs CLIENT KILL, SCRIPT EXISTS vs SCRIPT LOAD, MEMORY USAGE vs
#: MEMORY PURGE, SORT vs SORT ... STORE, XREAD may BLOCK) — anything not listed
#: here is treated as a write and must pass the write gate.
REDIS_READ_COMMANDS: frozenset[str] = frozenset(
    {
        "GET", "MGET", "GETRANGE", "GETBIT", "BITCOUNT", "BITPOS", "STRLEN",
        "BITFIELD_RO", "LPOS",
        "EXISTS", "TYPE", "TTL", "PTTL", "SCAN", "RANDOMKEY", "DUMP",
        "HGET", "HMGET", "HGETALL", "HKEYS", "HVALS", "HLEN", "HEXISTS",
        "HSTRLEN", "HSCAN",
        "LRANGE", "LLEN", "LINDEX",
        "SMEMBERS", "SISMEMBER", "SMISMEMBER", "SCARD", "SRANDMEMBER", "SSCAN",
        "SINTER", "SUNION", "SDIFF",
        "ZRANGE", "ZREVRANGE", "ZRANGEBYSCORE", "ZREVRANGEBYSCORE",
        "ZRANGEBYLEX", "ZREVRANGEBYLEX", "ZSCORE", "ZMSCORE", "ZCARD",
        "ZCOUNT", "ZRANK", "ZREVRANK", "ZLEXCOUNT", "ZSCAN",
        "XRANGE", "XREVRANGE", "XLEN", "XINFO", "XPENDING",
        "PING", "ECHO", "INFO", "DBSIZE", "TIME",
    }
)


class SafetyPolicy:
    """Evaluates operations against the configured safety rules."""

    def __init__(self, settings: Settings) -> None:
        self.read_only = settings.read_only
        self._deny = [re.compile(p, re.IGNORECASE) for p in settings.ssh_command_denylist]
        self._allow = [re.compile(p) for p in settings.ssh_command_allowlist]

    def effective_read_only(self, profile_read_only: bool) -> bool:
        return self.read_only or profile_read_only

    def check_write(self, profile_read_only: bool, operation: str) -> None:
        """Raise ``SafetyError`` if a mutating operation is not permitted."""
        if self.effective_read_only(profile_read_only):
            raise SafetyError(
                f"Operation '{operation}' is blocked because read-only mode is enabled."
            )

    def check_ssh_command(self, command: str) -> None:
        """Validate an SSH command against the allow/deny lists."""
        if self._allow:
            if not any(p.search(command) for p in self._allow):
                raise SafetyError("SSH command is not on the configured allowlist.")
            return
        for pattern in self._deny:
            if pattern.search(command):
                raise SafetyError(
                    f"SSH command matched a denylist pattern: {pattern.pattern}"
                )

    def check_redis_command(self, profile_read_only: bool, command: str) -> None:
        """Allow known read-only Redis commands; treat everything else as a write.

        Conservative by design: an unrecognized verb must pass the write gate,
        so novel or typo'd commands can never mutate state in read-only mode.
        """
        parts = command.split()
        verb = parts[0].upper() if parts else ""
        if verb in REDIS_READ_COMMANDS:
            return
        self.check_write(profile_read_only, "db_query")
