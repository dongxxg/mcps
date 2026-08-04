// lib/report-state-logic.js — pure helpers for the taskboard state collector.
//
// No fs / network / side-effects → unit-testable with `node --test`. The
// detached collector (scripts/report-state.js) imports these and adds the
// fs/network shell around them.
//
// Credential resolution mirrors daily-report/scripts/whoami.js (reads
// .mcp.json / .taskboard-config / env) so already-configured users need zero
// extra setup. SPEC: docs/oracle-sync-落地设计方案.md §3 / §7.4 / §8.1.

import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

/** MCP server URL used when nothing else is configured. */
export const DEFAULT_TASKBOARD_MCP_URL = 'http://192.168.5.115/api/mcp';

export const REPORT_SOURCE = Object.freeze({
  RD_AUTO: 'rd-auto',
  MANUAL_ARTIFACT: 'manual-artifact',
  MANUAL_RD_UNAVAILABLE: 'manual-rd-unavailable',
  MANUAL_REPORT: 'manual-report',
});

// ─── rd-status argv (C001/C003 injection guard) ─────────────────────────────
// The `rd status` invocation MUST stay in array form (execFileSync) so the
// change name never reaches a shell. Centralizing the argv here lets a unit
// test assert array form — preventing the C001 command-injection from silently
// regressing if someone rewrites it back to an execSync string.
export function buildRdStatusArgs(changeName) {
  return ['status', '--change', String(changeName), '--json'];
}

// ─── REST base derivation ───────────────────────────────────────────────────
// The MCP URL ends in /api/mcp; the REST endpoints (phase-report, has-link)
// live under the same host root. Strip the MCP suffix to get the REST base.

export function deriveRestBase(mcpUrl) {
  if (!mcpUrl || typeof mcpUrl !== 'string') return '';
  let u = mcpUrl.trim().replace(/\/+$/, '');
  u = u.replace(/\/api\/mcp$/i, '');
  return u;
}

// ─── Config-file readers (thin fs wrappers) ─────────────────────────────────

/**
 * Read the taskboard entry from .mcp.json. Supports both the `mcpServers`
 * wrapper schema and the direct `taskboard` schema. Returns { url, headers }
 * or null.
 */
export function readMcpTaskboardConfig(projectRoot) {
  const mcpFile = join(projectRoot, '.mcp.json');
  if (!existsSync(mcpFile)) return null;
  try {
    const mcp = JSON.parse(readFileSync(mcpFile, 'utf-8'));
    return (mcp.taskboard || (mcp.mcpServers && mcp.mcpServers.taskboard)) || null;
  } catch {
    return null;
  }
}

/** Read .taskboard-config (key=value lines) into a plain object. */
export function readTaskboardConfig(projectRoot) {
  const cfgFile = join(projectRoot, '.taskboard-config');
  if (!existsSync(cfgFile)) return {};
  const out = {};
  for (const line of readFileSync(cfgFile, 'utf-8').split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const eq = t.indexOf('=');
    if (eq === -1) continue;
    const k = t.slice(0, eq).trim();
    const v = t.slice(eq + 1).trim();
    if (k && v) out[k] = v;
  }
  return out;
}

// ─── Credential resolution (PURE — testable with injected configs) ──────────

/**
 * Resolve taskboard REST credentials from env + parsed config sources.
 * Returns { token, base } or null when no token is available (caller no-ops).
 *
 * Token priority: TASKBOARD_PAT > TASKBOARD_TOKEN > .mcp.json Authorization >
 * .taskboard-config taskboard_token.
 * URL priority:   TASKBOARD_URL > TASKBOARD_MCP_URL > .mcp.json url > default.
 */
