from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import artifact_guard  # noqa: E402
from workflow_engine import WorkflowEngine, WorkflowError, build_graph  # noqa: E402


class FakePlanningBatch:
    def __init__(
        self,
        *,
        migration_capable: bool = False,
        risk_flags: list[str] | None = None,
    ) -> None:
        self.assignments: list[dict[str, Any]] = []
        self.migration_capable = migration_capable
        self.risk_flags = sorted(
            set(risk_flags or [])
            | ({"database-migration"} if migration_capable else set())
        )

    def __call__(
        self,
        assignment_paths: list[Path],
        *,
        run_dir: Path,
        worker_runtime: str,
        allow_existing: bool,
    ) -> tuple[int, dict[str, Any]]:
        workers = []
        for assignment_path in assignment_paths:
            assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
            self.assignments.append(assignment)
            output = Path(assignment["output_artifact"])
            if not output.exists():
                artifact_guard.initialize_artifact(assignment_path)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            if assignment["output_kind"] != "plan":
                raise AssertionError(
                    f"unexpected fake assignment: {assignment['stage']}"
                )
            artifact.update(
                {
                    "status": "complete",
                    "risk_flags": self.risk_flags,
                    "design_challenge_required": (
                        assignment.get("profile") == "full" or bool(self.risk_flags)
                    ),
                    "tasks": [
                        {
                            "id": "API-TASK-001",
                            "requirement_ids": ["REQ-001"],
                            "depends_on": [],
                            "summary": "Implement the requested behavior.",
                            "steps": ["Follow the repository convention."],
                            "expected_files": ["feature.txt"],
                            "validation_ids": ["API-VAL-001"],
                            "mechanism_ids": [],
                        }
                    ],
                    "work_packets": [
                        {
                            "id": "API-PACKET-001",
                            "summary": "Implement and verify the requested behavior.",
                            "task_ids": ["API-TASK-001"],
                            "depends_on": [],
                            "estimated_minutes": 20,
                        }
                    ],
                    "validations": [
                        {
                            "id": "API-VAL-001",
                            "command": "python -m unittest",
                            "cwd": assignment["cwd"],
                            "scope": "broad",
                            "migration_capable": self.migration_capable,
                        }
                    ],
                    "complexity_mechanisms": [],
                    "finding_resolutions": [],
                    "non_goals": ["No unrelated refactor."],
                    "risks": [],
                    "blockers": [],
                }
            )
            output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
            artifact_guard.CURRENT_ARTIFACT_PATH = output
            artifact_guard.validate_plan(artifact)
            workers.append(
                {
                    "action_id": assignment["action_id"],
                    "agent_name": f"fake-{len(self.assignments)}",
                    "assignment_path": str(assignment_path),
                    "output_artifact": str(output),
                    "started_at": "2026-08-22T10:00:00Z",
                    "ended_at": "2026-08-22T10:01:00Z",
                    "backend": "test",
                    "handle_id": f"worker-{len(self.assignments)}",
                    "cleanup_status": "complete",
                    "status": "accepted",
                    "reason": None,
                }
            )
        return 0, {"generated_at": "2026-08-22T10:01:00Z", "workers": workers}


class CaptureRejectingBatch:
    def __init__(self) -> None:
        self.allow_existing: bool | None = None

    def __call__(
        self,
        assignment_paths: list[Path],
        *,
        run_dir: Path,
        worker_runtime: str,
        allow_existing: bool,
    ) -> tuple[int, dict[str, Any]]:
        self.allow_existing = allow_existing
        workers = []
        for index, path in enumerate(assignment_paths, start=1):
            assignment = json.loads(path.read_text(encoding="utf-8"))
            workers.append(
                {
                    "action_id": assignment["action_id"],
                    "agent_name": f"capture-{index}",
                    "assignment_path": str(path),
                    "output_artifact": assignment["output_artifact"],
                    "started_at": "2026-08-22T10:00:00Z",
                    "ended_at": "2026-08-22T10:01:00Z",
                    "terminal_id": f"capture-pane-{index}",
                    "status": "rejected",
                    "reason": "simulated recovery batch",
                }
            )
        return 1, {"generated_at": "2026-08-22T10:01:00Z", "workers": workers}


class RejectFirstPlanningBatch(FakePlanningBatch):
    def __init__(self) -> None:
        super().__init__()
        self.rejected = False

    def __call__(
        self,
        assignment_paths: list[Path],
        *,
        run_dir: Path,
        worker_runtime: str,
        allow_existing: bool,
    ) -> tuple[int, dict[str, Any]]:
        if not self.rejected:
            self.rejected = True
            assignment = json.loads(assignment_paths[0].read_text(encoding="utf-8"))
            self.assignments.append(assignment)
            return 1, {
                "generated_at": "2026-08-22T10:01:00Z",
                "workers": [
                    {
                        "action_id": assignment["action_id"],
                        "agent_name": "fake-rejected",
                        "assignment_path": str(assignment_paths[0]),
                        "output_artifact": assignment["output_artifact"],
                        "started_at": "2026-08-22T10:00:00Z",
                        "ended_at": "2026-08-22T10:01:00Z",
                        "terminal_id": "pane-rejected",
                        "status": "rejected",
                        "reason": "simulated missing output",
                    }
                ],
            }
        return super().__call__(
            assignment_paths,
            run_dir=run_dir,
            worker_runtime=worker_runtime,
            allow_existing=allow_existing,
        )


