#!/usr/bin/env bash
# PreToolUse hook: 组合 Git 操作守卫
# - 禁止读写框架保护文件
# - 禁止 git pull 拉取基线分支 main/master
# - 禁止本地 git merge 合并不同分支
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/hook-json-helper.sh"

INPUT=$(cat)
TOOL=$(_jq_val "$INPUT" tool_name)

case "$TOOL" in
    Bash) ;;
    *) exit 0 ;;
esac

COMMAND=$(_jq_val "$INPUT" command)

# ── 1) 框架保护路径 / bypass 文件 ──
# 保护策略：Edit/Write 工具侧已有 guard，Bash 侧只拦破坏性操作。
# git add/status/diff 等无害操作不受影响。
# 框架目录默认即本 agent 目录；generator 注入 HARNESS_ROOT 让非 Claude 环境复用同一目录。
# 单引号 ERE 里无法内插 $HARNESS_ROOT（会被当成行尾锚），故运行时先转义再拼正则。
_HARNESS_DIR="${HARNESS_ROOT:-.claude}"
_HARNESS_DIR_RE="$(printf '%s' "$_HARNESS_DIR" | sed -e 's/[][\.*^$/]/\\&/g')"
_PROTECTED_RE="(\\.git[/\\\\]hooks[/\\\\]|${_HARNESS_DIR_RE}[/\\\\]hooks[/\\\\])"
_BYPASS_FILES_RE="(\\.harness[/\\\\]\\.framework-edit|\\.harness[/\\\\]\\.push-challenge|\\.framework-edit|\\.push-challenge)"
_SAFE_GIT_RE='^git[[:space:]]+(add|status|diff|log|stash)[[:space:]]'

if echo "$COMMAND" | grep -qE "$_SAFE_GIT_RE"; then
    : # git add/status/diff 不拦截
elif echo "$COMMAND" | grep -qE "$_PROTECTED_RE"; then
    hook_deny "框架保护区，AI 止步。这些文件只有人类的肉身之手才能碰——去请 PM 帮你吧。"
    exit 0
elif echo "$COMMAND" | grep -qE "$_BYPASS_FILES_RE"; then
    hook_deny "框架保护区，AI 止步。这些文件只有人类的肉身之手才能碰——去请 PM 帮你吧。"
    exit 0
fi

# ── 2) 禁止 git pull 拉取 main/master（无 --rebase）──
# 含 --rebase 时放行（如 git pull --rebase origin main，是合法的基线同步），
# 因为 --rebase 不会产生 merge commit。--no-rebase 不含子串 --rebase，仍被拦。
if echo "$COMMAND" | grep -qE '(^|[;&|][[:space:]]*)git[[:space:]]+pull[[:space:]]+.*\b(main|master)\b' \
   && ! echo "$COMMAND" | grep -qE -- '--rebase'; then
    hook_deny "禁止通过 git pull 拉取基线分支 main/master。基线同步必须通过 GitLab Merge Request 流程，确保代码评审和 CI 门禁。"
    exit 0
fi

# ── 2.5) 禁止裸 git pull（无 --rebase）──
# 裸 git pull 默认走 merge 策略，落后远端时产生 merge commit，
# 被服务端 pre-receive 拒（事后拦截，AI 已 push 失败需返工）。
# 同步远端统一用 git pull --rebase。--no-rebase 不含子串 --rebase，仍被拦。
if echo "$COMMAND" | grep -qE '(^|[;&|][[:space:]]*)git[[:space:]]+pull([[:space:]]|$)' \
   && ! echo "$COMMAND" | grep -qE -- '--rebase'; then
    hook_deny "禁止裸 git pull（默认 merge 策略会产生 merge commit 被服务端 pre-receive 拒绝）。同步远端请用 git pull --rebase。"
    exit 0
fi

# ── 3) 禁止本地 git merge 合并分支 ──
if echo "$COMMAND" | grep -qE '(^|[;&|][[:space:]]*)git[[:space:]]+merge([[:space:]]|$)'; then
    hook_deny "禁止本地 git merge 合并不同分支。分支合并必须通过 GitLab Merge Request 流程，确保代码评审和 CI 门禁。"
    exit 0
fi

exit 0
