'use strict';

// synthesize-tasks.js — 把 MCP 原始输出合成归一化 tasks.json
//
// 模型只需：
//   1. mcp__taskboard__list-tasks({assignedToMe:true,verbose:true}) → raw-tasks.json
//   2. mcp__taskboard__list-task-statuses({projectId})               → statuses.json
//   3. mcp__taskboard__list-project-members({projectId})             → members.json
//   4. 跑本脚本
//
// 用法：
//   node synthesize-tasks.js \
//     --tasks @raw-tasks.json \
//     --statuses @statuses.json \
//     --members @members.json \
//     --user wangzk \
//     --output tasks.json

const fs = require('node:fs');
const path = require('node:path');
const { parseArgs } = require('./lib/argv');

function readJsonInput(rawArg, label) {
  if (!rawArg || typeof rawArg !== 'string') {
    throw new Error(`missing --${label}`);
  }
  if (rawArg.startsWith('@')) {
    return JSON.parse(fs.readFileSync(rawArg.slice(1), 'utf-8'));
  }
  return JSON.parse(rawArg);
}

function fail(stderrLine) {
  process.stderr.write(stderrLine + '\n');
  process.exit(1);
}

function main() {
  const args = parseArgs(process.argv, {
    flags: [],
    options: { tasks: '', statuses: '', members: '', user: '', output: '', 'assignee-filter': '' },
  });
  const opts = args.options;
  const missing = ['tasks', 'statuses', 'members', 'user', 'output'].filter((k) => !opts[k]);
  if (missing.length) {
    fail(`synthesize-tasks.js: missing required option(s): ${missing.join(', ')}`);
  }

  let rawTasks, statuses, members;
  try {
    rawTasks = readJsonInput(opts.tasks, 'tasks');
    statuses = readJsonInput(opts.statuses, 'statuses');
    members = readJsonInput(opts.members, 'members');
  } catch (e) {
    fail(`synthesize-tasks.js: ${e.message}`);
  }

  if (!Array.isArray(rawTasks)) fail('synthesize-tasks.js: --tasks must be a JSON array');
  if (!Array.isArray(statuses)) fail('synthesize-tasks.js: --statuses must be a JSON array');
  if (!Array.isArray(members)) fail('synthesize-tasks.js: --members must be a JSON array');

  // 查表索引
  const statusMap = new Map(statuses.map((s) => [s.id, s]));
  const memberMap = new Map(members.map((m) => [m.userId, m]));

  // issue !147: 按 assignee 过滤（可选，向后兼容）
  // 传 --assignee-filter <name> 时按匹配 userId 的 assigneeId 过滤；
  // 解析不到 userId 时 fail-open（warn 但不过滤），避免静默吞数据。
  let filteredTasks = rawTasks;
  let filteredOut = 0;
  if (opts['assignee-filter']) {
    const filterName = opts['assignee-filter'];
    const member = members.find((m) => (m.git_username || m.name) === filterName);
    if (member && member.userId) {
      const before = rawTasks.length;
      filteredTasks = rawTasks.filter((t) => t.assigneeId === member.userId);
      filteredOut = before - filteredTasks.length;
    } else {
      // fail-open：找不到 userId 时不过滤，warn 不报错
      process.stderr.write(
        `[synthesize-tasks] warn: cannot resolve userId for "${filterName}" in members; skipping filter (output may contain unassigned tasks)\n`
      );
    }
  }

  const synthesized = filteredTasks.map((t) => {
    const status = statusMap.get(t.statusId) || {};
    const assignee = memberMap.get(t.assigneeId) || null;
    return {
      id: t.id,
      code: t.code || '',
      title: t.title,
      status: {
        id: status.id || t.statusId,
        name: status.name || t.status || '',
        color: status.color || t.statusColor || '',
        is_terminal: Boolean(status.isTerminal !== undefined ? status.isTerminal : status.is_terminal),
        is_initial: Boolean(status.isInitial !== undefined ? status.isInitial : status.is_initial),
      },
      priority: t.priority || 'medium',
      assignee: assignee ? { id: assignee.userId, name: assignee.name, email: assignee.email || '' } : null,
      due_date: t.dueDate ? t.dueDate.slice(0, 10) : null,
      branch_id: t.branchId || null,
    };
  });

  const outputDir = path.dirname(opts.output);
  try {
    fs.mkdirSync(outputDir, { recursive: true });
  } catch (e) {
    fail(`synthesize-tasks.js: failed to create output dir: ${e.message}`);
  }

  try {
    fs.writeFileSync(opts.output, JSON.stringify(synthesized, null, 2) + '\n', 'utf-8');
  } catch (e) {
    fail(`synthesize-tasks.js: failed to write --output: ${e.message}`);
  }

  process.stdout.write(
    JSON.stringify({ ok: true, output: opts.output, count: synthesized.length, filtered_out: filteredOut }) + '\n'
  );
}

main();
