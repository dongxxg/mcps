# 任务完成留痕 — AI 行为约束

> server 通过 `update-task-status` 返回的 `warnings` 字段已包含完整触发逻辑（terminal 状态 + delivery branch 过滤）和自包含 message（A/B/C 三选项）。本规则**不复述 server 实现**，只补充 AI 看到警告后**不可从 server 推导的行为约束**。

## 核心原则

`warnings` 是**软提示**，状态已成功移动。AI 的职责：

1. **不得静默忽略**——任何非空 warning 必须告知用户
2. **不得回滚状态**——warning 不是错误，状态移动已经完成
3. **不得强制上传**——message 的 A/B/C 三选项由用户选，AI 不预设答案

## 上传机制（选项 A 触发时）

`create-attachment-upload-ticket` 是两阶段上传：

```
Step A: mcp__taskboard__create-attachment-upload-ticket({
          taskId, projectId,
          filename, mimeType, size
        })
        → 返回 { uploadUrl, ticketId, expiresAt }

Step B: curl -F 'file=@<path>' <uploadUrl>
        → 返回 { id: attachmentId }
```

约束：
- ticket 10 分钟一次性
- `filename` / `mimeType` / `size` 必须与 Step A 锁定的一致（否则 400）
- 不需要 PAT（ticket 本身是凭证）

## 与 daily-report 的关系

任务完成留痕与 daily-report **相互独立**：
- 任务完成时按本规则处理 warning
- 每日按 daily-report skill 流程提交日报
- 一个任务完成可以不提交当日日报，反之亦然

## 选项 B（commit 已留痕）的判断标准

用户选 B 时，AI 应**验证**而非盲信。检查最近相关 commit 的 message：

| 充分 | 不充分 |
|------|-------|
| 含根因 + 方案 + 影响范围 | "fix bug" / "update code" |
| 引用了 task code（如 `[630]`） | 无 task code 关联 |
| 描述了测试/验证方法 | 仅一行标题 |

判断不确定时回到 A/C 选项让用户决定，不替用户做主。
