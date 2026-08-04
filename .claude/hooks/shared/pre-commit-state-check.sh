#!/usr/bin/env bash
# PreToolUse hook: git commit 前校验
# 职责：GATE_BYPASS Challenge-Response 验证
# 格式校验已迁移到 git commit-msg hook（.claude/hooks/git/commit-msg）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/hook-json-helper.sh"

INPUT=$(cat)
COMMAND=$(_jq_raw "$INPUT" command)

# 只拦截 git commit
if ! echo "$COMMAND" | grep -qE '(^|&&|\||\;|\s)git\s+commit\b'; then
    exit 0
fi

PROJECT_DIR="${QODER_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-.}}"

deny() {
    hook_deny "$1"
    exit 0
}

# ── GATE_BYPASS 禁止 ──
# 不允许绕过质量门禁
COMMIT_MSG=""
if [ -f "$PROJECT_DIR/.git/COMMIT_EDITMSG" ]; then
    COMMIT_MSG=$(cat "$PROJECT_DIR/.git/COMMIT_EDITMSG" 2>/dev/null || true)
fi

if echo "$COMMIT_MSG" | grep -qE 'GATE_BYPASS:'; then
    deny "请修复 P0 问题后正常提交。"
fi

exit 0
