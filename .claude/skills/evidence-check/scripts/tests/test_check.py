#!/usr/bin/env python3
"""Tests for evidence-check.py audit engine."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK_PY = Path(__file__).resolve().parent.parent / "check.py"


def make_pipeline_state(tasks_dir, change_name, state):
    """Write a stub pipeline-state.json under tasks_dir/<change_name>/."""
    change_dir = tasks_dir / change_name
    change_dir.mkdir(parents=True, exist_ok=True)
    ps_path = change_dir / "pipeline-state.json"
    ps_path.write_text(json.dumps(state, ensure_ascii=False))


def run_check(repo_path, extra_args=None):
    """Run check.py against a repo, return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, str(CHECK_PY), "--repo", str(repo_path), "--all"]
    if extra_args:
        cmd.extend(extra_args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.returncode, r.stdout, r.stderr


def load_audit_json(repo_path):
    """Load the generated audit JSON for this repo."""
    repo_name = Path(repo_path).resolve().name
    path = Path(repo_path) / ".harness" / "audit" / f"{repo_name}.json"
    return json.loads(path.read_text())


class TestDevelopmentFlow(unittest.TestCase):
    def test_all_fields_pass(self):
        """development flow with all 6 fields → pass"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "my-feature", {
                "schema_version": 6,
                "caller": "wangzk",
                "title": "My feature change",
                "flow_type": "development",
                "current_phase": "completed",
                "created_at": "2026-06-15T00:00:00Z",
                "scores": {"reviewer": 92},
                "pipeline": {
                    "intake": {
                        "status": "done", "exit_status": "DONE",
                        "summary": "intake passed",
                        "dispatch_history": [{"token_usage": {"input_tokens": 100, "output_tokens": 50, "model": "test"}}],
                    },
                    "test": {
                        "status": "done", "exit_status": "DONE",
                        "dispatch_history": [{"token_usage": {"input_tokens": 200, "output_tokens": 80, "model": "test"}}],
                    },
                },
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0, f"stderr={stderr}")
            data = load_audit_json(repo)
            c = data["changes"][0]
            self.assertEqual(c["audit_result"], "pass")
            self.assertEqual(c["classification"], "business")
            self.assertEqual(c["completeness"]["present"], 6)
            self.assertEqual(len(c["findings"]), 0)

    def test_missing_test_report_block(self):
        """development flow missing test_report → block"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "no-test", {
                "schema_version": 6,
                "caller": "wangzk",
                "title": "No tester ran",
                "flow_type": "development",
                "current_phase": "code-review",
                "created_at": "2026-06-15T00:00:00Z",
                "scores": {"reviewer": 85},
                "pipeline": {
                    "intake": {
                        "status": "done", "exit_status": "DONE",
                        "summary": "intake passed",
                        "dispatch_history": [{"token_usage": {"input_tokens": 100, "output_tokens": 50, "model": "test"}}],
                    },
                },
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            data = load_audit_json(repo)
            c = data["changes"][0]
            self.assertEqual(c["audit_result"], "block")
            self.assertIn("test_report", c["completeness"]["missing"])


    def test_in_progress_phases(self):
        """development flow with test/code-review still pending → in_progress"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "still-building", {
                "schema_version": 6,
                "caller": "wangzk",
                "title": "Still implementing",
                "flow_type": "development",
                "current_phase": "implement",
                "created_at": "2026-06-15T00:00:00Z",
                "pipeline": {
                    "intake": {
                        "status": "done", "exit_status": "DONE",
                        "summary": "ok",
                        "dispatch_history": [{"token_usage": {"input_tokens": 100, "output_tokens": 50, "model": "test"}}],
                    },
                    "test": {"status": "pending"},
                    "code-review": {"status": "pending"},
                },
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            data = load_audit_json(repo)
            c = data["changes"][0]
            self.assertEqual(c["audit_result"], "in_progress")
            self.assertIn("test_report", c["completeness"]["pending"])
            self.assertIn("review_score", c["completeness"]["pending"])


class TestQuickFlow(unittest.TestCase):
    def test_na_fields_accepted(self):
        """quick flow missing test_report + review_score → pass (N/A allowed)"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "quick-fix", {
                "schema_version": 6,
                "caller": "wangzk",
                "title": "Quick fix",
                "flow_type": "quick",
                "current_phase": "completed",
                "created_at": "2026-06-15T00:00:00Z",
                "pipeline": {
                    "intake": {
                        "status": "done", "exit_status": "DONE",
                        "summary": "quick fix done",
                        "dispatch_history": [{"token_usage": {"input_tokens": 500, "output_tokens": 100, "model": "test"}}],
                    },
                },
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            data = load_audit_json(repo)
            c = data["changes"][0]
            self.assertEqual(c["audit_result"], "pass")
            self.assertIn("test_report", c["completeness"]["na"])
            self.assertIn("review_score", c["completeness"]["na"])


class TestClassification(unittest.TestCase):
    def test_ci_driven_excluded(self):
        """E2E CI-driven change → na"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "e2e-smoke-test", {
                "schema_version": 6,
                "title": "E2E smoke test",
                "flow_type": "development",
                "current_phase": "completed",
                "created_at": "2026-06-15T00:00:00Z",
                "scores": {"reviewer": 80},
                "pipeline": {},
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            data = load_audit_json(repo)
            c = data["changes"][0]
            self.assertEqual(c["audit_result"], "na")
            self.assertEqual(c["classification"], "ci_driven")

    def test_not_started_excluded(self):
        """Pending + 0 dispatch → na"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "draft", {
                "schema_version": 6,
                "title": "Draft change",
                "flow_type": "development",
                "current_phase": "pending",
                "created_at": "2026-06-15T00:00:00Z",
                "pipeline": {},
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            data = load_audit_json(repo)
            c = data["changes"][0]
            self.assertEqual(c["audit_result"], "na")
            self.assertEqual(c["classification"], "not_started")


class TestOldSchemaCompatibility(unittest.TestCase):
    def test_old_schema_detection(self):
        """Old schema (no caller, no test phase) → handled gracefully"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "legacy-change", {
                "title": "Legacy change",
                "flow_type": "development",
                "current_phase": "archive",
                "created_at": "2026-06-15T00:00:00Z",
                "scores": {"reviewer": 88},
                "pipeline": {
                    "intake": {
                        "status": "done", "exit_status": "DONE",
                        "summary": "old style",
                        "dispatch_history": [{"token_usage": {"input_tokens": 300, "output_tokens": 50, "model": "test"}}],
                    },
                    "apply": {
                        "status": "done", "exit_status": "DONE",
                        "dispatch_history": [
                            {"token_usage": {"input_tokens": 500, "output_tokens": 200, "model": "test"}},
                            {"token_usage": {"input_tokens": 200, "output_tokens": 100, "model": "test"}},
                        ],
                    },
                },
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            data = load_audit_json(repo)
            c = data["changes"][0]
            self.assertEqual(c["classification"], "business")
            ec = c["evidence_chain"]
            # apply phase has 2 dispatches → test detected via old schema
            self.assertTrue(ec["test_report"]["present"])
            self.assertTrue(ec["review_score"]["present"])
            # no caller field → trigger missing (temp dir not a git repo)
            self.assertFalse(ec["trigger_source"]["present"])


class TestEdgeCases(unittest.TestCase):
    def test_empty_tasks_dir(self):
        """Empty tasks dir → exit 0"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            tasks.mkdir(parents=True)
            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)

    def test_corrupted_json_skipped(self):
        """Corrupted pipeline-state.json → skip, no crash"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            bad_dir = tasks / "bad-change"
            bad_dir.mkdir(parents=True)
            (bad_dir / "pipeline-state.json").write_text("not valid json {{{")

            make_pipeline_state(tasks, "good-change", {
                "schema_version": 6,
                "caller": "wangzk",
                "title": "Good change",
                "flow_type": "quick",
                "current_phase": "completed",
                "created_at": "2026-06-15T00:00:00Z",
                "pipeline": {
                    "intake": {
                        "status": "done", "exit_status": "DONE",
                        "summary": "ok",
                        "dispatch_history": [{"token_usage": {"input_tokens": 100, "output_tokens": 50, "model": "test"}}],
                    },
                },
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            data = load_audit_json(repo)
            self.assertEqual(len(data["changes"]), 1)
            self.assertEqual(data["changes"][0]["change_name"], "good-change")

    def test_markdown_output(self):
        """Markdown output has expected sections"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test-repo"
            tasks = repo / ".harness" / "tasks"
            make_pipeline_state(tasks, "md-test", {
                "schema_version": 6,
                "caller": "wangzk",
                "title": "Markdown test",
                "flow_type": "development",
                "current_phase": "completed",
                "created_at": "2026-06-15T00:00:00Z",
                "scores": {"reviewer": 95},
                "pipeline": {
                    "intake": {
                        "status": "done", "exit_status": "DONE",
                        "summary": "md test intake",
                        "dispatch_history": [{"token_usage": {"input_tokens": 100, "output_tokens": 50, "model": "test"}}],
                    },
                    "test": {
                        "status": "done", "exit_status": "DONE",
                        "dispatch_history": [{"token_usage": {"input_tokens": 50, "output_tokens": 30, "model": "test"}}],
                    },
                },
            })

            code, stdout, stderr = run_check(repo)
            self.assertEqual(code, 0)
            repo_name = repo.resolve().name
            md_path = repo / ".harness" / "audit" / f"{repo_name}.md"
            self.assertTrue(md_path.exists())
            md_content = md_path.read_text()
            self.assertIn("# 证据链合规审计", md_content)
            self.assertIn("## 1. 摘要", md_content)
            self.assertIn("## 2. 明细", md_content)
            self.assertIn("✅", md_content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