export function resolveTaskboardCreds({ env = {}, mcpConfig = null, tbConfig = {} } = {}) {
  const envToken = env.TASKBOARD_PAT || env.TASKBOARD_TOKEN || '';
  const rawAuth =
    (mcpConfig && (mcpConfig.headers?.Authorization || mcpConfig.headers?.authorization)) || '';
  const mcpToken = rawAuth
    ? rawAuth.startsWith('Bearer ')
      ? rawAuth.slice(7)
      : rawAuth
    : '';
  const cfgToken = (tbConfig && tbConfig.taskboard_token) || '';

  const token = envToken || mcpToken || cfgToken;
  if (!token) return null;

  const envUrl = env.TASKBOARD_URL || env.TASKBOARD_MCP_URL || '';
  const url = envUrl || (mcpConfig && mcpConfig.url) || DEFAULT_TASKBOARD_MCP_URL;
  const base = deriveRestBase(url);
  if (!base) return null;

  return { token, base };
}

// ─── Phase normalization ────────────────────────────────────────────────────
// Pipeline phases not present in the taskboard PHASE_TO_STATUSID table are
// collapsed onto their nearest mapped phase so the write-back still fires.

export function normalizePhase(phase) {
  switch (phase) {
    case 'smoke':
      return 'implement'; // post-implement smoke test = still developing (SID 30)
    case 'merge-prep':
    case 'doc-sync':
    case 'completed':
      return 'archive'; // terminal state → archive (SID 62)
    case 'debate':
      return 'code-review'; // debate is part of the review cycle
    default:
      return phase;
  }
}

// ─── Source A: infer from pipeline-state.json (rd-auto mode) ────────────────

// exit_status values written by advance.js (authoritative). Case-normalized
// before lookup for defensive robustness.
const BLOCKED_EXITS = new Set(['BLOCKED', 'NEEDS_PM', 'NEEDS_CONTEXT', 'BLOCKED_REVIEW']);
const DONE_EXITS = new Set(['DONE', 'DONE_WITH_CONCERNS']);
// status values written by advance.js (see advance.js:271-275).
const BLOCKED_STATUSES = new Set(['blocked', 'needs_pm']);
const DONE_STATUSES = new Set(['done', 'done_with_concerns']);

/**
 * @param {object} ps parsed pipeline-state.json
 * @returns {{source, phase, phaseStatus, flowType, score?}}
 */
export function inferPhaseFromPipelineState(ps) {
  const rawPhase = ps?.current_phase;
  const phase = normalizePhase(rawPhase);
  // Look up the pipeline entry under the raw (un-normalized) phase name.
  const entry = ps?.pipeline?.[rawPhase] || ps?.pipeline?.[phase];
  const rawExit = entry?.exit_status;
  const exitStatus = typeof rawExit === 'string' ? rawExit.toUpperCase() : rawExit;
  const status = entry?.status;
  // Terminal state: change has been completed → treat as archive|done so the
  // Oracle STATUSID mapping (*|archive|done → 62) fires. Without this, the
  // archive entry's in_progress status yields archive|in_progress (no mapping)
  // and the sync silently skips — the exact gap that surfaced in E2E (2026-07-23).
  if (rawPhase === 'completed') {
    return { source: REPORT_SOURCE.RD_AUTO, phase, phaseStatus: 'done', flowType: ps?.flow_type || 'development', score: ps?.scores?.reviewer ?? ps?.scores?.architect };
  }
  // DONE_WITH_CONCERNS means the phase advanced (non-P0 concerns auto-promote,
  // SPEC §循环终止条件) — treat as done so code-review 50/60 progression fires.
  // C002: previously only status==='done' counted, dropping the common
  // DONE_WITH_CONCERNS case → code-review stalled Oracle at 30/35.
  const phaseStatus =
    BLOCKED_EXITS.has(exitStatus) || BLOCKED_STATUSES.has(status)
      ? 'blocked'
      : DONE_EXITS.has(exitStatus) || DONE_STATUSES.has(status)
        ? 'done'
        : 'in_progress';
  const flowType = ps?.flow_type || 'development';
  // reviewer score feeds the code-review 50/60 disambiguation on the taskboard
  // side (SPEC §5.1); fall back to architect if reviewer is absent.
  const reviewer = ps?.scores?.reviewer;
  const architect = ps?.scores?.architect;
  const score = typeof reviewer === 'number' ? reviewer : typeof architect === 'number' ? architect : undefined;
  return { source: REPORT_SOURCE.RD_AUTO, phase, phaseStatus, flowType, score };
}

