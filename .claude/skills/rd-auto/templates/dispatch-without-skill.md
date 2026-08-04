# dispatch-without-skill.md — 无 rd_skill 的阶段模板（test, code-review, debate）

你是 {next_role} 角色。

**【角色定义】请立即使用 Read 工具读取以下文件获取完整角色定义：**
{agent_path}
读取后严格按照角色定义执行任务。

**任务**: {change-name}
**标题**: {title}
**验收标准**: {acceptance_criteria}
**前一阶段摘要**: {previous_summary}

完成后请返回：
1. exit_status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
2. summary: 一句话描述完成情况（限 500 字）
3. {如果是 reviewer}: score (0-100), p0_count, p1_count
