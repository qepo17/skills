from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import artifact_guard  # noqa: E402
import workflow_tools  # noqa: E402


class WorkflowPolicyTests(unittest.TestCase):
    def test_auto_uses_standard_for_low_risk_single_repository(self) -> None:
        result = workflow_tools.workflow_policy(
            repository_count=1,
            risk_flags=[],
        )
        self.assertEqual("standard", result["profile"])
        self.assertFalse(result["workflow_policy"]["contract_required"])
        self.assertEqual(3, result["workflow_policy"]["max_tasks_per_packet"])
        self.assertEqual(30, result["workflow_policy"]["coordinator_attempt_budget"])
        self.assertTrue(result["workflow_policy"]["user_plan_approval_required"])

    def test_user_plan_approval_policy_cannot_be_disabled(self) -> None:
        result = workflow_tools.workflow_policy(
            repository_count=1,
            risk_flags=[],
        )
        result["workflow_policy"]["user_plan_approval_required"] = False
        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "may not waive user plan approval",
        ):
            artifact_guard.validate_workflow_policy(
                result["workflow_policy"],
                result["profile"],
                "$.workflow_policy",
            )

    def test_high_risk_fast_request_escalates_to_full(self) -> None:
        result = workflow_tools.workflow_policy(
            repository_count=1,
            risk_flags=["database-migration"],
            requested_profile="fast",
        )
        self.assertEqual("full", result["profile"])
        self.assertTrue(result["workflow_policy"]["contract_required"])
        self.assertIn("safety profiles cannot be weakened", " ".join(result["profile_reasons"]))

    def test_fast_is_available_only_by_explicit_request(self) -> None:
        result = workflow_tools.workflow_policy(
            repository_count=1,
            risk_flags=[],
            requested_profile="fast",
        )
        self.assertEqual("fast", result["profile"])
        self.assertEqual("none", result["workflow_policy"]["design_challenge"])

    def test_fast_public_interface_request_escalates_to_standard(self) -> None:
        result = workflow_tools.workflow_policy(
            repository_count=1,
            risk_flags=["public-interface"],
            requested_profile="fast",
        )
        self.assertEqual("standard", result["profile"])
        self.assertEqual("risk-only", result["workflow_policy"]["design_challenge"])


class UserPlanApprovalGuardTests(unittest.TestCase):
    def test_project_writer_requires_approved_and_hash_pinned_review_bundle(self) -> None:
        review_path = Path("/tmp/plan-review-v1.md")
        review_hash = "a" * 64
        run = {
            "phase": "plan-review",
            "workflow_policy": {"user_plan_approval_required": True},
            "plan_review": {
                "status": "pending",
                "review_path": str(review_path),
                "review_sha256": review_hash,
            },
        }
        assignment_path = Path("/tmp/implement-api.json")
        assignment = {"project_file_access": "write"}

        with self.assertRaisesRegex(ValueError, "explicitly approves"):
            workflow_tools._enforce_user_plan_approval(
                run,
                [(assignment_path, assignment)],
            )

        run["phase"] = "implement"
        run["plan_review"]["status"] = "approved"
        with self.assertRaisesRegex(ValueError, "does not pin"):
            workflow_tools._enforce_user_plan_approval(
                run,
                [(assignment_path, assignment)],
            )

        assignment["plan_review"] = {
            "path": str(review_path),
            "sha256": review_hash,
        }
        workflow_tools._enforce_user_plan_approval(
            run,
            [(assignment_path, assignment)],
        )


class WorktreeFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()
        self.git_run("git", "init", "-q")
        self.git_run("git", "config", "user.email", "tests@example.com")
        self.git_run("git", "config", "user.name", "Tests")
        (self.repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.git_run("git", "add", "tracked.txt")
        self.git_run("git", "commit", "-qm", "initial")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def git_run(self, *command: str) -> None:
        subprocess.run(command, cwd=self.repo, check=True)

    def test_fingerprint_tracks_modified_and_untracked_content(self) -> None:
        clean = workflow_tools.worktree_fingerprint(self.repo)
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        modified = workflow_tools.worktree_fingerprint(self.repo)
        self.assertNotEqual(clean, modified)

        (self.repo / "new.txt").write_text("untracked\n", encoding="utf-8")
        untracked = workflow_tools.worktree_fingerprint(self.repo)
        self.assertNotEqual(modified, untracked)

        (self.repo / "new.txt").unlink()
        self.git_run("git", "checkout", "--", "tracked.txt")
        self.assertEqual(clean, workflow_tools.worktree_fingerprint(self.repo))


class BatchSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.repo = self.root / "repo"
        self.worktree = self.root / "worktree"
        self.log_dir = self.root / "run" / "repos" / "api" / "logs"
        self.assignments = self.root / "run" / "assignments"
        for directory in (self.repo, self.worktree, self.log_dir, self.assignments):
            directory.mkdir(parents=True, exist_ok=True)
        self.initial = self.root / "run" / "repos" / "api" / "initial-status.txt"
        self.initial.write_text("", encoding="utf-8")
        self.input = self.root / "run" / "requirements.json"
        self.input.write_text('{"artifact_kind":"requirements"}\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_json(self, path: Path, value: dict[str, Any]) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_dry_run_validates_and_builds_one_batch_command(self) -> None:
        output = self.root / "run" / "repos" / "api" / "validation-1.json"
        assignment_path = self.assignments / "validate-api-1.json"
        assignment = {
            "schema_version": 1,
            "artifact_kind": "assignment",
            "run_id": "20260817T120000Z-example",
            "action_id": "validate:api:1",
            "created_at": "2026-08-17T12:00:00Z",
            "stage": "validate",
            "attempt": 1,
            "repo_id": "api",
            "cwd": str(self.worktree),
            "thinking": "medium",
            "timeout_seconds": 600,
            "project_file_access": "none",
            "git_access": "none",
            "forge_access": "none",
            "repositories": [
                {
                    "repo_id": "api",
                    "root": str(self.repo),
                    "worktree": str(self.worktree),
                    "access": "read",
                }
            ],
            "baseline": "a" * 40,
            "preexisting_status_path": str(self.initial),
            "input_artifacts": [{"path": str(self.input), "sha256": self.sha(self.input)}],
            "requirement_ids": ["REQ-001"],
            "instructions": ["Run the assigned validation commands."],
            "validation_commands": ["python -m unittest"],
            "output_kind": "result",
            "output_artifact": str(output),
            "log_dir": str(self.log_dir),
            "artifact_schema_path": str(SCRIPTS_DIR.parent / "schemas" / "result.md"),
            "validator_path": str(SCRIPTS_DIR / "artifact_guard.py"),
        }
        self.write_json(assignment_path, assignment)

        with mock.patch.dict(os.environ, {}, clear=True):
            code, manifest = workflow_tools.run_assignment_batch(
                [assignment_path],
                run_dir=self.root / "run",
                worker_runtime="pi",
                dry_run=True,
            )
        self.assertEqual(0, code)
        self.assertEqual("dry-run", manifest["workers"][0]["status"])
        command = manifest["workers"][0]["command"]
        self.assertEqual("direct", manifest["execution_context"]["backend"])
        self.assertEqual("pi", command[0])
        self.assertIn("--print", command)
        self.assertIn("--no-session", command)
        self.assertIn("--thinking", command)
        self.assertIn("max", command)
        self.assertIn("--model", command)
        self.assertIn("openai-codex/gpt-5.6-luna", command)
        self.assertEqual("pi", manifest["workers"][0]["runtime"])
        self.assertIn(str(assignment_path.resolve()), command[-1])

    def test_dry_run_uses_codex_for_a_codex_coordinator(self) -> None:
        output = self.root / "run" / "repos" / "api" / "validation-codex.json"
        assignment_path = self.assignments / "validate-api-codex.json"
        assignment = {
            "schema_version": 1,
            "artifact_kind": "assignment",
            "run_id": "20260817T120000Z-example",
            "action_id": "validate:api:codex",
            "created_at": "2026-08-17T12:00:00Z",
            "stage": "validate",
            "attempt": 1,
            "repo_id": "api",
            "cwd": str(self.worktree),
            "thinking": "medium",
            "timeout_seconds": 600,
            "project_file_access": "none",
            "git_access": "none",
            "forge_access": "none",
            "repositories": [
                {
                    "repo_id": "api",
                    "root": str(self.repo),
                    "worktree": str(self.worktree),
                    "access": "read",
                }
            ],
            "baseline": "a" * 40,
            "preexisting_status_path": str(self.initial),
            "input_artifacts": [{"path": str(self.input), "sha256": self.sha(self.input)}],
            "requirement_ids": ["REQ-001"],
            "instructions": ["Run the assigned validation commands."],
            "validation_commands": ["python -m unittest"],
            "output_kind": "result",
            "output_artifact": str(output),
            "log_dir": str(self.log_dir),
            "artifact_schema_path": str(SCRIPTS_DIR.parent / "schemas" / "result.md"),
            "validator_path": str(SCRIPTS_DIR / "artifact_guard.py"),
        }
        self.write_json(assignment_path, assignment)

        with mock.patch.dict(os.environ, {}, clear=True):
            code, manifest = workflow_tools.run_assignment_batch(
                [assignment_path],
                run_dir=self.root / "run",
                worker_runtime="codex",
                dry_run=True,
            )
        self.assertEqual(0, code)
        command = manifest["workers"][0]["command"]
        self.assertEqual("direct", manifest["execution_context"]["backend"])
        self.assertEqual("codex", command[0])
        self.assertIn("exec", command)
        self.assertIn("--model", command)
        self.assertIn("gpt-5.6-luna", command)
        self.assertIn('model_reasoning_effort="max"', command)
        self.assertEqual("codex", manifest["workers"][0]["runtime"])

    def test_project_writer_batch_requires_run_state_with_plan_approval(self) -> None:
        plan = self.root / "run" / "repos" / "api" / "plan-v1.json"
        self.write_json(
            plan,
            {
                "artifact_kind": "plan",
                "repo_id": "api",
                "design_challenge_required": False,
            },
        )
        output = self.root / "run" / "repos" / "api" / "implementation-1.json"
        assignment_path = self.assignments / "implement-api-1.json"
        assignment = {
            "schema_version": 1,
            "artifact_kind": "assignment",
            "run_id": "20260817T120000Z-example",
            "action_id": "implement:api:1",
            "created_at": "2026-08-17T12:00:00Z",
            "stage": "implement",
            "attempt": 1,
            "repo_id": "api",
            "cwd": str(self.worktree),
            "thinking": "high",
            "timeout_seconds": 600,
            "project_file_access": "write",
            "git_access": "none",
            "forge_access": "none",
            "repositories": [
                {
                    "repo_id": "api",
                    "root": str(self.repo),
                    "worktree": str(self.worktree),
                    "access": "write",
                }
            ],
            "baseline": "a" * 40,
            "preexisting_status_path": str(self.initial),
            "input_artifacts": [{"path": str(plan), "sha256": self.sha(plan)}],
            "requirement_ids": ["REQ-001"],
            "instructions": ["Implement the approved plan."],
            "validation_commands": [],
            "output_kind": "result",
            "output_artifact": str(output),
            "log_dir": str(self.log_dir),
            "artifact_schema_path": str(SCRIPTS_DIR.parent / "schemas" / "result.md"),
            "validator_path": str(SCRIPTS_DIR / "artifact_guard.py"),
        }
        self.write_json(assignment_path, assignment)

        with self.assertRaisesRegex(ValueError, "require run.json"):
            workflow_tools.run_assignment_batch(
                [assignment_path],
                run_dir=self.root / "run",
                dry_run=True,
            )

    def test_supervisor_waits_validates_and_closes_an_accepted_worker(self) -> None:
        output = self.root / "run" / "repos" / "api" / "validation-accepted.json"
        assignment_path = self.assignments / "validate-api-accepted.json"
        assignment = {
            "schema_version": 1,
            "artifact_kind": "assignment",
            "run_id": "20260817T120000Z-example",
            "action_id": "validate:api:accepted",
            "created_at": "2026-08-17T12:00:00Z",
            "stage": "validate",
            "attempt": 1,
            "repo_id": "api",
            "cwd": str(self.worktree),
            "thinking": "medium",
            "timeout_seconds": 600,
            "project_file_access": "none",
            "git_access": "none",
            "forge_access": "none",
            "repositories": [
                {
                    "repo_id": "api",
                    "root": str(self.repo),
                    "worktree": str(self.worktree),
                    "access": "read",
                }
            ],
            "baseline": "a" * 40,
            "preexisting_status_path": str(self.initial),
            "input_artifacts": [{"path": str(self.input), "sha256": self.sha(self.input)}],
            "requirement_ids": ["REQ-001"],
            "instructions": ["Run validation."],
            "validation_commands": [],
            "output_kind": "result",
            "output_artifact": str(output),
            "log_dir": str(self.log_dir),
            "artifact_schema_path": str(SCRIPTS_DIR.parent / "schemas" / "result.md"),
            "validator_path": str(SCRIPTS_DIR / "artifact_guard.py"),
        }
        self.write_json(assignment_path, assignment)
        status_path = self.log_dir / "accepted-status.txt"
        status_path.write_text("", encoding="utf-8")
        result = {
            "schema_version": 1,
            "artifact_kind": "result",
            "run_id": assignment["run_id"],
            "assignment_path": str(assignment_path),
            "assignment_sha256": self.sha(assignment_path),
            "repo_id": "api",
            "stage": "validate",
            "attempt": 1,
            "created_at": "2026-08-17T12:01:00Z",
            "status": "complete",
            "summary": "Validation completed.",
            "requirement_ids": ["REQ-001"],
            "task_ids": [],
            "changed_files": [],
            "validations": [],
            "decisions": [],
            "resolutions": [],
            "git": {"head": "a" * 40, "status_short_path": str(status_path)},
            "blockers": [],
            "next_action": "review-1",
        }
        self.write_json(output, result)
        fake_herdr = self.root / "fake-herdr.py"
        command_log = self.root / "herdr-commands.jsonl"
        fake_herdr.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            f"log = pathlib.Path({str(command_log)!r})\n"
            "with log.open('a', encoding='utf-8') as handle:\n"
            "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:4] == ['status', 'server', '--json']:\n"
            "    print(json.dumps({'running': True, 'compatible': True, 'protocol': 20}))\n"
            "elif sys.argv[1:3] == ['workspace', 'create']:\n"
            "    print(json.dumps({'result': {'workspace': 'workspace-test', "
            "'root_pane': {'pane_id': 'pane-test'}}}))\n"
            "else:\n"
            "    print(json.dumps({'result': {'ok': True}}))\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        fake_herdr.chmod(0o755)

        with mock.patch.dict(os.environ, {"HERDR_ENV": "1"}, clear=True):
            code, manifest = workflow_tools.run_assignment_batch(
                [assignment_path],
                run_dir=self.root / "run",
                herdr_binary=str(fake_herdr),
                allow_existing=True,
            )
        commands = [json.loads(line) for line in command_log.read_text().splitlines()]
        self.assertEqual(0, code)
        self.assertEqual("accepted", manifest["workers"][0]["status"])
        self.assertIn(["workspace", "close", "workspace-test"], commands)
        self.assertNotIn(["pane", "close", "pane-test"], commands)
        self.assertEqual("herdr", manifest["workers"][0]["backend"])
        self.assertEqual("complete", manifest["workers"][0]["cleanup_status"])
        self.assertTrue(Path(manifest["batch_log"]).is_file())


class DeterministicReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.run_dir = self.root / "run"
        self.repo = self.root / "repo"
        self.worktree = self.root / "worktree"
        self.log_dir = self.run_dir / "integration" / "logs"
        for directory in (self.run_dir, self.repo, self.worktree, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_report_is_rendered_from_artifacts_and_escapes_request_text(self) -> None:
        request = self.run_dir / "request.md"
        request.write_text("Ship <script>alert('x')</script> safely.\n", encoding="utf-8")
        requirements_path = self.run_dir / "requirements.json"
        requirements = {
            "schema_version": 1,
            "artifact_kind": "requirements",
            "run_id": "20260817T130000Z-report",
            "created_at": "2026-08-17T13:00:00Z",
            "requirements": [
                {
                    "id": "REQ-001",
                    "source_text": "Ship safely.",
                    "acceptance_criteria": ["The report escapes repository-derived text."],
                    "repository_ids": ["api"],
                }
            ],
            "constraints": [],
        }
        self.write_json(requirements_path, requirements)
        initial = self.run_dir / "repos" / "api" / "initial-status.txt"
        initial.parent.mkdir(parents=True)
        initial.write_text("", encoding="utf-8")
        run = {
            "run_id": "20260817T130000Z-report",
            "status": "working",
            "phase": "report",
            "profile": "standard",
            "request_path": str(request),
            "requirements_path": str(requirements_path),
            "repositories": {
                "api": {
                    "branch": "feat/report",
                    "base_branch": "main",
                    "accepted_artifacts": {},
                }
            },
            "accepted_artifacts": {},
        }
        self.write_json(self.run_dir / "run.json", run)

        output = self.run_dir / "report.json"
        html_path = self.root / "artifacts" / "report.html"
        assignment_path = self.run_dir / "assignments" / "report-global-1.json"
        assignment = {
            "schema_version": 1,
            "artifact_kind": "assignment",
            "run_id": run["run_id"],
            "action_id": "report:global:1",
            "created_at": "2026-08-17T13:10:00Z",
            "stage": "report",
            "attempt": 1,
            "profile": "standard",
            "repo_id": None,
            "cwd": str(self.run_dir),
            "thinking": "medium",
            "timeout_seconds": 600,
            "project_file_access": "none",
            "git_access": "none",
            "forge_access": "none",
            "repositories": [
                {
                    "repo_id": "api",
                    "root": str(self.repo),
                    "worktree": str(self.worktree),
                    "access": "read",
                }
            ],
            "baseline": None,
            "preexisting_status_path": None,
            "input_artifacts": [
                {"path": str(requirements_path), "sha256": self.sha(requirements_path)}
            ],
            "requirement_ids": ["REQ-001"],
            "instructions": ["Render accepted artifacts deterministically."],
            "validation_commands": [],
            "output_kind": "report",
            "output_artifact": str(output),
            "log_dir": str(self.log_dir),
            "artifact_schema_path": str(SCRIPTS_DIR.parent / "schemas" / "report.md"),
            "validator_path": str(SCRIPTS_DIR / "artifact_guard.py"),
        }
        self.write_json(assignment_path, assignment)

        report = workflow_tools.render_report(
            run_dir=self.run_dir,
            assignment_path=assignment_path,
            html_path=html_path,
            output_path=output,
        )
        self.assertEqual(["REQ-001"], report["requirement_ids"])
        rendered = html_path.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        artifact_guard.CURRENT_ARTIFACT_PATH = output
        artifact_guard.validate_report(report)


if __name__ == "__main__":
    unittest.main()
