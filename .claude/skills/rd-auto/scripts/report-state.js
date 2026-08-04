#!/usr/bin/env node
// report-state.js — rd_harness-side collector for Oracle task status sync.
//
// Reads a task's current phase (pipeline-state.json | `rd status`) and reports
// it to taskboard's REST hub, which maps it to an Oracle STATUSID and writes
// back to Oracle. Fire-and-forget: spawned detached by the rd-auto advance loop
// (mirrors grafana/push-metrics.js). Silent no-op when taskboard creds are
// missing or AI_STATE_REPORT_DISABLED=1 — never blocks the dev flow, never
// throws to its caller.
//
// SPEC: docs/oracle-sync-落地设计方案.md §3 / §7.4 / §8.1.
// Usage:
//   node report-state.js <change> [--dry-run]

import { execSync, execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
import http from 'node:http';
import https from 'node:https';

import {
  resolveTaskboardCreds,
  readMcpTaskboardConfig,
  readTaskboardConfig,
  inferPhaseFromPipelineState,
  inferPhaseFromArtifacts,
  buildReportPayload,
  buildRdStatusArgs,
} from './lib/report-state-logic.js';
import { statePath } from './lib/state-store.js';
import { PROJECT_ROOT } from './lib/constants.js';

const LOCAL_STATE_DIR = join(homedir(), '.config', 'harness');
const LOCAL_STATE_FILE = join(LOCAL_STATE_DIR, 'report-state.last');
const HTTP_TIMEOUT_MS = 3000;
const RD_STATUS_TIMEOUT_MS = 3000;

function debug(msg) {
  if (process.env.REPORT_STATE_DEBUG) process.stderr.write(`[report-state] ${msg}\n`);
}

// ─── operatorName / RESNAME source (git config user.name) ───────────────────
function getGitUsername() {
  try {
    return execSync('git config user.name', { encoding: 'utf8' }).trim() || 'unknown';
  } catch {
    return 'unknown';
  }
}

// ─── applyRatio from tasks.md (manual-artifact refinement, SPEC §3.3) ───────
function computeApplyRatio(changeName) {
  try {
    const tasksMd = join(PROJECT_ROOT, '.harness', 'spec', 'changes', changeName, 'tasks.md');
    if (!existsSync(tasksMd)) return undefined;
    const md = readFileSync(tasksMd, 'utf8');
    const checked = (md.match(/^\s*[-*]\s+\[x\]/gim) || []).length;
    const unchecked = (md.match(/^\s*[-*]\s+\[ \]/gim) || []).length;
    const total = checked + unchecked;
    if (total === 0) return undefined;
    return checked / total;
  } catch {
    return undefined;
  }
}

// ─── minimal HTTP JSON helper (node:http, like push-metrics.js) ─────────────
function httpJson(method, fullUrl, { headers = {}, body, timeoutMs = HTTP_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    let url;
    try {
      url = new URL(fullUrl);
    } catch (e) {
      resolve({ status: 0, body: String(e.message) });
      return;
    }
    const opts = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname + url.search,
      method,
      headers: { ...headers, ...(body != null ? { 'Content-Type': 'application/json' } : {}) },
      timeout: timeoutMs,
    };
    // C004: pick the client by protocol so an https TASKBOARD_URL doesn't
    // silently TLS-fail forever (node:http cannot speak TLS).
    const client = url.protocol === 'https:' ? https : http;
    const req = client.request(opts, (res) => {
      let data = '';
      res.on('data', (c) => {
        data += c;
      });
      res.on('end', () => resolve({ status: res.statusCode || 0, body: data }));
    });
    req.on('error', (e) => resolve({ status: 0, body: e.message }));
    req.on('timeout', () => {
      req.destroy();
      resolve({ status: 0, body: 'timeout' });
    });
    if (body != null) req.write(body);
    req.end();
  });
}

// ─── local counter state (SPEC §8.1: ~/.config/harness/report-state.last) ───
function readLocalState() {
  try {
    return JSON.parse(readFileSync(LOCAL_STATE_FILE, 'utf8'));
  } catch {
    return {};
  }
}
function writeLocalState(change, counts) {
  try {
    if (!existsSync(LOCAL_STATE_DIR)) mkdirSync(LOCAL_STATE_DIR, { recursive: true });
    const prev = readLocalState();
    writeFileSync(
      LOCAL_STATE_FILE,
      JSON.stringify(
        { ...prev, lastChange: change, lastCounts: counts, updatedAt: new Date().toISOString() },
        null,
        2,
      ),
      'utf8',
    );
  } catch {
    /* best-effort; counter state is non-critical */
  }
}

