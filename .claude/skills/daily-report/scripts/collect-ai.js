'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { parseArgs } = require('./lib/argv');

// --- CST date helper (统一走 lib/time.js) ---
const { todayCST, isDateMatch } = require('./lib/time');

// --- Auto-detect backend directory (claude/codex/codebuddy/qoder) ---
// 解析顺序（高 → 低）：
//   1. HARNESS_BACKEND env（用户/hook 显式指定）
//   2. 当前运行 client 对应目录（detectClient 识别 claude-code/codex/codebuddy/qoder）
//   3. 存在性 fallback 列表（codebuddy 等无 client 信号时）
// Bug: 原 fallback 优先级硬编码 .codebuddy>.codex>.claude，当机器同时存在
//   ~/.codebuddy 与 ~/.claude 时，Claude Code session 的 token 被错误地从
//   ~/.codebuddy 采集（当前 session 数据在 ~/.claude，结果 session_count=0、token 全 0）。
// 修复：当前 client 对应目录优先于存在性 fallback，避免读到别的 backend 的数据。
function clientBackendDir(clientName) {
  switch (clientName) {
    case 'claude-code': return '.claude';
    case 'codex':       return '.codex';
    case 'qoder':       return '.qoder';
    default:            return null;  // codebuddy/cursor 等无映射 → 走存在性 fallback
  }
}

function detectBackendDir(subdir) {
  // 1. HARNESS_BACKEND 显式指定优先
  const be = process.env.HARNESS_BACKEND;
  if (be) {
    const p = path.join(os.homedir(), '.' + be, subdir);
    if (fs.existsSync(p)) return p;
  }
  // 2. 当前运行 client 对应目录（修复：避免 claude-code 读到 .codebuddy）
  const clientDir = clientBackendDir(detectClient(process.env).name);
  if (clientDir) {
    const p = path.join(os.homedir(), clientDir, subdir);
    if (fs.existsSync(p)) return p;
  }
  // 3. 存在性 fallback：codebuddy/cursor 等无 client 信号时
  for (const bd of ['.qoder', '.codebuddy', '.codex', '.claude']) {
    const p = path.join(os.homedir(), bd, subdir);
    if (fs.existsSync(p)) return p;
  }
  return path.join(os.homedir(), '.claude', subdir);
}

// --- Phase-to-role mapping ---
// Design review note: intake/smoke phases map to null (system auto), not counted in role stats
// Issue !189 Bug1: design-review 实际角色是 developer（harness-rules.yaml:760-762），
// 原映射 architect 致 by_role 桶错位。
// Issue !194: quick-flow 的 dispatch/verify 阶段角色依赖 state.intent.intent_category
// 动态路由（见 advance.js resolveQuickFlowRole），静态表无法表达——dispatch 通过
// resolveDispatchRole(state) 动态查，verify 兜底 developer（最常见）。
const PHASE_ROLE_MAP = {
  explore: 'architect',
  propose: 'architect',
  'design-review': 'developer',
  implement: 'developer',
  test: 'tester',
  smoke: null,
  'code-review': 'reviewer',
  debate: 'reviewer',
  intake: null,
  // quick-flow 阶段
  verify: 'developer',
};

// Issue !194: quick-flow dispatch 阶段角色按 intent_category 路由
// 复刻 advance.js resolveQuickFlowRole 逻辑（不能 import ESM，此处内联副本）
function resolveDispatchRole(state) {
  if (!state || state.flow_type !== 'quick') return 'developer';
  const cat = state.intent && state.intent.intent_category;
  switch (cat) {
    case 'bug_fix':        return 'developer';
    case 'code_review':    return 'reviewer';
    case 'testing':        return 'tester';
    case 'explore_design': return 'architect';
    case 'quick_change': {
      const n = (state.intent && state.intent.affected_files || []).length;
      return n >= 3 ? 'developer' : null;  // <=2 files: 主会话自处理
    }
    default: return 'developer';  // 兜底
  }
}

// 根据 phase + state 解析角色：先查静态表，dispatch 阶段特殊处理（quick-flow 动态路由）
function resolvePhaseRole(phase, state) {
  if (phase === 'dispatch') return resolveDispatchRole(state);
  return PHASE_ROLE_MAP[phase] || null;
}

// --- SPEC terminal phases ---
const TERMINAL_PHASES = new Set(['archive', 'merge-prep', 'completed', 'complete']);