class FakeSuccessfulBatch(FakePlanningBatch):
    def __init__(
        self,
        *,
        round_one_finding: bool = False,
        fail_first_validation: bool = False,
        migration_capable: bool = False,
        risk_flags: list[str] | None = None,
    ) -> None:
        super().__init__(
            migration_capable=migration_capable,
            risk_flags=risk_flags,
        )
        self.round_one_finding = round_one_finding
        self.fail_first_validation = fail_first_validation
        self.validation_attempts = 0

    def __call__(
        self,
        assignment_paths: list[Path],
        *,
        run_dir: Path,
        worker_runtime: str,
        allow_existing: bool,
    ) -> tuple[int, dict[str, Any]]:
        if all(
            json.loads(path.read_text(encoding="utf-8"))["stage"] == "plan"
            for path in assignment_paths
        ):
            return super().__call__(
                assignment_paths,
                run_dir=run_dir,
                worker_runtime=worker_runtime,
                allow_existing=allow_existing,
            )
        workers = []
        for assignment_path in assignment_paths:
            assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
            self.assignments.append(assignment)
            output = Path(assignment["output_artifact"])
            if not output.exists():
                artifact_guard.initialize_artifact(assignment_path)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            worktree = Path(assignment["cwd"])
            log_dir = Path(assignment["log_dir"])
            log_dir.mkdir(parents=True, exist_ok=True)
            status_path = (
                log_dir / f"{assignment['stage']}-status-{len(self.assignments)}.txt"
            )

            if assignment["stage"] == "contract":
                artifact.update(
                    {
                        "requirement_map": {"REQ-001": ["api"]},
                        "domain_terms": [],
                        "behavior_rules": [
                            {
                                "id": "RULE-001",
                                "requirement_ids": ["REQ-001"],
                                "description": "The requested behavior remains observable.",
                            }
                        ],
                        "interfaces": [],
                        "dependencies": [],
                        "compatibility": ["Preserve existing callers."],
                        "rollout": ["Deliver the repository change."],
                        "cross_repository_validation": [
                            "Run the planned repository checks."
                        ],
                        "risks": [],
                        "open_questions": [],
                        "blockers": [],
                    }
                )
            elif assignment["stage"] == "design-challenge":
                artifact.update(
                    {
                        "summary": "The plan is the least powerful complete design.",
                        "mechanism_assessments": [],
                        "findings": [],
                        "verdict": "accept",
                        "blockers": [],
                    }
                )
            elif assignment["stage"] == "implement":
                (worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
                status_path.write_text("?? feature.txt\n", encoding="utf-8")
                artifact.update(
                    {
                        "summary": "Implemented the approved packet.",
                        "changed_files": ["feature.txt"],
                        "tree_fingerprint": self._fingerprint(worktree),
                        "validations": [],
                        "decisions": [
                            {
                                "id": "DEC-001",
                                "kind": "implementation",
                                "summary": "Used the existing local module.",
                                "evidence": "feature.txt",
                            }
                        ],
                        "resolutions": [],
                        "git": {
                            "head": self._git(worktree, "rev-parse", "HEAD"),
                            "status_short_path": str(status_path),
                        },
                        "next_action": "validate",
                    }
                )
            elif assignment["stage"] == "validate":
                self.validation_attempts += 1
                should_fail = (
                    self.fail_first_validation and self.validation_attempts == 1
                )
                fingerprint = self._fingerprint(worktree)
                records = []
                assigned_validations = zip(
                    assignment["validation_ids"],
                    assignment["validation_commands"],
                    strict=True,
                )
                for index, (validation_id, command) in enumerate(
                    assigned_validations, start=1
                ):
                    evidence = (
                        log_dir / f"validation-{len(self.assignments)}-{index}.log"
                    )
                    evidence.write_text("pass\n", encoding="utf-8")
                    records.append(
                        {
                            "id": validation_id,
                            "command": command,
                            "command_sha256": __import__("hashlib")
                            .sha256(command.encode())
                            .hexdigest(),
                            "cwd": str(worktree),
                            "tree_fingerprint": fingerprint,
                            "cache_status": "fresh",
                            "source_artifact": None,
                            "exit_code": 1 if should_fail else 0,
                            "result": "fail" if should_fail else "pass",
                            "summary": "Validation failed."
                            if should_fail
                            else "Validation passed.",
                            "log_path": str(evidence),
                        }
                    )
                status_path.write_text(
                    self._git(worktree, "status", "--short") + "\n", encoding="utf-8"
                )
                artifact.update(
                    {
                        "summary": (
                            "A planned check failed."
                            if should_fail
                            else "All planned checks passed."
                        ),
                        "tree_fingerprint": fingerprint,
                        "validations": records,
                        "decisions": [],
                        "resolutions": [],
                        "git": {
                            "head": self._git(worktree, "rev-parse", "HEAD"),
                            "status_short_path": str(status_path),
                        },
                        "next_action": "review-1",
                    }
                )
            elif assignment["stage"] == "validation-fix":
                (worktree / "feature.txt").write_text(
                    "implemented after validation fix\n", encoding="utf-8"
                )
                status_path.write_text(
                    self._git(worktree, "status", "--short") + "\n", encoding="utf-8"
                )
                artifact.update(
                    {
                        "summary": "Resolved the assigned validation failure.",
                        "changed_files": ["feature.txt"],
                        "tree_fingerprint": self._fingerprint(worktree),
                        "validations": [],
                        "decisions": [
                            {
                                "id": "DEC-VAL-FIX-001",
                                "kind": "validation",
                                "summary": "Corrected the validation failure.",
                                "evidence": "feature.txt",
                            }
                        ],
                        "resolutions": [],
                        "git": {
                            "head": self._git(worktree, "rev-parse", "HEAD"),
                            "status_short_path": str(status_path),
                        },
                        "next_action": "validate",
                    }
                )
            elif assignment["stage"] in {"review-1", "review-2"}:
                status_path.write_text(
                    self._git(worktree, "status", "--short") + "\n", encoding="utf-8"
                )
                findings = []
                if assignment["stage"] == "review-1" and self.round_one_finding:
                    findings = [
                        {
                            "id": "API-R1-001",
                            "category": "spec",
                            "severity": "high",
                            "actionable": True,
                            "disposition": "must-fix",
                            "requirement_id": "REQ-001",
                            "path": "feature.txt",
                            "line": 1,
                            "summary": "The first implementation needs correction.",
                            "evidence": "The first line has the pre-fix value.",
                        }
                    ]
                artifact.update(
                    {
                        "reviewed_status_path": str(status_path),
                        "findings": findings,
                        "blockers": [],
                    }
                )
            elif assignment["stage"] in {"fix-1", "fix-2"}:
                (worktree / "feature.txt").write_text(
                    "implemented and fixed\n", encoding="utf-8"
                )
                resolution_log = log_dir / f"{assignment['stage']}-resolution.log"
                resolution_log.write_text("fixed\n", encoding="utf-8")
                status_path.write_text(
                    self._git(worktree, "status", "--short") + "\n", encoding="utf-8"
                )
                artifact.update(
                    {
                        "summary": "Resolved every assigned finding.",
                        "changed_files": ["feature.txt"],
                        "tree_fingerprint": self._fingerprint(worktree),
                        "validations": [],
                        "decisions": [
                            {
                                "id": "DEC-FIX-001",
                                "kind": "finding-resolution",
                                "summary": "Corrected the reviewed behavior.",
                                "evidence": str(resolution_log),
                            }
                        ],
                        "resolutions": [
                            {
                                "finding_id": finding_id,
                                "outcome": "fixed",
                                "summary": "Corrected the reviewed behavior.",
                                "evidence_path": str(resolution_log),
                            }
                            for finding_id in assignment["finding_ids"]
                        ],
                        "git": {
                            "head": self._git(worktree, "rev-parse", "HEAD"),
                            "status_short_path": str(status_path),
                        },
                        "next_action": "validate",
                    }
                )
            elif assignment["stage"] == "integrate":
                inputs = [
                    Path(reference["path"])
                    for reference in assignment["input_artifacts"]
                ]
                plan_path = next(
                    path
                    for path in inputs
                    if path.suffix == ".json"
                    and json.loads(path.read_text(encoding="utf-8")).get(
                        "artifact_kind"
                    )
                    == "plan"
                )
                challenge_path = next(
                    path
                    for path in inputs
                    if path.suffix == ".json"
                    and json.loads(path.read_text(encoding="utf-8")).get(
                        "artifact_kind"
                    )
                    == "design-challenge"
                )
                evidence_path = next(
                    path
                    for path in reversed(inputs)
                    if path.suffix == ".json"
                    and json.loads(path.read_text(encoding="utf-8")).get("stage")
                    == "validate"
                )
                artifact.update(
                    {
                        "requirement_matrix": [
                            {
                                "requirement_id": "REQ-001",
                                "repository_ids": ["api"],
                                "validation_evidence": [str(evidence_path)],
                                "status": "pass",
                            }
                        ],
                        "interfaces": [],
                        "mechanism_conformance": [
                            {
                                "repo_id": "api",
                                "plan_path": str(plan_path),
                                "design_challenge_path": str(challenge_path),
                                "status": "pass",
                                "evidence_paths": [str(evidence_path)],
                            }
                        ],
                        "changed_files_by_repo": {"api": ["feature.txt"]},
                        "rollout": ["Deliver api."],
                        "risks": [],
                        "blockers": [],
                    }
                )
            elif assignment["stage"] == "deliver":
                self._git(worktree, "add", "feature.txt")
                if self._git(worktree, "status", "--short"):
                    self._git(
                        worktree, "commit", "-m", "feat: implement requested behavior"
                    )
                commit = self._git(worktree, "rev-parse", "HEAD")
                check_log = log_dir / "required-check.log"
                check_log.write_text("passed\n", encoding="utf-8")
                artifact.update(
                    {
                        "branch": self._git(worktree, "branch", "--show-current"),
                        "base_branch": "main",
                        "commits": [commit],
                        "pr_url": "https://example.test/pull/1",
                        "checks": [
                            {
                                "name": "tests",
                                "url": "https://example.test/check/1",
                                "required": True,
                                "state": "passed",
                                "evidence_path": str(check_log),
                            }
                        ],
                        "blockers": [],
                    }
                )
            else:
                raise AssertionError(
                    f"unexpected fake assignment: {assignment['stage']}"
                )

            output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
            artifact_guard.CURRENT_ARTIFACT_PATH = output
            artifact_guard.VALIDATORS[assignment["output_kind"]](artifact)
            workers.append(
                {
                    "action_id": assignment["action_id"],
                    "agent_name": f"fake-{len(self.assignments)}",
                    "assignment_path": str(assignment_path),
                    "output_artifact": str(output),
                    "started_at": "2026-08-22T10:00:00Z",
                    "ended_at": "2026-08-22T10:01:00Z",
                    "terminal_id": f"pane-{len(self.assignments)}",
                    "status": "accepted",
                    "reason": None,
                }
            )
        return 0, {"generated_at": "2026-08-22T10:01:00Z", "workers": workers}

    @staticmethod
    def _git(worktree: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(worktree), *args],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    @staticmethod
    def _fingerprint(worktree: Path) -> str:
        from workflow_tools import worktree_fingerprint

        return worktree_fingerprint(worktree)


class WorkflowEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.codebase_design_dir = self.root / "codebase-design"
        self.codebase_design_dir.mkdir()
        (self.codebase_design_dir / "SKILL.md").write_text(
            "---\nname: codebase-design\ndescription: Test fixture.\n---\n",
            encoding="utf-8",
        )
        (self.codebase_design_dir / "DEEPENING.md").write_text(
            "# Deepening\n\nTest fixture.\n",
            encoding="utf-8",
        )
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Tests"], cwd=self.repo, check=True
        )
        (self.repo / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.repo, check=True)
        self.worktree = self.root / "worktree"
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "-qb",
                "feat/langgraph-test",
                str(self.worktree),
            ],
            cwd=self.repo,
            check=True,
        )
        self.spec = self.root / "bootstrap.json"
        self.run_dir = self.root / "run-standard"
        self.now_tick = 0

    def tearDown(self) -> None:
        artifact_guard.CURRENT_ARTIFACT_PATH = None
        self.tempdir.cleanup()

    def now(self) -> str:
        value = datetime(2026, 8, 22, 10, tzinfo=UTC) + timedelta(seconds=self.now_tick)
        self.now_tick += 1
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def write_spec(
        self, *, profile: str = "standard", risks: list[str] | None = None
    ) -> None:
        value = {
            "run_id": "20260822T100000Z-langgraph-test",
            "request": "Implement the requested behavior.",
            "profile": profile,
            "risk_flags": risks or [],
            "requirements": [
                {
                    "id": "REQ-001",
                    "source_text": "Implement the requested behavior.",
                    "acceptance_criteria": ["The behavior is implemented and tested."],
                    "repository_ids": ["api"],
                }
            ],
            "constraints": ["Do not add unrelated behavior."],
            "repositories": [
                {
                    "repo_id": "api",
                    "root": str(self.repo),
                    "worktree": str(self.worktree),
                    "base_branch": "master",
                    "branch": "feat/langgraph-test",
                }
            ],
        }
        self.spec.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def initialize(self, fake: FakePlanningBatch | None = None) -> WorkflowEngine:
        self.write_spec()
        return WorkflowEngine.initialize(
            spec_path=self.spec,
            run_dir=self.run_dir,
            skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.codebase_design_dir,
            batch_runner=fake or FakePlanningBatch(),
            report_root=self.root / "reports",
            now=self.now,
        )

    def test_missing_codebase_design_dependency_reports_install_action(self) -> None:
        engine = WorkflowEngine(
            self.root / "unused-run",
            skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.root / "missing-codebase-design",
        )
        with self.assertRaisesRegex(WorkflowError, "E2E_CODEBASE_DESIGN_DIR"):
            engine._resolve_codebase_design_dir()

    def test_bootstrap_preflight_pins_direct_execution_without_a_terminal_manager(
        self,
    ) -> None:
        self.initialize()
        engine = WorkflowEngine(
            self.run_dir,
            skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.codebase_design_dir,
            report_root=self.root / "reports",
            now=self.now,
        )
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "workflow_engine._git",
                return_value="https://example.invalid/repository",
            ),
        ):
            error = engine._external_preflight_error(engine.load_run())

        self.assertIsNone(error)
        execution = engine.load_run()["worker_execution"]
        self.assertEqual("direct", execution["backend"])
        self.assertEqual("pi", execution["runtime"])
        self.assertEqual("fallback", execution["detected_from"])

    def test_graph_runs_bootstrap_and_planning_then_interrupts_for_exact_bundle(
        self,
    ) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 50,
        }

        output = graph.invoke({"run_dir": str(self.run_dir)}, config=config)

        run = engine.load_run()
        self.assertEqual("plan-review", run["phase"])
        self.assertEqual("awaiting-user", run["status"])
        self.assertEqual(1, len(fake.assignments))
        self.assertEqual("plan", fake.assignments[0]["stage"])
        worker = engine.load_agents()["agents"][0]
        self.assertEqual("test", worker["backend"])
        self.assertEqual("worker-1", worker["handle_id"])
        self.assertEqual("complete", worker["cleanup_status"])
        self.assertNotIn("pane_id", worker)
        self.assertIn("__interrupt__", output)
        payload = output["__interrupt__"][0].value
        self.assertEqual(run["plan_review"]["review_sha256"], payload["review_sha256"])
        self.assertTrue(Path(payload["review_path"]).is_file())

        graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "review_sha256": payload["review_sha256"],
                    "text": "I approve all plans in this exact complete review bundle.",
                }
            ),
            config=config,
            interrupt_after=["plan_review"],
        )
        approved = engine.load_run()
        self.assertEqual("implement", approved["phase"])
        self.assertEqual("approved", approved["plan_review"]["status"])
        self.assertEqual(
            "I approve all plans in this exact complete review bundle.",
            approved["plan_review"]["approval_text"],
        )

    def test_completion_audit_rejects_a_worker_with_an_open_handle(self) -> None:
        engine = self.initialize()
        agents = engine.load_agents()
        agents["agents"].append(
            {
                "name": "open-completed-worker",
                "stage": "review-1",
                "repo_id": "api",
                "attempt": 1,
                "backend": "tmux",
                "handle_id": "@open",
                "status": "idle",
                "cleanup_status": "retained",
                "cleanup_error": None,
                "started_at": "2026-08-22T10:00:00Z",
                "ended_at": "2026-08-22T10:01:00Z",
                "output_artifact": str(self.run_dir / "review.json"),
            }
        )
        engine._save_agents(agents)

        with self.assertRaisesRegex(WorkflowError, "worker handles still open"):
            engine.phase_complete()

    def test_reconcile_retries_cleanup_and_closes_the_agent_projection(self) -> None:
        engine = self.initialize()
        run = engine.load_run()
        run["worker_execution"] = {
            "schema_version": 1,
            "backend": "direct",
            "runtime": "pi",
            "detected_from": "fallback",
            "evidence": {},
        }
        engine._save_run(run)
        agents = engine.load_agents()
        agents["agents"].append(
            {
                "name": "cleanup-retry-worker",
                "stage": "plan",
                "repo_id": "api",
                "attempt": 1,
                "backend": "direct",
                "handle_id": "4242",
                "status": "idle",
                "cleanup_status": "failed",
                "cleanup_error": "temporary cleanup failure",
                "started_at": "2026-08-22T10:00:00Z",
                "ended_at": "2026-08-22T10:01:00Z",
                "output_artifact": str(self.run_dir / "unused-plan.json"),
            }
        )
        engine._save_agents(agents)
        record_path = (
            self.run_dir
            / "supervisor"
            / "worker-"
            f"{hashlib.sha256('cleanup:retry'.encode()).hexdigest()[:16]}.json"
        )
        record_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "action_id": "cleanup:retry",
                    "agent_name": "cleanup-retry-worker",
                    "backend": "direct",
                    "runtime": "pi",
                    "handle_id": "4242",
                    "started_at": "2026-08-22T10:00:00Z",
                    "ended_at": "2026-08-22T10:01:00Z",
                    "status": "settled",
                    "cleanup_status": "failed",
                    "cleanup_error": "temporary cleanup failure",
                    "status_path": str(self.run_dir / "status.json"),
                    "stdout_path": str(self.run_dir / "stdout.log"),
                    "stderr_path": str(self.run_dir / "stderr.log"),
                    "details": {"pid": 4242},
                    "record_path": str(record_path),
                }
            ),
            encoding="utf-8",
        )

        engine.reconcile()

        worker = engine.load_agents()["agents"][0]
        self.assertEqual("complete", worker["cleanup_status"])
        self.assertEqual("closed", worker["status"])
        self.assertIsNone(worker["cleanup_error"])

    def test_resume_retries_external_blockers_but_not_code_decisions(self) -> None:
        engine = self.initialize()
        evidence = self.run_dir / "logs" / "external.log"
        engine._block(
            summary="Forge authentication is temporarily unavailable.",
            evidence_path=evidence,
            required_action="Authenticate, then resume.",
            kind="authentication",
        )
        self.assertTrue(engine.resume_external_blockers())
        self.assertEqual("working", engine.load_run()["status"])

        engine._block(
            summary="A material code decision is required.",
            evidence_path=self.run_dir / "logs" / "code.log",
            required_action="Revise the accepted design.",
            kind="code",
        )
        self.assertFalse(engine.resume_external_blockers())
        self.assertEqual("blocked", engine.load_run()["status"])

    def test_explicit_validation_evidence_retry_clears_only_coverage_blocker(
        self,
    ) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        engine.phase_plan()
        review_hash = engine.load_run()["plan_review"]["review_sha256"]
        engine.apply_plan_decision(
            {
                "decision": "approve",
                "review_sha256": review_hash,
                "text": "I approve all plans in this exact complete review bundle.",
            }
        )
        engine._set_phase("validate")
        engine._block(
            summary=(
                "Validation for api did not cover the current tree and planned checks."
            ),
            evidence_path=self.run_dir / "run.json",
            required_action="Correct the validation evidence before resuming.",
            kind="code",
            repo_id="api",
        )

        self.assertTrue(engine.retry_validation_evidence())
        run = engine.load_run()
        self.assertEqual("working", run["status"])
        self.assertEqual([], run["blockers"])
        self.assertEqual("pending", run["repositories"]["api"]["status"])

        engine._block(
            summary="A material code decision is required.",
            evidence_path=self.run_dir / "logs" / "code.log",
            required_action="Revise the accepted design.",
            kind="code",
        )
        self.assertFalse(engine.retry_validation_evidence())
        self.assertEqual("blocked", engine.load_run()["status"])

    def test_crash_recovery_closes_a_worker_that_already_wrote_its_output(self) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        run = engine.load_run()
        assignment_path = engine.build_assignment(
            stage="plan",
            repo_id="api",
            scope="crash-recovery",
            inputs=[Path(run["request_path"]), Path(run["requirements_path"])],
            instructions=["Produce a repository plan."],
        )
        engine._install_actions([assignment_path])
        working = engine.load_run()
        working["next_actions"][0]["status"] = "working"
        engine._save_run(working)
        fake(
            [assignment_path],
            run_dir=self.run_dir,
            worker_runtime="pi",
            allow_existing=False,
        )

        command_log = self.root / "crash-recovery-herdr.jsonl"
        fake_herdr = self.root / "fake-crash-recovery-herdr.py"
        fake_herdr.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            f"log = pathlib.Path({str(command_log)!r})\n"
            "with log.open('a', encoding='utf-8') as handle:\n"
            "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:3] in (['agent', 'get'], ['agent', 'wait']):\n"
            "    print(json.dumps({'result': {'agent': {\n"
            "        'terminal_id': 'term-recovered', 'pane_id': 'pane-recovered'\n"
            "    }}}))\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        fake_herdr.chmod(0o755)

        with mock.patch.dict(
            "os.environ", {"E2E_HERDR_BINARY": str(fake_herdr)}
        ):
            engine.reconcile()

        commands = (
            [json.loads(line) for line in command_log.read_text().splitlines()]
            if command_log.exists()
            else []
        )
        self.assertIn(["pane", "close", "pane-recovered"], commands)
        self.assertNotIn(["pane", "close", "term-recovered"], commands)
        recovered_agent = engine.load_agents()["agents"][0]
        self.assertEqual("herdr", recovered_agent["backend"])
        self.assertEqual("complete", recovered_agent["cleanup_status"])
        self.assertNotIn("pane_id", recovered_agent)

    def test_reconcile_recovers_completed_plan_without_relaunching_worker(self) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        assignment = engine._schedule_plans(engine.load_run())[0]
        engine._install_actions([assignment])
        fake(
            [assignment],
            run_dir=self.run_dir,
            worker_runtime="pi",
            allow_existing=False,
        )

        engine.reconcile()

        recovered = engine.load_run()
        self.assertEqual([], recovered["next_actions"])
        self.assertEqual(
            json.loads(assignment.read_text(encoding="utf-8"))["output_artifact"],
            recovered["repositories"]["api"]["plan_path"],
        )
        self.assertEqual("plan-review", engine.phase_plan())
        self.assertEqual(1, len(fake.assignments))

    def test_mixed_recovery_batch_allows_existing_and_missing_outputs(self) -> None:
        capture = CaptureRejectingBatch()
        engine = self.initialize(capture)
        run = engine.load_run()
        inputs = [Path(run["request_path"]), Path(run["requirements_path"])]
        assignments = [
            engine.build_assignment(
                stage="plan",
                repo_id="api",
                scope=scope,
                inputs=inputs,
                instructions=["Produce a repository plan."],
            )
            for scope in ("recovery-one", "recovery-two")
        ]
        first_output = Path(
            json.loads(assignments[0].read_text(encoding="utf-8"))["output_artifact"]
        )
        first_output.write_text("{invalid", encoding="utf-8")

        result = engine._execute_assignments(assignments)

        self.assertTrue(capture.allow_existing)
        self.assertEqual(2, len(result.rejected))

    def test_one_missing_worker_output_is_replaced_once(self) -> None:
        fake = RejectFirstPlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()

        outcome = engine.phase_plan()

        self.assertEqual("plan-review", outcome)
        self.assertEqual(
            [1, 2], [assignment["attempt"] for assignment in fake.assignments]
        )
        agents = engine.load_agents()["agents"]
        self.assertEqual(["failed", "closed"], [agent["status"] for agent in agents])
        self.assertIn("-attempt-2.json", fake.assignments[-1]["output_artifact"])

    def test_planning_discovery_escalates_and_hash_pins_the_replanned_full_plan(
        self,
    ) -> None:
        fake = FakeSuccessfulBatch(risk_flags=["security"])
        engine = self.initialize(fake)
        engine.phase_bootstrap()

        outcome = engine.phase_plan()

        run = engine.load_run()
        self.assertEqual("contract", outcome)
        self.assertEqual("full", run["profile"])
        self.assertEqual(["security"], run["risk_flags"])
        self.assertTrue(run["workflow_policy"]["contract_required"])
        self.assertIsNone(run["repositories"]["api"]["plan_path"])
        escalation = run["profile_escalation"]
        self.assertTrue(Path(escalation["path"]).is_file())
        self.assertIn("api", run["pending_plan_revisions"])

        self.assertEqual("plan", engine.phase_contract())
        self.assertEqual("plan", engine.phase_plan())
        self.assertEqual("plan-review", engine.phase_plan())
        final_run = engine.load_run()
        revised_plan = json.loads(
            Path(final_run["repositories"]["api"]["plan_path"]).read_text()
        )
        self.assertEqual(2, revised_plan["revision"])
        self.assertEqual("profile-escalation", revised_plan["revision_basis"]["kind"])
        self.assertEqual(
            escalation["sha256"], revised_plan["revision_basis"]["artifact"]["sha256"]
        )

    def test_generic_continue_does_not_cross_plan_review_gate(self) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        engine.phase_plan()
        review_hash = engine.load_run()["plan_review"]["review_sha256"]

        with self.assertRaisesRegex(WorkflowError, "generic continuation"):
            engine.apply_plan_decision(
                {
                    "decision": "approve",
                    "review_sha256": review_hash,
                    "text": "continue",
                }
            )
        for qualified_text in (
            "I do not approve all plans in this bundle.",
            "I approve all plans except api.",
        ):
            with self.assertRaisesRegex(WorkflowError, "affirmatively approve"):
                engine.apply_plan_decision(
                    {
                        "decision": "approve",
                        "review_sha256": review_hash,
                        "text": qualified_text,
                    }
                )
        run = engine.load_run()
        self.assertEqual("awaiting-user", run["status"])
        self.assertEqual("pending", run["plan_review"]["status"])

    def test_requested_changes_create_a_hash_pinned_plan_revision_and_new_bundle(
        self,
    ) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        engine.phase_plan()
        first_review = engine.load_run()["plan_review"]

        engine.apply_plan_decision(
            {
                "decision": "changes",
                "review_sha256": first_review["review_sha256"],
                "text": "Keep the behavior local to the existing module.",
                "repository_ids": ["api"],
            }
        )
        engine.phase_plan()

        run = engine.load_run()
        revised_plan = json.loads(
            Path(run["repositories"]["api"]["plan_path"]).read_text()
        )
        self.assertEqual(2, revised_plan["revision"])
        self.assertEqual("user-feedback", revised_plan["revision_basis"]["kind"])
        self.assertNotEqual(
            first_review["review_sha256"], run["plan_review"]["review_sha256"]
        )
        self.assertEqual("awaiting-user", run["status"])

    def test_validation_assignment_propagates_planned_validation_ids(self) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        engine.phase_plan()

        from workflow_tools import worktree_fingerprint

        fingerprint = worktree_fingerprint(self.worktree)
        legacy_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
        legacy_path = engine.build_assignment(
            stage="validate",
            repo_id="api",
            scope=f"post-implementation-{legacy_hash}",
            instructions=["Run the planned checks."],
            validation_commands=engine._plan_commands("api"),
        )
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual([], legacy["validation_ids"])

        assignment_path = engine._validation_assignment("api", "post-implementation")
        assignment = json.loads(assignment_path.read_text(encoding="utf-8"))

        self.assertNotEqual(legacy_path, assignment_path)
        self.assertEqual(["API-VAL-001"], assignment["validation_ids"])
        self.assertEqual(["python -m unittest"], assignment["validation_commands"])

    def test_review_assignment_uses_unambiguous_completion_and_status_evidence(
        self,
    ) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        engine.phase_plan()

        assignment_path = engine._review_assignment("api", 1, [])
        assignment = json.loads(assignment_path.read_text(encoding="utf-8"))

        self.assertIn("round-1-evidence-v1", assignment["action_id"])
        self.assertIn(
            "A finished review has status complete even when it reports must-fix findings; use blocked only when the review itself cannot finish.",
            assignment["instructions"],
        )
        self.assertIn(
            "Write reviewed_status_path as the exact final git status --short output with no commentary.",
            assignment["instructions"],
        )

    def test_failed_validation_runs_one_batched_fix_then_revalidates(self) -> None:
        fake = FakeSuccessfulBatch(fail_first_validation=True)
        engine = self.initialize(fake)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 150,
        }
        interrupted = graph.invoke({"run_dir": str(self.run_dir)}, config=config)
        review_hash = interrupted["__interrupt__"][0].value["review_sha256"]

        graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "review_sha256": review_hash,
                    "text": "I approve all plans in this exact complete review bundle.",
                }
            ),
            config=config,
        )

        self.assertEqual("complete", engine.load_run()["status"])
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertEqual(1, stages.count("validation-fix"))
        self.assertEqual(3, stages.count("validate"))
        fixes = engine._artifacts(repo_id="api", stage="validation-fix", kind="result")
        self.assertEqual(["API-VAL-001"], fixes[-1][2]["validation_ids"])

    def test_high_review_finding_runs_one_fix_batch_and_targeted_second_review(
        self,
    ) -> None:
        fake = FakeSuccessfulBatch(round_one_finding=True)
        engine = self.initialize(fake)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 150,
        }
        interrupted = graph.invoke({"run_dir": str(self.run_dir)}, config=config)
        review_hash = interrupted["__interrupt__"][0].value["review_sha256"]

        graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "review_sha256": review_hash,
                    "text": "I approve all plans in this exact complete review bundle.",
                }
            ),
            config=config,
        )

        self.assertEqual("complete", engine.load_run()["status"])
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertIn("fix-1", stages)
        self.assertIn("review-2", stages)
        self.assertNotIn("fix-2", stages)
        fix_artifacts = engine._artifacts(repo_id="api", stage="fix-1", kind="result")
        self.assertEqual(["API-R1-001"], fix_artifacts[-1][2]["finding_ids"])
        second_review = engine._latest_review("api", 2)
        assert second_review is not None
        self.assertEqual(["API-R1-001"], second_review[1]["verified_finding_ids"])
        self.assertEqual([], second_review[1]["findings"])

    def test_full_profile_graph_runs_contract_challenge_integration_and_report(
        self,
    ) -> None:
        self.write_spec(profile="full")
        fake = FakeSuccessfulBatch()
        full_run = self.root / "run-full-complete"
        engine = WorkflowEngine.initialize(
            spec_path=self.spec,
            run_dir=full_run,
            skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.codebase_design_dir,
            batch_runner=fake,
            report_root=self.root / "reports",
            now=self.now,
        )
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 150,
        }
        interrupted = graph.invoke({"run_dir": str(full_run)}, config=config)
        review_hash = interrupted["__interrupt__"][0].value["review_sha256"]

        graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "review_sha256": review_hash,
                    "text": "I approve all plans in this exact complete review bundle.",
                }
            ),
            config=config,
        )

        run = engine.load_run()
        self.assertEqual("complete", run["status"])
        self.assertIsNotNone(run["contract_path"])
        self.assertTrue(run["workflow_policy"]["integration_required"])
        self.assertTrue(run["workflow_policy"]["report_required"])
        self.assertEqual(1, len(engine._artifacts(kind="integration")))
        reports = engine._artifacts(kind="report")
        self.assertEqual(1, len(reports))
        self.assertTrue(Path(reports[0][1]["html_path"]).is_file())
        self.assertEqual(
            [
                "contract",
                "plan",
                "design-challenge",
                "implement",
                "validate",
                "review-1",
                "integrate",
                "deliver",
                "validate",
            ],
            [assignment["stage"] for assignment in fake.assignments],
        )

    def test_migration_capable_validation_waits_for_isolated_database_evidence(
        self,
    ) -> None:
        self.write_spec(profile="full")
        fake = FakeSuccessfulBatch(migration_capable=True)
        full_run = self.root / "run-migration-gate"
        engine = WorkflowEngine.initialize(
            spec_path=self.spec,
            run_dir=full_run,
            skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.codebase_design_dir,
            batch_runner=fake,
            report_root=self.root / "reports",
            now=self.now,
        )
        checkpointer = InMemorySaver()
        graph = build_graph(engine, checkpointer)
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 150,
        }
        interrupted = graph.invoke({"run_dir": str(full_run)}, config=config)
        review_hash = interrupted["__interrupt__"][0].value["review_sha256"]

        graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "review_sha256": review_hash,
                    "text": "I approve all plans in this exact complete review bundle.",
                }
            ),
            config=config,
        )
        blocked = engine.load_run()
        self.assertEqual("blocked", blocked["status"])
        self.assertIn("database target", blocked["blockers"][0]["summary"].lower())
        self.assertNotIn(
            "validate", [assignment["stage"] for assignment in fake.assignments]
        )

        with self.assertRaisesRegex(WorkflowError, "URL or credential"):
            engine.record_database_target(
                repo_id="api",
                classification="isolated-test",
                description="scheme://redacted-target",
            )
        evidence = engine.record_database_target(
            repo_id="api",
            classification="isolated-test",
            description="Ephemeral database dedicated to this test worktree",
        )
        self.assertNotIn("database_url", evidence.read_text(encoding="utf-8").lower())
        graph.invoke(
            {
                "run_dir": str(full_run),
                "attempt_baseline": len(engine.load_agents()["agents"]),
            },
            config=config,
        )
        self.assertEqual("complete", engine.load_run()["status"])

    def test_full_profile_is_valid_before_contract_worker_runs(self) -> None:
        self.write_spec(profile="full", risks=["database-migration"])
        full_run = self.root / "run-full"
        engine = WorkflowEngine.initialize(
            spec_path=self.spec,
            run_dir=full_run,
            skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.codebase_design_dir,
            now=self.now,
        )
        run = engine.load_run()
        self.assertEqual("full", run["profile"])
        self.assertEqual("bootstrap", run["phase"])
        self.assertIsNone(run["contract_path"])

    def test_low_risk_graph_completes_after_explicit_approval(self) -> None:
        fake = FakeSuccessfulBatch()
        engine = self.initialize(fake)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 100,
        }
        interrupted = graph.invoke({"run_dir": str(self.run_dir)}, config=config)
        review_hash = interrupted["__interrupt__"][0].value["review_sha256"]

        graph.invoke(
            Command(
                resume={
                    "decision": "approve",
                    "review_sha256": review_hash,
                    "text": "I approve all plans in this exact complete review bundle.",
                }
            ),
            config=config,
        )

        run = engine.load_run()
        self.assertEqual("complete", run["status"])
        self.assertEqual("complete", run["phase"])
        self.assertTrue((self.run_dir / "metrics.json").is_file())
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertEqual(
            ["plan", "implement", "validate", "review-1", "deliver", "validate"],
            stages,
        )
        deliveries = engine._artifacts(repo_id="api", stage="deliver", kind="delivery")
        self.assertEqual("https://example.test/pull/1", deliveries[-1][1]["pr_url"])
        (self.worktree / "uncommitted-after-delivery.txt").write_text(
            "not delivered\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "task changes may be missing from the delivered commits",
        ):
            engine._validate_worker_output(deliveries[-1][2], deliveries[-1][0])

    def test_cli_persists_plan_interrupt_in_sqlite(self) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        engine.phase_plan()

        process = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "orchestrator.py"),
                "run",
                str(self.run_dir),
                "--worker-runtime",
                "pi",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, process.returncode, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual("awaiting-user", output["status"])
        self.assertEqual("plan-review", output["phase"])
        self.assertEqual(
            engine.load_run()["plan_review"]["review_sha256"],
            output["interrupts"][0]["review_sha256"],
        )
        self.assertTrue((self.run_dir / "langgraph.sqlite").is_file())

        resumed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "orchestrator.py"),
                "resume",
                str(self.run_dir),
                "--worker-runtime",
                "pi",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, resumed.returncode, resumed.stderr)
        resumed_output = json.loads(resumed.stdout)
        self.assertEqual("awaiting-user", resumed_output["status"])
        self.assertEqual(
            output["plan_review"]["sha256"],
            resumed_output["interrupts"][0]["review_sha256"],
        )

    def test_mermaid_exposes_each_policy_phase_and_approval_node(self) -> None:
        engine = self.initialize()
        graph = build_graph(engine, InMemorySaver())
        mermaid = graph.get_graph().draw_mermaid()
        for node in (
            "bootstrap",
            "contract",
            "plan",
            "plan_review",
            "implement",
            "validate",
            "review_1",
            "fix_1",
            "review_2",
            "fix_2",
            "integrate",
            "deliver",
            "report",
            "complete",
        ):
            self.assertIn(node, mermaid)


if __name__ == "__main__":
    unittest.main()
