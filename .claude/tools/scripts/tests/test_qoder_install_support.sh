#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR"/../../../.. && pwd)"
INSTALL="$PROJECT_ROOT/install.sh"
SETUP="$PROJECT_ROOT/.claude/tools/scripts/setup/setup-harness.sh"
HOOK_SETUP="$PROJECT_ROOT/.claude/tools/scripts/setup/setup-hooks.sh"

grep -q 'codebuddy | codex | qoder | claude | all' "$INSTALL"
grep -q 'QODER_PROJECT_DIR' "$INSTALL"
grep -q 'claude codebuddy codex qoder' "$INSTALL"
grep -q 'local choices=(claude codex codebuddy qoder all)' "$INSTALL"
grep -q 'all).*GEN_TARGETS="codebuddy codex qoder"' "$INSTALL"
grep -q 'qoder).*GEN_TARGETS="qoder"' "$INSTALL"
grep -q 'for _bd in .codex .codebuddy .qoder' "$INSTALL"

grep -q 'qoder).*rd_tools="none"' "$SETUP"
grep -q 'for _bd in .codex .codebuddy .qoder' "$SETUP"
grep -q 'for _bd in .codex .codebuddy .qoder .claude' "$HOOK_SETUP"

echo 'test_qoder_install_support: all tests passed'