// --- Empty output structure ---
function emptyOutput(date, cwd) {
  const emptyTriggerBucket = () => ({ dispatch_count: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0, by_role: {}, by_model: {} });
  // by_backend bucket：按 backend 分组聚合 token（Claude/Codex 各算各的，不求和）
  // 字段语义与 stats.js 对齐：null 表示「该 backend 下不可用」（如 codex 的 input/output/cached）
  const emptyBackendBucket = () => ({
    dispatch_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    cached_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 0,
    model: null,
    _modelCounts: {},
    _seen: { input: false, output: false, cached: false, reasoning: false, total: false },
  });
  const harnessVersion = readHarnessVersion(cwd);
  const client = detectClient(process.env);

  return {
    date,
    harness_version: harnessVersion,
    client_name: client.name,
    client_version: client.version,
    tasks: [],
    summary: {
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_dispatches: 0,
      total_wall_clock_ms: 0,
      // Dispatch breakdown by trigger type (pipeline = AI自动调度, natural = 人工调度)
      dispatch_by_trigger: {
        pipeline: emptyTriggerBucket(),
        natural: emptyTriggerBucket(),
      },
      // 新增维度：按 backend 分组聚合 token（Claude/Codex 不混合求和）
      by_backend: {},
      backend_fallback_count: 0,
      spec_stats: { total_changes: 0, closed_loop: 0, open: 0, by_phase: {} },
      concern_stats: { total: 0, p0_found: 0, p0_closed: 0, p1_found: 0, p1_closed: 0 },
      // 采样缺口计数：usage.jsonl 中 tokens:null 的短命 subagent 记录数
      sampled_gap_count: 0,
      session_input_tokens: 0,
      session_output_tokens: 0,
      session_cache_creation_input_tokens: 0,
      session_cache_read_input_tokens: 0,
      session_count: 0,
      session_by_project: {},
      session_by_model: {},
    },
  };
}

// 把单条 dispatch 的 token_usage（pipeline-state）或 entry.tokens（usage.jsonl）聚合到 by_backend
// backend 兜底：缺失 → 'claude'（向前兼容）；未知 → 'unknown' + stderr 告警（去重，与 stats.js 一致）
const _warnedUnknownBackendsCollectAi = new Set();
function aggregateByBackend(summary, backend, normalized) {
  if (!backend) {
    backend = 'claude';
    summary.backend_fallback_count++;
  } else if (!['claude', 'codex', 'codebuddy', 'qoder'].includes(backend)) {
    if (!_warnedUnknownBackendsCollectAi.has(backend)) {
      _warnedUnknownBackendsCollectAi.add(backend);
      console.error(`[harness] Warning: Unknown backend value: ${backend} (aggregated into 'unknown' group)`);
    }
    backend = 'unknown';
  }
  if (!summary.by_backend[backend]) summary.by_backend[backend] = {
    dispatch_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    cached_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 0,
    model: null,
    _modelCounts: {},
    _seen: { input: false, output: false, cached: false, reasoning: false, total: false },
  };
  const b = summary.by_backend[backend];
  b.dispatch_count++;
  if (normalized.input !== null) { b.input_tokens += normalized.input; b._seen.input = true; }
  if (normalized.output !== null) { b.output_tokens += normalized.output; b._seen.output = true; }
  if (normalized.cached !== null) { b.cached_tokens += normalized.cached; b._seen.cached = true; }
  if (normalized.reasoning !== null) { b.reasoning_tokens += normalized.reasoning; b._seen.reasoning = true; }
  if (normalized.total !== null) { b.total_tokens += normalized.total; b._seen.total = true; }
  if (normalized.model) {
    b._modelCounts[normalized.model] = (b._modelCounts[normalized.model] || 0) + 1;
  }
}

// 把 pipeline-state.json 的 token_usage（Claude transcript 格式 / Codex 单值）归一化
// 与 stats.js normalizeTokenUsage 对齐（重复实现以避免 cross-module import）
function normalizeTokenUsageForReport(rawTokens, backend) {
  const be = (backend || 'claude').toLowerCase();
  const t = rawTokens || {};
  if (be === 'codex' || be === 'qoder') {
    const total = typeof t.total === 'number' ? t.total : null;
    return { input: null, output: null, cached: null, reasoning: null, total, model: null };
  }
  if (be === 'claude' || be === 'codebuddy') {
    return {
      input: typeof t.input_tokens === 'number' ? t.input_tokens : null,
      output: typeof t.output_tokens === 'number' ? t.output_tokens : null,
      cached: typeof t.cache_read_input_tokens === 'number' ? t.cache_read_input_tokens : null,
      reasoning: null,
      total: null,
      model: typeof t.model === 'string' ? t.model : null,
    };
  }
  // unknown backend
  return { input: null, output: null, cached: null, reasoning: null, total: null, model: null };
}

