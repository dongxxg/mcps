#!/usr/bin/env node
// ci-run-agent.js — CI 后端路由包装器
// 检测当前后端，将 prompt 路由到 claude/codebuddy、codex 或 qoderclicn
// 用法: node ci-run-agent.js --model <m> --max-turns <n> --allowed-tools <t> --output-format <f>
//       prompt 从 stdin 读入

import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const BACKENDS_DIR = join(__dirname, '..', '..', '..', 'backends');

const { detectBackend } = await import(
  join(BACKENDS_DIR, 'backend-factory.js')
);

function parseArgs() {
  const raw = process.argv.slice(2);
  const opts = {};
  for (let i = 0; i < raw.length; i++) {
    const k = raw[i];
    if (k === '--model' || k === '--max-turns' || k === '--allowed-tools' || k === '--output-format') {
      opts[k.slice(2)] = raw[++i];
    }
  }
  return opts;
}

const opts = parseArgs();
const prompt = readFileSync(0, 'utf8');
const backend = detectBackend();

if (backend.type === 'codex') {
  const child = spawn('codex', [
    'exec', '--json', '--full-auto',
    '--sandbox', 'workspace-write',
    prompt,
  ], { stdio: 'inherit' });
  child.on('close', (code) => process.exit(code || 0));
} else if (backend.type === 'codebuddy') {
  // codebuddy CLI 与 claude code 同构，仅二进制名不同
  const cliArgs = ['-p'];
  if (opts.model) cliArgs.push('--model', opts.model);
  if (opts['max-turns']) cliArgs.push('--max-turns', opts['max-turns']);
  if (opts['allowed-tools']) cliArgs.push('--allowedTools', opts['allowed-tools']);
  if (opts['output-format']) cliArgs.push('--output-format', opts['output-format']);
  cliArgs.push(prompt);

  const child = spawn('codebuddy', cliArgs, { stdio: 'inherit' });
  child.on('close', (code) => process.exit(code || 0));
} else if (backend.type === 'qoder') {
  const cliArgs = ['--print', '--permission-mode', 'auto'];
  if (opts.model) cliArgs.push('--model', opts.model);
  if (opts['max-turns']) cliArgs.push('--max-turns', opts['max-turns']);
  if (opts['allowed-tools']) cliArgs.push('--allowed-tools', opts['allowed-tools']);
  if (opts['output-format']) cliArgs.push('--output-format', opts['output-format']);
  cliArgs.push(prompt);

  const child = spawn('qoderclicn', cliArgs, { stdio: 'inherit' });
  child.on('close', (code) => process.exit(code || 0));
} else {
  const cliArgs = ['-p'];
  if (opts.model) cliArgs.push('--model', opts.model);
  if (opts['max-turns']) cliArgs.push('--max-turns', opts['max-turns']);
  if (opts['allowed-tools']) cliArgs.push('--allowedTools', opts['allowed-tools']);
  if (opts['output-format']) cliArgs.push('--output-format', opts['output-format']);
  cliArgs.push(prompt);

  const child = spawn('claude', cliArgs, { stdio: 'inherit' });
  child.on('close', (code) => process.exit(code || 0));
}