// ─── Source B: infer from `rd status --json` (manual-artifact mode) ─────────

/**
 * @param {object} rdStatus parsed `rd status --change <c> --json`
 * @param {{applyRatio?: number}} [opts] applyRatio = checked/total of tasks.md (0..1)
 * @returns {{source, phase, phaseStatus, flowType, artifactProgress}}
 */
export function inferPhaseFromArtifacts(rdStatus, opts = {}) {
  const applyRatio = opts.applyRatio;
  const arts = Array.isArray(rdStatus?.artifacts) ? rdStatus.artifacts : [];
  const statusOf = (id) => {
    const a = arts.find((x) => x.id === id);
    return a ? a.status : undefined;
  };
  const proposal = statusOf('proposal');
  const design = statusOf('design');
  const specs = statusOf('specs');
  const tasks = statusOf('tasks');
  const allDesignDone = [proposal, design, specs, tasks].every((s) => s === 'done');
  const artifactProgress = { proposal, design, specs, tasks, applyRatio };
  const flowType = 'development';

  if (rdStatus?.isComplete) {
    return { source: REPORT_SOURCE.MANUAL_ARTIFACT, phase: 'archive', phaseStatus: 'done', flowType, artifactProgress };
  }
  if (proposal !== 'done') {
    return { source: REPORT_SOURCE.MANUAL_ARTIFACT, phase: 'explore', phaseStatus: 'in_progress', flowType, artifactProgress };
  }
  if (!allDesignDone) {
    return { source: REPORT_SOURCE.MANUAL_ARTIFACT, phase: 'propose', phaseStatus: 'in_progress', flowType, artifactProgress };
  }
  // All design artifacts done → implementation phase; refine by applyRatio when known.
  if (typeof applyRatio === 'number') {
    return applyRatio >= 1
      ? { source: REPORT_SOURCE.MANUAL_ARTIFACT, phase: 'implement', phaseStatus: 'done', flowType, artifactProgress }
      : { source: REPORT_SOURCE.MANUAL_ARTIFACT, phase: 'implement', phaseStatus: 'in_progress', flowType, artifactProgress };
  }
  // No applyRatio → can't tell implement progress; report propose done (design complete, awaiting impl).
  return { source: REPORT_SOURCE.MANUAL_ARTIFACT, phase: 'propose', phaseStatus: 'done', flowType, artifactProgress };
}

// ─── Payload assembly ───────────────────────────────────────────────────────
// Builds a body matching taskboard's reportHarnessPhaseInputSchema.
// manual-rd-unavailable omits phase/phaseStatus (SPEC §8.1 step 3: phase=null).

export function buildReportPayload({ change, inferred, operatorName, summary } = {}) {
  const source = inferred?.source || REPORT_SOURCE.MANUAL_REPORT;
  const unavailable = source === REPORT_SOURCE.MANUAL_RD_UNAVAILABLE;
  const payload = {
    harnessChange: change,
    operatorName,
    source,
  };
  if (!unavailable) {
    if (inferred?.phase) payload.phase = inferred.phase;
    if (inferred?.phaseStatus) payload.phaseStatus = inferred.phaseStatus;
    if (inferred?.flowType) payload.flowType = inferred.flowType;
    if (typeof inferred?.score === 'number') payload.score = inferred.score;
    if (inferred?.artifactProgress) payload.artifactProgress = inferred.artifactProgress;
  }
  if (summary) payload.summary = summary;
  return payload;
}