// Finalize by_backend bucket：dominant model + 未见过非 null 的字段设 null
function finalizeByBackend(summary) {
  for (const bucket of Object.values(summary.by_backend)) {
    const entries = Object.entries(bucket._modelCounts || {});
    if (entries.length > 0) {
      bucket.model = entries.sort((a, b) => b[1] - a[1])[0][0];
    }
    delete bucket._modelCounts;
    const seen = bucket._seen || {};
    if (!seen.input) bucket.input_tokens = null;
    if (!seen.output) bucket.output_tokens = null;
    if (!seen.cached) bucket.cached_tokens = null;
    if (!seen.reasoning) bucket.reasoning_tokens = null;
    if (!seen.total) bucket.total_tokens = null;
    delete bucket._seen;
  }
}

// usage.jsonl 条目归一化（字段名：input/output/cache_read/cache_creation/total/model）
// 与 pipeline-state 的 normalizeTokenUsageForReport 区别：字段名不同（无 _input_tokens 后缀）
function normalizeUsageJsonlTokens(tokens, backend) {
  const be = (backend || 'claude').toLowerCase();
  const t = tokens || {};
  if (be === 'codex' || be === 'qoder') {
    const total = typeof t.total === 'number' ? t.total : null;
    return { input: null, output: null, cached: null, reasoning: null, total, model: null };
  }
  if (be === 'claude' || be === 'codebuddy') {
    return {
      input: typeof t.input === 'number' ? t.input : null,
      output: typeof t.output === 'number' ? t.output : null,
      cached: typeof t.cache_read === 'number' ? t.cache_read : null,
      reasoning: null,
      total: null,
      model: typeof t.model === 'string' ? t.model : null,
    };
  }
  return { input: null, output: null, cached: null, reasoning: null, total: null, model: null };
}

