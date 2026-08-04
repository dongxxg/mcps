# 自动意图路由

> 当 PM 输入开发类指令时，自动调用 `/rd-auto` 进行意图分析和角色派活，而不是手动实现。

## 触发规则

### 意图速查（判断时对照）

| PM 说的关键词 | 意图类别 | 强制动作 |
|---|---|---|
| 实现/做/开发/新增/添加 + 具体描述 | 功能开发 | → `/rd-auto` |
| 修复/fix/解决 + 问题描述 | Bug 修复 | → `/rd-auto`（intent_category=bug_fix） |
| 热修复/紧急/hotfix | 热修复 | → `/rd-auto`（flow-type=hotfix） |
| 重构/优化结构/拆分/合并模块 | 重构 | → `/rd-auto` |
| 补测试/加测试/测试覆盖 | 补测试 | → `/rd-auto` |
| 改配置/环境变量/CI配置 | 配置变更 | → `/rd-auto` |
| 写文档/ADR/补充说明/更新设计文档 | 写文档 | → `/rd-auto` |
| 继续/接着/resume + 任务名 | 继续任务 | → `/rd-auto` |

### 必须触发（违反 = 漏判，PM 应提示模型）

> **硬规则**：用户消息**主要意图**匹配以下任一类别时，**必须**调用 `Skill(skill="rd-auto")`，不得自行实现或仅口头回应。

用户消息**主要意图**是以下之一时：
- **功能开发**：实现/做/开发/新增/添加/功能 + 具体描述
- **Bug 修复**：修复/fix/解决 + 问题描述
- **热修复**：热修复/紧急/hotfix/线上问题
- **重构**：重构/优化结构/拆分/合并模块
- **补测试**：补测试/加测试/测试覆盖
- **配置变更**：改配置/环境变量/CI配置
- **写文档**：写文档/ADR/补充说明/更新设计文档
- **继续任务**：继续/接着/resume + 任务名

**判断原则**：
- 匹配**主要意图**即可触发——即使消息含次要内容（如"顺便问下 XX"），仍按主意图路由
- 宁可多触发不漏判——自行实现后再补 rd-auto 的代价 >> 误触发的一次确认成本

### 不触发（正常对话）

- 简单提问（"XX 是什么"、"怎么用 YY"）
- 代码探索（"看下这个文件"、"搜索 XX"）
- Git 操作（拉取/推送/提交/分支）
- 项目管理（查看状态、看板、日报）
- 明确以 `/` 开头的其他 skill 命令
- 对话中的追问、澄清、确认

## 应急召唤（模型漏判时的兜底）

如果模型**没有**自动触发 rd-auto，PM 可说以下任一语句**强制召唤**：

- `"用 rd-auto 做 <任务描述>"`
- `"/rd-auto <任务描述>"`
- `"走 rd-auto 流程：<任务描述>"`

模型收到上述语句后，**必须**立即调用 `Skill(skill="rd-auto")`，不得以任何理由跳过。

## 执行方式

触发后：
1. **意图明确**（高置信度）：直接调用 `Skill(skill="rd-auto")`，无需确认
2. **意图模糊**（不确定类别）：先调用 `/rd-auto parse "<PM 原话>"` 获取结构化意图-json，再按结果路由
3. **意图过弱**（<0.6，如"这个文件是干什么的"）：不触发，正常对话

## 优先级（从高到低）

1. PM 明确说"用 rd-auto 做 X" → 立即调用 `Skill(rd-auto)`，不做其他事
2. PM 说 `/rd-auto ...` → 直接执行该命令
3. 自然语言匹配意图 → 自动触发 `Skill(rd-auto)`
4. 其他 `/` 命令（如 `/rd:explore`）→ 执行该命令，不路由到 rd-auto

## intent_category 与 flow-type 自动升级（bug_fix 必读）

`orchestrator init` 时若 `--intent-json` 含 `intent_category`，会**自动升级到 quick flow**（轻量 5 阶段，不经 propose/design-review，不强制 proposal/design/spec）：

- **触发条件**：`intent_category ∈ [bug_fix, quick_change, code_review, testing]` + `confidence ≥ 0.85` + `affected_files ≤ 3`
- **实现位置**：`cli-commands.js` auto-upgrade-to-quick（即便 `--flow-type development`，含合规 intent_category 也会自动升 quick）

**操作要点**：bug_fix / 根因明确的小修复，init 时务必在 `--intent-json` 传 `intent_category`，否则即便根因明确也会走 development 全套（产出冗余制品）：

```bash
node .claude/skills/rd-auto/scripts/orchestrator.js init <name> \
  --flow-type development \
  --intent-json '{"task_type":"...","intent_category":"bug_fix","confidence":0.9,"affected_files":["path"],"complexity_hint":"S"}' \
  --criteria "..."
```

> 实证：fix-push-cleanup-hook（30 行 hook 修复）因 init 未传 `intent_category` 走了 development 全套，产出 ~2400 行文档；若传 `bug_fix` 会自动升 quick。这是操作问题，非框架缺陷——无需新机制，传对字段即可。
