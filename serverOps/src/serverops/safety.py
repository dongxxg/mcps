"""Safety policy: read-only enforcement + SSH command allow/deny lists.

Applied by tool functions before they touch a remote service.
"""

from __future__ import annotations

import re

from .errors import SafetyError
from .models import Settings


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