// --- Main ---
function main() {
  const args = parseArgs(process.argv, {
    options: { date: todayCST(), cwd: '', user: '' },
  });

  if (args.options.cwd) {
    try {
      process.chdir(args.options.cwd);
    } catch (e) {
      process.stderr.write(`[collect-ai] failed to chdir to "${args.options.cwd}": ${e.message}\n`);
      process.exit(1);
    }
  }

  const targetDate = args.options.date;
  const cwd = process.cwd();
  const tasksDir = path.join(cwd, '.harness', 'tasks');

  // Issue !190: 今日有 dispatch 活动的 change_name 集合，用于过滤 concern_stats，
  // 避免历史 concerns 污染业务日报。
  const activeChangeNames = new Set();

  const output = emptyOutput(targetDate, cwd);

  if (fs.existsSync(tasksDir)) {
    let subdirs;
    try {
      subdirs = fs.readdirSync(tasksDir, { withFileTypes: true })
        .filter((d) => d.isDirectory())
        .map((d) => d.name);
    } catch (e) {
      subdirs = [];
    }

    // Issue !218/!219：扫描 archive/ 子目录下的已归档 change，避免 dispatch 漏采
    const archiveDir = path.join(tasksDir, 'archive');
    if (fs.existsSync(archiveDir)) {
      try {
        const archived = fs.readdirSync(archiveDir, { withFileTypes: true })
          .filter((d) => d.isDirectory())
          .map((d) => path.join('archive', d.name));
        subdirs = subdirs.concat(archived);
      } catch (e) {
        // ignore
      }
    }

    for (const dirName of subdirs) {
      const stateFile = path.join(tasksDir, dirName, 'pipeline-state.json');
      if (!fs.existsSync(stateFile)) continue;

      let state;
      try {
        const raw = fs.readFileSync(stateFile, 'utf-8');
        state = JSON.parse(raw);
      } catch (e) {
        process.stderr.write(`[collect-ai] WARNING: skipping ${dirName}/pipeline-state.json: ${e.message}\n`);
        continue;
      }

      if (!state.pipeline) continue;

      // --- SPEC stats (global snapshot, not date-filtered) ---
      // Must be before the dispatch-matching continue (C1 from design-review)
      const currentPhase = state.current_phase || '';
      const completedAt = state.completed_at || null;
      output.summary.spec_stats.total_changes += 1;
      if (TERMINAL_PHASES.has(currentPhase) || completedAt) {
        output.summary.spec_stats.closed_loop += 1;
      } else {
        output.summary.spec_stats.open += 1;
      }
      if (currentPhase) {
        output.summary.spec_stats.by_phase[currentPhase] = (output.summary.spec_stats.by_phase[currentPhase] || 0) + 1;
      }

      // Collect matching dispatches from all phases
      const taskDispatches = [];
      for (const [phaseName, phaseData] of Object.entries(state.pipeline)) {
        const history = phaseData && phaseData.dispatch_history;
        if (!Array.isArray(history)) continue;

        for (const dispatch of history) {
          if (!dispatch.started_at) continue;
          if (!isDateMatch(dispatch.started_at, targetDate)) continue;

          // Issue !210: 归一化 token_usage——残缺对象（如 {backend:"claude"} 无真实 token 字段）
          // 归成 null，避免污染报表 JSON 和 by_role/by_model 聚合
          const rawTokens = dispatch.token_usage;
          const normalizedTokens = (rawTokens && typeof rawTokens === 'object' &&
            (rawTokens.input_tokens != null || rawTokens.output_tokens != null ||
             rawTokens.cache_read_input_tokens != null || rawTokens.cache_creation_input_tokens != null ||
             rawTokens.total != null))
            ? rawTokens
            : null;

          taskDispatches.push({
            phase: phaseName,
            started_at: dispatch.started_at,
            completed_at: dispatch.completed_at || null,
            token_usage: normalizedTokens,
            exit_status: dispatch.exit_status || null,
          });
        }
      }

      if (taskDispatches.length === 0) continue;

      // Issue !190: 记录"今日有 dispatch 活动"的 change_name，供 concern_stats 过滤。
      // shared-state 目录用 change_name（不是 task dirName），故必须有 state.change_name 才能关联。
      if (state.change_name) {
        activeChangeNames.add(state.change_name);
      }

      // Build task entry
      const taskEntry = {
        change_name: state.change_name || dirName,
        caller: state.caller || '',
        title: state.title || state.change_name || dirName,
        current_phase: state.current_phase || '',
        phases_completed: (state.quality_metrics && state.quality_metrics.phases_completed) || 0,
        phases_total: (state.quality_metrics && state.quality_metrics.phases_total) || 0,
        scores: state.scores || {},
        quality_metrics: normalizeQualityMetrics(state.quality_metrics),
        dispatches: taskDispatches,
      };
      output.tasks.push(taskEntry);

      // Aggregate into summary
      for (const d of taskDispatches) {
        const role = resolvePhaseRole(d.phase, state);
        const tokens = d.token_usage || {};
        const inputTokens = tokens.input_tokens || 0;
        const outputTokens = tokens.output_tokens || 0;
        const cacheReadTokens = tokens.cache_read_input_tokens || 0;
        const cacheCreationTokens = tokens.cache_creation_input_tokens || 0;

        output.summary.total_input_tokens += inputTokens;
        output.summary.total_output_tokens += outputTokens;
        output.summary.total_dispatches += 1;

        // Pipeline trigger aggregation
        const pipelineTrigger = output.summary.dispatch_by_trigger.pipeline;
        pipelineTrigger.dispatch_count += 1;
        pipelineTrigger.input_tokens += inputTokens;
        pipelineTrigger.output_tokens += outputTokens;
        pipelineTrigger.cache_read_tokens += cacheReadTokens;
        pipelineTrigger.cache_creation_tokens += cacheCreationTokens;

        // by_backend 聚合（新）：从 token_usage.backend 读取，缺失按 claude 兜底
        const backend = tokens.backend || null;
        const normalized = normalizeTokenUsageForReport(tokens, backend);
        aggregateByBackend(output.summary, backend, normalized);

        if (role) {
          if (!pipelineTrigger.by_role[role]) {
            pipelineTrigger.by_role[role] = { dispatch_count: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0 };
          }
          pipelineTrigger.by_role[role].dispatch_count += 1;
          pipelineTrigger.by_role[role].input_tokens += inputTokens;
          pipelineTrigger.by_role[role].output_tokens += outputTokens;
          pipelineTrigger.by_role[role].cache_read_tokens += cacheReadTokens;
          pipelineTrigger.by_role[role].cache_creation_tokens += cacheCreationTokens;
        }

        // Model aggregation (pipeline trigger)
        const model = tokens.model || 'unknown';
        if (!pipelineTrigger.by_model[model]) {
          pipelineTrigger.by_model[model] = { dispatch_count: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0 };
        }
        pipelineTrigger.by_model[model].dispatch_count += 1;
        pipelineTrigger.by_model[model].input_tokens += inputTokens;
        pipelineTrigger.by_model[model].output_tokens += outputTokens;
        pipelineTrigger.by_model[model].cache_read_tokens += cacheReadTokens;
        pipelineTrigger.by_model[model].cache_creation_tokens += cacheCreationTokens;

        // Aggregate wall clock per dispatch
        if (d.started_at && d.completed_at) {
          const startMs = new Date(d.started_at).getTime();
          const endMs = new Date(d.completed_at).getTime();
          if (!isNaN(startMs) && !isNaN(endMs)) {
            output.summary.total_wall_clock_ms += (endMs - startMs);
          }
        }
      }
    }

    // For wall clock: prefer quality_metrics total_wall_clock_ms when available across tasks
    let qualityWallClock = 0;
    let hasQualityWallClock = false;
    for (const task of output.tasks) {
      if (task.quality_metrics && task.quality_metrics.total_wall_clock_ms != null) {
        qualityWallClock += task.quality_metrics.total_wall_clock_ms;
        hasQualityWallClock = true;
      }
    }
    if (hasQualityWallClock) {
      output.summary.total_wall_clock_ms = qualityWallClock;
    }
  }

  // --- Concern stats (global snapshot from shared-state) ---
  // Issue !157+!159: --user 过滤只统计当前用户的 concerns，避免把他人 P0/P1 算到自己头上
  // Issue !190: 只统计今日有 dispatch 活动的 change，避免历史 concerns 污染业务日报
  collectConcernStats(cwd, output, args.options.user || '', activeChangeNames);

  // --- Usage tracking from ~/.claude/usage/usage.jsonl ---
  collectUsageJsonl(targetDate, output);

  // --- Session token stats (all local Claude Code sessions today) ---
  collectSessionTokens(targetDate, output);

  // --- Finalize by_backend buckets（dominant model + null 语义）---
  finalizeByBackend(output.summary);

  process.stdout.write(JSON.stringify(output, null, 2) + '\n');
}

