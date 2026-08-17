# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Repo Layout

Two Python packages + the ECC harness:

| Directory | What |
|---|---|
| `excelOps/` | Pure-Python Excel library: read (openpyxl) → analyze (embedded DuckDB) → write (xlsxwriter). Policy-unaware backends; ops layer implements business operations (filter, lookup, narrate, transform, etc.) |
| `serverOps/` | FastMCP server for operating SSH/Docker/K8s/DB via named connection profiles. Security layer (read-only gate, SSH command denylist, audit log, credential redaction). |
| `.claude/` | ECC (Everything Claude Code) harness: rules, skills, hooks, backends, CI templates, tool scripts. **Do not edit unless maintaining the harness itself.** |
| `.harness/` | rd-auto spec/task state. Managed by the orchestrator; do not hand-edit. |

---

## Development Commands

Both packages are pip-installable with a `src/` layout. Each has its own `pyproject.toml`.

### excelOps

```bash
cd excelOps
pip install -e .                     # core: openpyxl + xlsxwriter
pip install -e '.[duckdb]'          # + analyze engine
pip install -e '.[dev]'             # pytest, ruff

pytest -q                           # tests
ruff check .                        # lint
```

### serverOps

```bash
cd serverOps
pip install -e .                    # core (fastmcp + pydantic + yaml)
pip install -e '.[ssh]'             # asyncssh
pip install -e '.[container]'       # aiodocker
pip install -e '.[k8s]'             # kubernetes
pip install -e '.[db]'              # sqlalchemy + asyncpg/aiomysql/aiosqlite + redis + clickhouse-connect
pip install -e '.[elasticsearch]'   # elasticsearch
pip install -e '.[all]'             # everything
pip install -e '.[dev]'             # pytest, pytest-asyncio, ruff

pytest -q                           # tests (77+)
ruff check .                        # lint
python -m serverops                 # stdio MCP (default)
python -m serverops --transport http --port 8000  # HTTP MCP
```

**Python version**: core works on 3.10–3.14; backends with C extensions (asyncpg, aiodocker, kubernetes) need 3.12 or 3.13 for pre-built wheels.

**Windows note**: venv activate via `.venv\Scripts\activate`; tests run via `.venv\Scripts\python -m pytest`.

### Quick deploy (serverOps)

```bash
python setup_mcp.py                # creates venv + installs + generates .mcp.json
python setup_mcp.py --extras db    # only install what you need
```

---

## serverOps Architecture

### Data flow

```
config.yaml (named connections)
  → pydantic validation (ServerOpsConfig)
  → ConnectorRegistry (lazy connect + per-name cache)
  → tools/ (meta, ssh, db, container) — safety gate + audit + redaction
  → MCP layer (FastMCP) → Claude Code/Desktop
```

Key files:

| File | Role |
|---|---|
| `src/serverops/config.py` | Load YAML, interpolate `${ENV}`, validate |
| `src/serverops/models.py` | Pydantic models for settings + connection profiles |
| `src/serverops/secrets.py` | Load `.env` before config interpolation |
| `src/serverops/registry.py` | Connection-name → cached `AsyncConnector` |
| `src/serverops/safety.py` | Read-only gate + SSH command denylist/allowlist |
| `src/serverops/audit.py` | JSONL audit log for write ops |
| `src/serverops/redaction.py` | Scrub secrets from errors/URLs before returning to model |
| `src/serverops/http_auth.py` | Bearer Token verifier for HTTP transport |
| `src/serverops/server.py` | FastMCP app + CLI (stdio/http) |
| `src/serverops/connectors/base.py` | `AsyncConnector` ABC |
| `src/serverops/connectors/{ssh,docker,kubernetes,database,elasticsearch}.py` | Per-backend connector implementations |
| `src/serverops/tools/{meta,ssh,db,container,es,ssh}.py` | MCP tool implementations |

### Connector design

- All connectors extend `AsyncConnector` (abstract `connect` / `health` / `close`).
- Heavy imports are **lazy** — the package imports cleanly even without any extra installed; errors surface on first use with install hints.
- Connectors are **policy-unaware** — safety/audit/redaction happen at the `tools/` layer.

### Security model

- **Named connections only** — tools accept a connection name, never raw host/credential.
- **Read-only gate** — global `settings.read_only` or per-connection `read_only` disables `ssh_exec`, `ssh_script`, `docker_exec`, `k8s_exec`, `db_execute`.
- **`db_query` physical read-only** — SQL backends execute then ROLLBACK; even an accidental INSERT has no effect.
- **ClickHouse query-only** — no transaction support, so `db_query` uses a **leading-keyword allowlist** (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN/EXISTS); `db_execute` is **always disabled** for ClickHouse regardless of `read_only`.
- **SSH command denylist** — regex-matched dangerous commands (`rm -rf /`, `mkfs`, `dd of=/dev/`, `shutdown`, fork bomb, etc.). Optional `ssh_command_allowlist` for "only these commands".
- **Credentials via `.env`** — never in config or tool args. DB URLs use `${VAR}` interpolation; SSH passwords use `password_env`.
- **Redaction** — passwords in URLs and secrets in error messages are scrubbed to `***` before returning to the model.

