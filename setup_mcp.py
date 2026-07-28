#!/usr/bin/env python3
"""serverOps — one-shot MCP deployment bootstrap.

Run with any Python 3.10+ interpreter:

    python setup_mcp.py                 # default: install all backends
    python setup_mcp.py --extras db     # only what you need (ssh|container|k8s|db|all|none)
    python setup_mcp.py --skip-install  # assume the venv is already set up

It will:
  1. Create ``serverOps/.venv`` (if missing) from the interpreter running it.
  2. ``pip install -e 'serverOps[<extras>]'`` into that venv.
  3. Seed ``config/servers.yaml`` and ``.env`` from their examples (never overwriting
     existing copies — your real config/secrets are protected).
  4. (Re)generate ``.mcp.json`` pointing the launcher at the venv python, the config,
     and the single ``.env`` secrets file — so you drop secrets in one place and reload.

Cross-platform: identical command on Windows (git-bash / cmd / PowerShell) and
POSIX (Linux / macOS). The venv layout (Scripts/ vs bin/) is detected automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

VALID_EXTRAS = {"ssh", "container", "k8s", "db", "all", "none"}


def venv_python(venv: Path) -> Path:
    """The venv's python executable, platform-aware."""
    rel = Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python"
    return venv / rel


def run(cmd: list[str], *, desc: str) -> None:
    print(f"[setup] {desc}")
    print(f"        {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent
    serverops = root / "serverOps"
    venv = serverops / ".venv"

    parser = argparse.ArgumentParser(description="Bootstrap serverOps for an MCP client.")
    parser.add_argument("--serverops-dir", default=str(serverops), help="Path to the serverOps package dir.")
    parser.add_argument("--extras", default="all", choices=sorted(VALID_EXTRAS), help="Optional backends to install.")
    parser.add_argument("--skip-install", action="store_true", help="Skip venv creation + pip install.")
    parser.add_argument("--mcp-json", default=str(root / ".mcp.json"), help="Path of the .mcp.json to generate.")
    parser.add_argument("--no-mcp-json", action="store_true", help="Do not (re)generate .mcp.json.")
    args = parser.parse_args(argv)

    serverops = Path(args.serverops_dir).resolve()
    venv = serverops / ".venv"
    py = venv_python(venv)

    # 1 + 2 — venv + install (skippable for re-runs / offline edits).
    if not args.skip_install:
        if not venv.exists():
            run([sys.executable, "-m", "venv", str(venv)], desc="create venv")
        spec = str(serverops) if args.extras == "none" else f"{serverops}[{args.extras}]"
        run([str(py), "-m", "pip", "install", "--upgrade", "pip"], desc="upgrade pip")
        run([str(py), "-m", "pip", "install", "-e", spec], desc=f"install serverops[{args.extras}]")
    elif not py.exists():
        print(f"[setup] --skip-install set but venv python not found at {py}", file=sys.stderr)
        return 1

    # 3 — seed config + secrets from examples (never clobber existing real files).
    seeds = [
        (serverops / "config" / "servers.example.yaml", serverops / "config" / "servers.yaml"),
        (serverops / ".env.example", serverops / ".env"),
    ]
    for example, target in seeds:
        if target.exists():
            print(f"[setup] keep existing {target.relative_to(root)}")
            continue
        if not example.exists():
            print(f"[setup] WARN: example missing, skip {target.relative_to(root)}", file=sys.stderr)
            continue
        shutil.copyfile(example, target)
        print(f"[setup] seeded   {target.relative_to(root)}  <-  {example.name}")

    config_path = (serverops / "config" / "servers.yaml").resolve()
    secrets_path = (serverops / ".env").resolve()

    # 4 — generate a minimal .mcp.json (config + secrets paths only; no inline secrets).
    if not args.no_mcp_json:
        mcp = {
            "mcpServers": {
                "serverops": {
                    "command": str(py),
                    "args": ["-m", "serverops"],
                    "env": {
                        "SERVEROPS_CONFIG": str(config_path),
                        "SERVEROPS_SECRETS": str(secrets_path),
                    },
                }
            }
        }
        out = Path(args.mcp_json).resolve()
        out.write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8")
        print(f"[setup] wrote    {out}")

    print("\n[setup] done.")
    print("  Next steps:")
    print(f"  1. Edit secrets in one file:  {secrets_path}")
    print(f"  2. Edit connections in:       {config_path}")
    print("  3. Reload your MCP client (Claude Code / Desktop) to pick up .mcp.json.")
    print("  4. (Verify) connection_list  /  server_health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