// --- Collect concern stats from .harness/shared-state/*/concerns.json ---
// Issue !157+!159: userFilter 非空时按 concern.author 过滤，只统计当前用户的 concerns。
//   - concern.author 缺失（旧数据）→ 保留 + warn，不丢弃，避免 false-negative
//   - userFilter 为空串 → 不过滤（向后兼容，保持现有行为）
// Issue !190: activeChangeNames 非空时只统计今日活跃 change 的 concerns，避免历史污染。
//   - activeChangeNames 为 null/undefined → 不过滤（向后兼容）
//   - concernDir 不在集合内 → 跳过
function collectConcernStats(cwd, output, userFilter, activeChangeNames) {
  const sharedStateDir = path.join(cwd, '.harness', 'shared-state');
  if (!fs.existsSync(sharedStateDir)) return;

  let concernSubdirs;
  try {
    concernSubdirs = fs.readdirSync(sharedStateDir, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name);
  } catch (e) {
    return;
  }

  const filterByUser = !!(userFilter && userFilter.trim());
  const targetUser = userFilter ? userFilter.trim() : '';
  const filterByChange = !!activeChangeNames;
  let warnedMissingAuthor = false;

  for (const concernDir of concernSubdirs) {
    // Issue !190: 只统计今日活跃 change 的 concerns
    if (filterByChange && !activeChangeNames.has(concernDir)) continue;

    const concernsFile = path.join(sharedStateDir, concernDir, 'concerns.json');
    if (!fs.existsSync(concernsFile)) continue;

    let concernsData;
    try {
      concernsData = JSON.parse(fs.readFileSync(concernsFile, 'utf-8'));
    } catch (e) {
      continue;
    }

    // dual-schema 兼容（issue !151 Bug 3）：
    //   - 新 schema {concerns: [...]}（concerns-schema.json，ID ^C[0-9]+$）
    //   - 老 schema {p0: [...], p1: [...]}（按 severity 分组，ID P0-001，老 shared-state 数据沿用）
    // 老数据每条已含 severity: 'P0'/'P1' + status: 'open'/'resolved'，合并后能被后续解析逻辑识别。
    let concerns = concernsData.concerns;
    if (!Array.isArray(concerns)) {
      const p0 = Array.isArray(concernsData.p0) ? concernsData.p0 : [];
      const p1 = Array.isArray(concernsData.p1) ? concernsData.p1 : [];
      concerns = [...p0, ...p1];
    }
    if (!concerns.length) continue;

    for (const c of concerns) {
      // Issue !157+!159: 按 author 字段过滤
      // Issue !186: 收紧 fail-open——无 author 的 concerns 在 --user 过滤模式下
      // 不计入个人日报（旧数据兼容期已过；保留 warn 提示用户升级写入端）。
      // 原 fail-open 行为会把无 author 的历史/框架 concerns 全算到当前 user 头上。
      if (filterByUser) {
        if (c.author === undefined || c.author === null || c.author === '') {
          if (!warnedMissingAuthor) {
            process.stderr.write(
              `[collect-ai] WARNING: concerns in ${concernDir}/concerns.json missing "author" field. `
              + `Skipping them (--user filter). Please upgrade Reviewer/Debate agents to write \`author\` field. `
              + `(see .claude/skills/rd-auto/references/shared-state.md)\n`
            );
            warnedMissingAuthor = true;
          }
          continue;  // !186: 跳过无 author，不再 fail-open
        } else if (String(c.author).trim() !== targetUser) {
          // 他人的 concern：跳过
          continue;
        }
      }

      const severity = (c.severity || '').toUpperCase();
      const status = (c.status || '').toLowerCase();
      output.summary.concern_stats.total += 1;

      if (severity === 'P0') {
        output.summary.concern_stats.p0_found += 1;
        if (status === 'resolved') {
          output.summary.concern_stats.p0_closed += 1;
        }
      } else if (severity === 'P1') {
        output.summary.concern_stats.p1_found += 1;
        if (status === 'resolved') {
          output.summary.concern_stats.p1_closed += 1;
        }
      }
    }
  }
}