// ─── REST calls ─────────────────────────────────────────────────────────────
async function hasLink(base, token, change) {
  const res = await httpJson('GET', `${base}/api/harness/has-link?change=${encodeURIComponent(change)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status !== 200) return { status: res.status, hasLink: false };
  try {
    return { status: res.status, hasLink: !!JSON.parse(res.body).hasLink };
  } catch {
    return { status: res.status, hasLink: false };
  }
}

async function postPhaseReport(base, token, payload) {
  return httpJson('POST', `${base}/api/harness/phase-report`, {
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

// ─── core: runReportState. Never throws. Returns counts. ────────────────────
/**
 * @param {string} changeName
 * @param {{dryRun?: boolean, operatorName?: string, summary?: string}} [opts]
 * @returns {Promise<{reported:number, no_link:number, rd_unavailable:number, error:number}>}
 */
export async function runReportState(changeName, opts = {}) {
  const dryRun = !!opts.dryRun;
  const counts = { reported: 0, no_link: 0, rd_unavailable: 0, error: 0 };
  const log = (s) => process.stderr.write(s + '\n');

  // Source discrimination (SPEC §3.2).
  const psPath = statePath(changeName);
  let inferred;
  try {
    if (psPath && existsSync(psPath)) {
      const ps = JSON.parse(readFileSync(psPath, 'utf8'));
      inferred = inferPhaseFromPipelineState(ps);
    } else {
      let rdStatus = null;
      try {
        // C001/C003: array form (execFileSync) — argv built by buildRdStatusArgs,
        // never passes changeName through a shell, so metacharacters cannot inject.
        const out = execFileSync('rd', buildRdStatusArgs(changeName), {
          encoding: 'utf8',
          timeout: RD_STATUS_TIMEOUT_MS,
        });
        rdStatus = JSON.parse(out);
      } catch {
        rdStatus = null;
      }
      if (rdStatus) {
        inferred = inferPhaseFromArtifacts(rdStatus, { applyRatio: computeApplyRatio(changeName) });
      } else {
        inferred = { source: 'manual-rd-unavailable' };
        counts.rd_unavailable++;
      }
    }
  } catch (e) {
    counts.error++;
    debug(`infer failed: ${e.message}`);
    inferred = { source: 'manual-rd-unavailable' };
  }

  const operatorName = opts.operatorName || getGitUsername();
  const payload = buildReportPayload({ change: changeName, inferred, operatorName, summary: opts.summary });

  // dry-run: pure local inspection — no creds, no network, bypasses kill-switch
  // (explicit human request, read-only). Lets a creds-less env still verify phase
  // inference + payload assembly. Does NOT write local state (read-only).
  if (dryRun) {
    log(`[report-state] (dry-run) change=${changeName} source=${inferred.source}`);
    log(`[report-state] (dry-run) payload=${JSON.stringify(payload)}`);
    return counts;
  }

  // Guard: kill-switch (SPEC §8.3).
  if (process.env.AI_STATE_REPORT_DISABLED === '1') return counts;

  // P2.2: operatorName resolves to 'unknown' when git user.name is unset — never
  // report that to Oracle (it would dirty DEVELOPPERSON/CHECKPERSON). Warn + no-op.
  if (!operatorName || operatorName === 'unknown') {
    log(`[report-state] WARN git user.name missing — skipping ${changeName} (refuse to write operatorName=unknown to Oracle)`);
    return counts;
  }

  // Guard: creds missing → silent no-op (SPEC §8.3 铁律).
  const creds = resolveTaskboardCreds({
    env: process.env,
    mcpConfig: readMcpTaskboardConfig(PROJECT_ROOT),
    tbConfig: readTaskboardConfig(PROJECT_ROOT),
  });
  if (!creds) return counts;

  // has-link pre-flight (SPEC §7.4 / §8.1 step 1).
  const link = await hasLink(creds.base, creds.token, changeName);
  if (link.status === 401) {
    // P2.3: PAT invalid — distinguish from "no link" so the dev can fix creds.
    log(`[report-state] WARN has-link HTTP 401 (PAT invalid/unauthorized) for ${changeName}`);
    counts.error++;
    writeLocalState(changeName, counts);
    return counts;
  }
  if (link.status === 0 || link.status >= 500) {
    // network error / taskboard 5xx — transient, retry next trigger/cron.
    debug(`has-link HTTP ${link.status || 'network-error'} for ${changeName}, will retry later`);
    counts.error++;
    writeLocalState(changeName, counts);
    return counts;
  }
  if (!link.hasLink) {
    counts.no_link++;
    log(`⚠ ${changeName}: no Oracle link, skipped`);
    writeLocalState(changeName, counts);
    return counts;
  }

  // POST phase report (SPEC §8.1 step 4).
  try {
    const res = await postPhaseReport(creds.base, creds.token, payload);
    if (res.status === 200) {
      counts.reported++;
    } else if (res.status === 403) {
      // SPEC §8.1 A5: PAT holder not a project member — warn so the dev notices.
      log(`[report-state] WARN 403 PAT holder not project member, cannot report ${changeName}`);
      counts.error++;
    } else {
      debug(`phase-report HTTP ${res.status}: ${String(res.body).slice(0, 200)}`);
      counts.error++;
    }
  } catch (e) {
    debug(`phase-report failed: ${e.message}`);
    counts.error++;
  }

  log(
    `[report-state] change=${changeName} reported=${counts.reported} no_link=${counts.no_link} rd_unavailable=${counts.rd_unavailable} error=${counts.error}`,
  );
  writeLocalState(changeName, counts);
  return counts;
}

// ─── CLI main (human / manual path) ─────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2);
  const changeName = args.find((a) => !a.startsWith('-'));
  const dryRun = args.includes('--dry-run');
  if (!changeName) {
    process.stderr.write('Usage: node report-state.js <change> [--dry-run]\n');
    process.exit(1);
  }
  await runReportState(changeName, { dryRun });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    // fire-and-forget: never fail the parent process.
    process.stderr.write(`[report-state] unexpected: ${e.message}\n`);
    process.exit(0);
  });
}