### ClickHouse URL schemes

| Scheme | Transport | Default port |
|---|---|---|
| `clickhouse://`, `clickhouse+http://` | HTTP | 8123 |
| `clickhouse+https://`, `clickhouses://`, `clickhouse+secure://` | HTTPS | 8443 |

Explicit port in URL always wins. SQL params use `:name` placeholders (translated to clickhouse-connect's `%(name)s`); literal `%` must be `%%` when params are present.

### SSH + ClickHouse via tunnel (previous session topic)

When config has both a `220` SSH connection and a ClickHouse connection on the same remote host, the connector code does **not** automatically tunnel. The user must either:
1. Set up an SSH tunnel externally (`ssh -L local_port:localhost:8123 user@host`) and point the ClickHouse URL at `localhost:local_port`, or
2. Add a dedicated connection that SSH-connects then runs a local proxy.

This is intentional: connectors are policy-unaware and each connection profile maps to exactly one backend kind.

---

## excelOps Architecture

```
openpyxl (read) → SheetData → DuckDB (analyze) → xlsxwriter (write)
```

| Directory | Role |
|---|---|
| `src/excelops/backends/reader.py` | Open XLSX, normalize headers (None/dupes → placeholders), pad ragged rows → `SheetData` |
| `src/excelops/backends/analyzer.py` | Register `SheetData` as DuckDB tables, run SQL |
| `src/excelops/backends/writer.py` | Copy-on-Write: same-dir temp file + `os.replace` (atomic, no corruption on failure) |
| `src/excelops/backends/models.py` | Shared `SheetData` type |
| `src/excelops/backends/merger.py` | Merge multiple workbooks |
| `src/excelops/ops/*.py` | Business operations: filter, lookup, derive, transform, narrate, union, project, shelf_life, product_lookup, combine |
| `src/excelops/errors.py` | Domain errors |
| `src/excelops/logging.py` | structlog setup |

Key design decisions:
- **Type fidelity**: dates stay dates across read → analyze → write; no implicit stringification.
- **Copy-on-Write**: an interrupted write never corrupts the existing file.
- **Policy-unaware**: no safety/audit coupling in backends (intentional for future MCP tool wrapping).

---

## ECC Harness

The `.claude/` directory contains the Everything Claude Code framework. Key areas:

- **`.claude/rules/`** — Project-specific AI behavior rules (commit spec, auto-dispatch, behavior constraints, output conventions). Loaded into context automatically.
- **`.claude/skills/`** — rd-auto (orchestrator), daily-report, devops, evidence-check, issue-board, memory-cli, pua-debugging, simplify, upgrade-harness, template-fill, skillhub.
- **`.claude/hooks/`** — Git hooks (commit-msg, pre-commit, pre-push) + shared shell scripts (git-guard, memory-route-guard, tasks-guard, session-start).
- **`.claude/backends/`** — Multi-backend dispatch (claude, codebuddy, codex, qoder).
- **`.claude/tools/scripts/`** — CI scripts, harness management, tests.
- **`.claude/agents/`** — Custom agents (Architect, Developer, Reviewer, Tester, Debate) with extension protocols.
- **`.harness/spec/`** — rd-auto change specs (excelops-core-engine, excelops-ops-suite).

**Do not modify `.claude/` or `.harness/` during normal feature development** — these are framework infrastructure.

---

## Key Rules (loaded automatically)

| Rule | Summary |
|---|---|
| `ai-git-commit-spec.md` | Commit format: `[task-id] STAGE module[AI-user.Developer]` + conventional body. Must `git fetch` before commit and push. No force push to shared branches. |
| `ai-behavior-constraints.md` | Demand fidelity: produce assumptions + clarification before implementing complex/ambiguous requests. |
| `auto-dispatch.md` | Development requests auto-route to `/rd-auto`. |
| `concise-output.md` | BLUF: conclusion first, no filler. |
| `task-completion-gate.md` | Handle taskboard `warnings` when tasks move to terminal state. |
| `usage-tracking.md` | Debate/Reviewer dispatch must include `change-name` and call `write-shared-state`. |

---

## Testing

```bash
# excelOps
cd excelOps && pytest -q

# serverOps (77+ tests, async via pytest-asyncio auto mode)
cd serverOps && pytest -q
cd serverOps && pytest -q tests/test_clickhouse.py   # single test file

# Run a specific test
pytest tests/test_clickhouse.py::test_something -v
```

Tests use injected mocks for external services (Docker, K8s, SSH). SQLite tests use a real in-memory database.