// --- Project slug to short name ---
// Slug: -work-repos-aios-rd-harness → short: rd-harness
// Rule: skip first 3 non-empty segments (path prefix like work/repos/aios or home/user/repos),
// join remaining segments as project name
function slugToShortName(slug) {
  const parts = slug.split('-').filter(Boolean);
  if (parts.length <= 3) return slug.replace(/^-/, '');
  const projectParts = parts.slice(3);
  return projectParts.join('-') || parts[parts.length - 1];
}

// --- Collect session tokens from all local Claude Code sessions ---
function collectSessionTokens(targetDate, output) {
  // HARNESS_PROJECTS_DIR 重定向到目标 backend（如 $HOME/.codebuddy/projects），
  // Claude Code 未设则回退到 ~/.claude/projects 默认布局。
  const projectsDir = process.env.HARNESS_PROJECTS_DIR
    ? process.env.HARNESS_PROJECTS_DIR.replace(/\$HOME/g, os.homedir())
    : detectBackendDir('projects');
  if (!fs.existsSync(projectsDir)) return;

  let projectDirs;
  try {
    projectDirs = fs.readdirSync(projectsDir, { withFileTypes: true })
      .filter((d) => d.isDirectory());
  } catch (e) {
    return;
  }

  // 跨 project 目录去重：同一 session 文件可能出现在多个 project 目录（符号链接/
  // 共享路径等边缘场景），用 session_id（文件名去 .jsonl）追踪已计数的 session。
  const seenSessionIds = new Set();

  for (const projectDir of projectDirs) {
    const projectPath = path.join(projectsDir, projectDir.name);
    const shortName = slugToShortName(projectDir.name);
    let files;
    try {
      files = fs.readdirSync(projectPath, { withFileTypes: true })
        .filter((f) => f.isFile() && f.name.endsWith('.jsonl'));
    } catch (e) {
      continue;
    }

    // Per-project accumulator
    let projectSessionCount = 0;
    let projectInput = 0;
    let projectOutput = 0;
    let projectCacheRead = 0;
    let projectCacheCreation = 0;

    for (const file of files) {
      const filePath = path.join(projectPath, file.name);
      // 跨 project 去重：同一 session 文件可能在多个 project 目录出现
      const sessionId = file.name.replace(/\.jsonl$/, '');
      if (seenSessionIds.has(sessionId)) continue;

      let content;
      try {
        content = fs.readFileSync(filePath, 'utf-8');
      } catch (e) {
        continue;
      }

      let sessionMatched = false;
      const lines = content.split('\n');
      for (const line of lines) {
        if (!line.trim()) continue;
        let entry;
        try {
          entry = JSON.parse(line);
        } catch (e) {
          continue;
        }

        // Date filter: use entry.timestamp (UTC → CST)
        if (entry.timestamp && !isDateMatch(entry.timestamp, targetDate)) continue;
        // If no timestamp, skip (can't determine date)
        if (!entry.timestamp) continue;

        sessionMatched = true;

        const usage = entry.message && entry.message.usage;
        if (!usage) continue;

        const uInput = usage.input_tokens || 0;
        const uOutput = usage.output_tokens || 0;
        const uCacheRead = usage.cache_read_input_tokens || 0;
        const uCacheCreation = usage.cache_creation_input_tokens || 0;

        output.summary.session_input_tokens += uInput;
        output.summary.session_output_tokens += uOutput;
        output.summary.session_cache_creation_input_tokens += uCacheCreation;
        output.summary.session_cache_read_input_tokens += uCacheRead;

        projectInput += uInput;
        projectOutput += uOutput;
        projectCacheRead += uCacheRead;
        projectCacheCreation += uCacheCreation;

        // Model aggregation for session tokens
        const model = (entry.message && entry.message.model) || 'unknown';
        if (!output.summary.session_by_model[model]) {
          output.summary.session_by_model[model] = { count: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0 };
        }
        output.summary.session_by_model[model].count += 1;
        output.summary.session_by_model[model].input_tokens += uInput;
        output.summary.session_by_model[model].output_tokens += uOutput;
        output.summary.session_by_model[model].cache_read_tokens += uCacheRead;
        output.summary.session_by_model[model].cache_creation_tokens += uCacheCreation;
      }

      if (sessionMatched) {
        seenSessionIds.add(sessionId);
        output.summary.session_count += 1;
        projectSessionCount += 1;
      }
    }

    // Store per-project breakdown
    if (projectSessionCount > 0) {
      output.summary.session_by_project[shortName] = {
        slug: projectDir.name,
        count: projectSessionCount,
        input_tokens: projectInput,
        output_tokens: projectOutput,
        cache_read_tokens: projectCacheRead,
        cache_creation_tokens: projectCacheCreation,
      };
    }
  }
}

// --- Resolve caller identity: git username > OS username ---
function resolveCaller() {
  try {
    const { execSync } = require('node:child_process');
    const gitUser = execSync('git config user.name', { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
    if (gitUser) return gitUser;
  } catch (_) { /* not in a git repo or git not available */ }
  try {
    return os.userInfo().username;
  } catch (_) {
    return 'unknown';
  }
}

// --- Read harness version from .harness/.harness-version ---
// 只取首行：与 session-start.sh / submit-harness-issue.sh / upgrade-harness SKILL.md
// 的 `head -1` 契约对齐（bump-version.sh 写入 3 行：version / force / signature）。
function readHarnessVersion(cwd) {
  const versionFile = path.join(cwd, '.harness', '.harness-version');
  try {
    const raw = fs.readFileSync(versionFile, 'utf-8');
    return raw.split('\n', 1)[0].trim() || null;
  } catch (_) {
    return null;
  }
}

// --- Normalize quality_metrics: 类型守卫，null / NaN / Infinity / 非数值 → 0 ---
// schema additionalProperties:false 锁死字段集；这里只做类型守卫，不枚举字段名，
// 避免 "schema 加字段 → normalize 漏字段" 的双向不同步。
function normalizeQualityMetrics(qm) {
  const src = qm || {};
  const out = {};
  for (const [k, v] of Object.entries(src)) {
    out[k] = (typeof v === 'number' && Number.isFinite(v)) ? v : 0;
  }
  return out;
}

// --- Detect AI client (claude-code / codex / codebuddy / qoder / cursor / cline) from env ---
// Order matters: more specific signals first. Returns {name, version} or {name:null, version:null}.
function detectClient(env) {
  const e = env || process.env;

  // Claude Code: CLAUDECODE=1 + CLAUDE_CODE_VERSION (e.g. "2.1.153 (Claude Code)")
  if (e.CLAUDECODE === '1' || e.CLAUDE_CODE_VERSION) {
    const raw = (e.CLAUDE_CODE_VERSION || '').trim();
    // Strip suffixes like " (Claude Code)" — take the first whitespace-separated token
    const version = raw.split(/\s+/)[0] || null;
    return { name: 'claude-code', version: version || null };
  }

  // OpenAI Codex CLI: CODEX env vars
  if (e.CODEX || e.CODEX_VERSION || e.CODEX_HOME) {
    const version = (e.CODEX_VERSION || '').trim() || null;
    return { name: 'codex', version };
  }

  // Qoder CN CLI: project/session signals exposed to hooks and wrapper processes.
  if (e.QODER_PROJECT_DIR || e.QODER_SESSION_ID || e.QODER_VERSION) {
    const version = (e.QODER_VERSION || '').trim() || null;
    return { name: 'qoder', version };
  }

  // Cursor: CURSOR_TRACE_ID or Cursor-defined env vars
  if (e.CURSOR_TRACE_ID || e.CURSOR_VSCODE) {
    return { name: 'cursor', version: (e.CURSOR_VERSION || '').trim() || null };
  }

  // Cline (VS Code extension) — no stable env signal; leave null for now
  return { name: null, version: null };
}

// --- Collect usage data from usage.jsonl ---
// Records written by PostToolUse hook (post-tool-use-agent-usage.sh)
// and by rd-auto mark-dispatch --end.
// HARNESS_USAGE_DIR 重定向到目标 backend（如 $HOME/.codebuddy/usage），
// Claude Code 未设则回退到 ~/.claude/usage 默认布局。
function collectUsageJsonl(targetDate, output) {
  const usageDir = process.env.HARNESS_USAGE_DIR
    ? process.env.HARNESS_USAGE_DIR.replace(/\$HOME/g, os.homedir())
    : detectBackendDir('usage');
  const usageFile = path.join(usageDir, 'usage.jsonl');
  if (!fs.existsSync(usageFile)) return;

  let content;
  try {
    content = fs.readFileSync(usageFile, 'utf-8');
  } catch (e) {
    return;
  }

  const usageDispatches = [];

  for (const line of content.split('\n')) {
    if (!line.trim()) continue;
    let entry;
    try {
      entry = JSON.parse(line);
    } catch (e) {
      continue;
    }

    // Date filter: ts is UTC, convert to CST
    if (!isDateMatch(entry.ts, targetDate)) continue;

    // trigger 过滤：pipeline-trigger 条目跳过，避免与 pipeline-state.json 重复计数。
    // pipeline-state.json 是 pipeline dispatch 的唯一来源；
    // usage.jsonl 只统计 natural-trigger（人工 dispatch）。
    if (entry.trigger === 'pipeline') continue;

    const role = entry.role || 'unknown';
    // 采样缺口检测：短命 subagent 的 tokens 字段为 null，token 数据不可用
    if (entry.tokens === null) {
      output.summary.sampled_gap_count += 1;
    }
    const tokens = entry.tokens || {};
    const inputTokens = tokens.input || 0;
    const outputTokens = tokens.output || 0;
    const cacheReadTokens = tokens.cache_read || 0;
    const cacheCreationTokens = tokens.cache_creation || 0;
    const durationMs = entry.duration_ms || 0;

    // Aggregate into summary totals
    output.summary.total_input_tokens += inputTokens;
    output.summary.total_output_tokens += outputTokens;
    output.summary.total_dispatches += 1;
    output.summary.total_wall_clock_ms += durationMs;

    // Natural trigger aggregation
    const naturalTrigger = output.summary.dispatch_by_trigger.natural;
    naturalTrigger.dispatch_count += 1;
    naturalTrigger.input_tokens += inputTokens;
    naturalTrigger.output_tokens += outputTokens;
    naturalTrigger.cache_read_tokens += cacheReadTokens;
    naturalTrigger.cache_creation_tokens += cacheCreationTokens;

    // by_backend 聚合（新）：usage.jsonl 已写 backend 字段（record-usage）
    // usage.jsonl 的 tokens 字段格式：{input, output, cache_read, cache_creation, model}（claude）
    // 或 {total}（codex）；需映射到 normalized 视图
    const entryBackend = entry.backend || null;
    const entryNormalized = normalizeUsageJsonlTokens(tokens, entryBackend);
    aggregateByBackend(output.summary, entryBackend, entryNormalized);

    if (!naturalTrigger.by_role[role]) {
      naturalTrigger.by_role[role] = { dispatch_count: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0 };
    }
    naturalTrigger.by_role[role].dispatch_count += 1;
    naturalTrigger.by_role[role].input_tokens += inputTokens;
    naturalTrigger.by_role[role].output_tokens += outputTokens;
    naturalTrigger.by_role[role].cache_read_tokens += cacheReadTokens;
    naturalTrigger.by_role[role].cache_creation_tokens += cacheCreationTokens;

    // Model aggregation (natural trigger)
    const model = tokens.model || 'unknown';
    if (!naturalTrigger.by_model[model]) {
      naturalTrigger.by_model[model] = { dispatch_count: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0 };
    }
    naturalTrigger.by_model[model].dispatch_count += 1;
    naturalTrigger.by_model[model].input_tokens += inputTokens;
    naturalTrigger.by_model[model].output_tokens += outputTokens;
    naturalTrigger.by_model[model].cache_read_tokens += cacheReadTokens;
    naturalTrigger.by_model[model].cache_creation_tokens += cacheCreationTokens;

    usageDispatches.push(entry);
  }

  // Create a virtual task entry for render-report.js active tasks list
  if (usageDispatches.length > 0) {
    const triggerBreakdown = {};
    for (const d of usageDispatches) {
      const t = d.trigger || 'unknown';
      triggerBreakdown[t] = (triggerBreakdown[t] || 0) + 1;
    }
    const triggerStr = Object.entries(triggerBreakdown).map(([k, v]) => `${k}:${v}`).join(', ');

    output.tasks.push({
      change_name: 'agent-dispatch',
      caller: resolveCaller(),
      title: `人工调度 (${triggerStr})`,
      current_phase: 'usage-tracking',
      phases_completed: 1,
      phases_total: 1,
      scores: {},
      quality_metrics: {},
      dispatches: usageDispatches.map((d) => ({
        phase: `usage-${d.trigger || 'natural'}`,
        started_at: d.started_at || d.ts,
        completed_at: d.completed_at || null,
        token_usage: d.tokens ? {
          input_tokens: d.tokens.input || 0,
          output_tokens: d.tokens.output || 0,
          cache_read_input_tokens: d.tokens.cache_read || 0,
          cache_creation_input_tokens: d.tokens.cache_creation || 0,
          model: d.tokens.model || null,
        } : null,
        exit_status: null,
      })),
      _usage_source: true,
    });
  }
}

main();
