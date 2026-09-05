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
import workflow_tools  # noqa: E402
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
                    "design_challenge_required": bool(
                        set(self.risk_flags) & artifact_guard.HIGH_RISK_FLAGS
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
        always_fail_validation: bool = False,
        delivery_code_failures: int = 0,
        migration_capable: bool = False,
        risk_flags: list[str] | None = None,
    ) -> None:
        super().__init__(
            migration_capable=migration_capable,
            risk_flags=risk_flags,
        )
        self.round_one_finding = round_one_finding
        self.fail_first_validation = fail_first_validation
        self.always_fail_validation = always_fail_validation
        self.delivery_code_failures = delivery_code_failures
        self.validation_attempts = 0
        self.delivery_attempts = 0

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
                fingerprint = self._fingerprint(worktree)
                should_fail = self.always_fail_validation or (
                    self.fail_first_validation and self.validation_attempts == 0
                )
                self.validation_attempts += 1
                records = []
                for index, (validation_id, command) in enumerate(
                    zip(
                        assignment["validation_ids"],
                        assignment["validation_commands"],
                        strict=True,
                    ),
                    start=1,
                ):
                    evidence = log_dir / f"implementation-{index}.log"
                    evidence.write_text("fail\n" if should_fail else "pass\n", encoding="utf-8")
                    records.append(
                        {
                            "id": validation_id,
                            "command": command,
                            "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                            "cwd": str(worktree),
                            "tree_fingerprint": fingerprint,
                            "cache_status": "fresh",
                            "source_artifact": None,
                            "exit_code": 1 if should_fail else 0,
                            "result": "fail" if should_fail else "pass",
                            "summary": (
                                "Validation failed."
                                if should_fail
                                else "Validation passed."
                            ),
                            "log_path": str(evidence),
                        }
                    )
                artifact.update(
                    {
                        "summary": "Implemented the approved packet.",
                        "changed_files": ["feature.txt"],
                        "tree_fingerprint": fingerprint,
                        "validations": records,
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
                should_fail = self.always_fail_validation or (
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
                fingerprint = self._fingerprint(worktree)
                records = []
                for index, (validation_id, command) in enumerate(
                    zip(
                        assignment["validation_ids"],
                        assignment["validation_commands"],
                        strict=True,
                    ),
                    start=1,
                ):
                    evidence = log_dir / f"{assignment['stage']}-{index}.log"
                    evidence.write_text("pass\n", encoding="utf-8")
                    records.append(
                        {
                            "id": validation_id,
                            "command": command,
                            "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                            "cwd": str(worktree),
                            "tree_fingerprint": fingerprint,
                            "cache_status": "fresh",
                            "source_artifact": None,
                            "exit_code": 0,
                            "result": "pass",
                            "summary": "Validation passed.",
                            "log_path": str(evidence),
                        }
                    )
                artifact.update(
                    {
                        "summary": "Resolved every assigned finding.",
                        "changed_files": ["feature.txt"],
                        "tree_fingerprint": fingerprint,
                        "validations": records,
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
            elif assignment["stage"] == "pipeline-fix":
                (worktree / "feature.txt").write_text(
                    "implemented after pipeline fix\n", encoding="utf-8"
                )
                status_path.write_text(
                    self._git(worktree, "status", "--short") + "\n",
                    encoding="utf-8",
                )
                fingerprint = self._fingerprint(worktree)
                records = []
                for index, (validation_id, command) in enumerate(
                    zip(
                        assignment["validation_ids"],
                        assignment["validation_commands"],
                        strict=True,
                    ),
                    start=1,
                ):
                    evidence = log_dir / f"pipeline-fix-{index}.log"
                    evidence.write_text("pass\n", encoding="utf-8")
                    records.append(
                        {
                            "id": validation_id,
                            "command": command,
                            "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                            "cwd": str(worktree),
                            "tree_fingerprint": fingerprint,
                            "cache_status": "fresh",
                            "source_artifact": None,
                            "exit_code": 0,
                            "result": "pass",
                            "summary": "Validation passed.",
                            "log_path": str(evidence),
                        }
                    )
                artifact.update(
                    {
                        "summary": "Resolved the change-related pipeline failure.",
                        "changed_files": ["feature.txt"],
                        "tree_fingerprint": fingerprint,
                        "validations": records,
                        "decisions": [
                            {
                                "id": "DEC-PIPELINE-FIX-001",
                                "kind": "pipeline",
                                "summary": "Corrected the required-check failure.",
                                "evidence": "feature.txt",
                            }
                        ],
                        "resolutions": [],
                        "git": {
                            "head": self._git(worktree, "rev-parse", "HEAD"),
                            "status_short_path": str(status_path),
                        },
                        "next_action": "deliver",
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
                self.delivery_attempts += 1
                self._git(worktree, "add", "feature.txt")
                if self._git(worktree, "status", "--short"):
                    self._git(
                        worktree, "commit", "-m", "feat: implement requested behavior"
                    )
                commit = self._git(worktree, "rev-parse", "HEAD")
                check_log = log_dir / f"required-check-{self.delivery_attempts}.log"
                check_failed = self.delivery_attempts <= self.delivery_code_failures
                check_log.write_text(
                    "failed\n" if check_failed else "passed\n", encoding="utf-8"
                )
                artifact.update(
                    {
                        "status": "blocked" if check_failed else "complete",
                        "branch": self._git(worktree, "branch", "--show-current"),
                        "base_branch": json.loads((run_dir / "run.json").read_text())["repositories"][assignment["repo_id"]]["base_branch"],
                        "commits": [commit],
                        "pr_url": "https://example.test/pull/1",
                        "checks": [
                            {
                                "name": "tests",
                                "url": "https://example.test/check/1",
                                "required": True,
                                "state": "failed" if check_failed else "passed",
                                "evidence_path": str(check_log),
                            }
                        ],
                        "blockers": (
                            [
                                {
                                    "id": f"BLOCK-PIPELINE-{self.delivery_attempts:03d}",
                                    "kind": "code",
                                    "summary": "A required check failed.",
                                    "evidence_path": str(check_log),
                                    "required_action": "Correct the change and rerun delivery.",
                                }
                            ]
                            if check_failed
                            else []
                        ),
                    }
                )
                if assignment.get("delivery_evidence_version") == 2:
                    artifact.update(
                        head_sha=commit, pushed_head_sha=commit, checked_head_sha=commit if not check_failed else None,
                        check_policy={"status": "required", "required_checks": [{"name": "tests", "app_id": None}],
                                      "evidence": [{"path": str(check_log), "sha256": hashlib.sha256(check_log.read_bytes()).hexdigest()}]},
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


class MissingBlockerKindBatch(FakeSuccessfulBatch):
    """Reproduce a settled writer whose only invalid field is blocker.kind."""

    def __init__(self, *, repair_change: str | None = None) -> None:
        super().__init__()
        self.repair_change = repair_change
        self.source_writes = 0
        self.repairs = 0

    def __call__(self, assignment_paths: list[Path], **kwargs: Any) -> tuple[int, dict[str, Any]]:
        assignment = json.loads(assignment_paths[0].read_text())
        if assignment.get("execution_mode") == "artifact-repair":
            self.assignments.append(assignment)
            self.repairs += 1
            original = Path(assignment["repair_of"]["artifact"]["path"])
            artifact = json.loads(original.read_text())
            artifact["assignment_path"] = str(assignment_paths[0])
            artifact["assignment_sha256"] = hashlib.sha256(assignment_paths[0].read_bytes()).hexdigest()
            artifact["blockers"][0]["kind"] = "environment"
            if self.repair_change == "status":
                artifact["status"] = "complete"
                artifact["blockers"] = []
            elif self.repair_change == "source":
                (Path(assignment["cwd"]) / "feature.txt").write_text("unauthorized repair\n")
            elif self.repair_change in {"invalid", "crash-after-invalid"}:
                del artifact["blockers"][0]["kind"]
            elif self.repair_change == "evidence":
                Path(artifact["blockers"][0]["evidence_path"]).write_text("changed evidence\n")
            elif self.repair_change == "index":
                self._git(Path(assignment["cwd"]), "add", "feature.txt")
            elif self.repair_change == "head":
                self._git(Path(assignment["cwd"]), "commit", "--allow-empty", "-qm", "unauthorized repair")
            elif self.repair_change == "branch":
                self._git(Path(assignment["cwd"]), "branch", "-m", "unauthorized-repair")
            output = Path(assignment["output_artifact"])
            output.write_text(json.dumps(artifact) + "\n")
            if self.repair_change in {"crash-after-output", "crash-after-invalid", "crash-without-output"}:
                if self.repair_change == "crash-without-output":
                    output.unlink()
                self.repair_change = None
                raise KeyboardInterrupt("simulated coordinator interruption")
            return 0, {"workers": [{
                "action_id": assignment["action_id"],
                "agent_name": f"repair-{self.repairs}",
                "status": "accepted", "cleanup_status": "complete",
                "started_at": "2026-08-22T10:00:00Z",
                "ended_at": "2026-08-22T10:01:00Z",
            }]}
        code, manifest = super().__call__(assignment_paths, **kwargs)
        if assignment["stage"] == "implement":
            self.source_writes += 1
            output = Path(assignment["output_artifact"])
            artifact = json.loads(output.read_text())
            evidence = Path(assignment["log_dir"]) / "environment.log"
            evidence.write_text("The isolated test service is unavailable.\n")
            artifact.update(status="blocked", blockers=[{
                "id": "BLOCK-001",
                "summary": "The isolated test service is unavailable.",
                "evidence_path": str(evidence),
                "required_action": "Restore the isolated test service, then resume.",
            }])
            if self.repair_change == "missing-evidence":
                evidence.unlink()
            elif self.repair_change == "contradictory":
                artifact["status"] = "complete"
            output.write_text(json.dumps(artifact) + "\n")
            if self.repair_change == "crash-after-writer":
                self.repair_change = None
                raise KeyboardInterrupt("writer settled before its rejection was recorded")
        return code, manifest


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
        self,
        *,
        profile: str = "standard",
        risks: list[str] | None = None,
        report_requested: bool = False,
    ) -> None:
        value = {
            "run_id": "20260822T100000Z-langgraph-test",
            "request": "Implement the requested behavior.",
            "profile": profile,
            "risk_flags": risks or [],
            "report_requested": report_requested,
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

    def initialize(
        self,
        fake: FakePlanningBatch | None = None,
        *,
        profile: str = "standard",
        risks: list[str] | None = None,
        report_requested: bool = False,
    ) -> WorkflowEngine:
        self.write_spec(
            profile=profile,
            risks=risks,
            report_requested=report_requested,
        )
        return WorkflowEngine.initialize(
            spec_path=self.spec,
            run_dir=self.run_dir,
            skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.codebase_design_dir,
            batch_runner=fake or FakePlanningBatch(),
            report_root=self.root / "reports",
            now=self.now,
        )

    def test_engine_normalizes_assignment_metadata_from_its_own_intent(self) -> None:
        batch = FakeSuccessfulBatch()
        def stale_metadata(paths: list[Path], **kwargs: Any) -> tuple[int, dict[str, Any]]:
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                output = Path(json.loads(path.read_text())["output_artifact"])
                artifact = json.loads(output.read_text())
                artifact["assignment_path"] = str(self.root / "nonexistent-assignment.json")
                output.write_text(json.dumps(artifact))
            return code, manifest
        engine = self.initialize(stale_metadata)
        build_graph(engine, InMemorySaver()).invoke(
            {"run_dir": str(self.run_dir)},
            {"configurable": {"thread_id": "assignment-metadata"}, "recursion_limit": 150},
        )
        self.assertEqual("complete", engine.load_run()["status"])
        self.assertEqual(["plan", "implement", "review-1", "deliver"], [a["stage"] for a in batch.assignments])

    def blocked_long_handoff(self):
        batch = FakeSuccessfulBatch()
        def long_handoff(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment["stage"] == "implement":
                    output = Path(assignment["output_artifact"])
                    artifact = json.loads(output.read_text())
                    artifact["next_action"] = "Proceed to independent review. " * 15
                    output.write_text(json.dumps(artifact, indent=2) + "\n")
                    worker = next(w for w in manifest["workers"] if w["action_id"] == assignment["action_id"])
                    worker.update(status="rejected", cleanup_status="complete", error_code="invalid-evidence",
                                  error_path="$.next_action", reason="$.next_action: must be at most 300 characters")
            return code, manifest
        engine = self.initialize(long_handoff)
        graph = build_graph(engine, InMemorySaver())
        config = {"configurable": {"thread_id": "long-handoff"}, "recursion_limit": 150}
        graph.invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("blocked", engine.load_run()["status"])
        self.assertIn("$.next_action", engine.load_run()["blockers"][0]["summary"])
        assignment = next(a for a in batch.assignments if a["stage"] == "implement")
        output = Path(assignment["output_artifact"])
        return engine, batch, graph, config, output

    def test_handoff_metadata_recovery_preserves_evidence_and_does_not_replay_source(self):
        engine, batch, graph, config, output = self.blocked_long_handoff()
        original = output.read_bytes()
        fingerprint = workflow_tools.worktree_fingerprint(self.worktree)
        before = engine.load_run()
        receipt = engine.repair_handoff_metadata(hashlib.sha256(original).hexdigest())
        recovered = json.loads(output.read_text())
        expected = json.loads(original)
        expected["next_action"] = None
        self.assertEqual(expected, recovered)
        self.assertEqual(original, Path(receipt["original"]["path"]).read_bytes())
        self.assertEqual(before["plan_review"], engine.load_run()["plan_review"])
        self.assertEqual(before["retry_limits"], engine.load_run()["retry_limits"])
        self.assertEqual(fingerprint, workflow_tools.worktree_fingerprint(self.worktree))
        self.assertEqual("working", engine.load_run()["status"])
        with self.assertRaises(WorkflowError):
            engine.repair_handoff_metadata(hashlib.sha256(original).hexdigest())
        graph.invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("complete", engine.load_run()["status"])
        self.assertEqual(["plan", "implement", "review-1", "deliver"], [a["stage"] for a in batch.assignments])

    def test_handoff_metadata_recovery_rejects_changed_content(self):
        engine, _, _, _, output = self.blocked_long_handoff()
        original = output.read_bytes()
        (self.worktree / "feature.txt").write_text("unvalidated change\n")
        with self.assertRaisesRegex(WorkflowError, "content|worktree"):
            engine.repair_handoff_metadata(hashlib.sha256(original).hexdigest())
        self.assertEqual(original, output.read_bytes())
        self.assertEqual("blocked", engine.load_run()["status"])

    def test_handoff_metadata_recovery_rejects_unpinned_or_other_invalid_evidence(self):
        engine, _, _, _, output = self.blocked_long_handoff()
        original = output.read_bytes()
        with self.assertRaises(WorkflowError):
            engine.repair_handoff_metadata("0" * 64)
        artifact = json.loads(original)
        artifact["summary"] = ""
        output.write_text(json.dumps(artifact))
        with self.assertRaises((WorkflowError, artifact_guard.ValidationError)):
            engine.repair_handoff_metadata(hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual("blocked", engine.load_run()["status"])

    def test_handoff_metadata_recovery_finishes_after_publication_crash(self):
        engine, _, _, _, output = self.blocked_long_handoff()
        original = output.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with mock.patch.object(engine, "_save_run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.repair_handoff_metadata(digest)
        self.assertIsNone(json.loads(output.read_text())["next_action"])
        self.assertEqual("blocked", engine.load_run()["status"])
        receipt = engine.repair_handoff_metadata(digest)
        self.assertEqual(original, Path(receipt["original"]["path"]).read_bytes())
        self.assertEqual("working", engine.load_run()["status"])

    def test_handoff_metadata_recovery_refuses_uncleaned_workers(self):
        engine, _, _, _, output = self.blocked_long_handoff()
        original = output.read_bytes()
        agents = engine.load_agents()
        agents["agents"][-1]["cleanup_status"] = "retained"
        engine._save_agents(agents)
        with self.assertRaisesRegex(WorkflowError, "settled and cleaned"):
            engine.repair_handoff_metadata(hashlib.sha256(original).hexdigest())
        self.assertEqual(original, output.read_bytes())
        self.assertEqual("blocked", engine.load_run()["status"])

    def test_handoff_metadata_recovery_cannot_clear_a_failed_check(self):
        engine, _, _, _, output = self.blocked_long_handoff()
        artifact = json.loads(output.read_text())
        artifact["validations"][0].update(result="fail", exit_code=1)
        output.write_text(json.dumps(artifact))
        original = output.read_bytes()
        with self.assertRaises((WorkflowError, artifact_guard.ValidationError)):
            engine.repair_handoff_metadata(hashlib.sha256(original).hexdigest())
        self.assertEqual(original, output.read_bytes())
        self.assertEqual("blocked", engine.load_run()["status"])

    def test_handoff_metadata_recovery_rejects_changed_approval(self):
        engine, _, _, _, output = self.blocked_long_handoff()
        original = output.read_bytes()
        review = Path(engine.load_run()["plan_review"]["review_path"])
        review.write_text(review.read_text() + "changed\n")
        with self.assertRaises((WorkflowError, artifact_guard.ValidationError)):
            engine.repair_handoff_metadata(hashlib.sha256(original).hexdigest())
        self.assertEqual(original, output.read_bytes())
        self.assertEqual("blocked", engine.load_run(validate=False)["status"])

    def test_missing_blocker_kind_repairs_output_without_replaying_source(self) -> None:
        batch = MissingBlockerKindBatch()
        engine = self.initialize(batch)
        build_graph(engine, InMemorySaver()).invoke(
            {"run_dir": str(self.run_dir)},
            {"configurable": {"thread_id": "missing-kind"}, "recursion_limit": 150},
        )
        self.assertEqual(1, batch.source_writes)
        self.assertEqual(1, batch.repairs)
        self.assertEqual("implemented\n", (self.worktree / "feature.txt").read_text())
        run = engine.load_run()
        self.assertEqual("blocked", run["status"])
        self.assertEqual("environment", run["blockers"][0]["kind"])
        repair = next(a for a in batch.assignments if a.get("execution_mode") == "artifact-repair")
        self.assertEqual("none", repair["project_file_access"])
        self.assertEqual("none", repair["git_access"])
        self.assertEqual("none", repair["forge_access"])
        original = json.loads(Path(repair["repair_of"]["artifact"]["path"]).read_text())
        self.assertNotIn("kind", original["blockers"][0])

    def assert_repair_is_rejected(self, change: str) -> None:
        batch = MissingBlockerKindBatch(repair_change=change)
        engine = self.initialize(batch)
        graph = build_graph(engine, InMemorySaver())
        config = {"configurable": {"thread_id": "unsafe-repair"}, "recursion_limit": 150}
        graph.invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("blocked", engine.load_run()["status"])
        self.assertEqual("decision", engine.load_run()["blockers"][0]["kind"])
        self.assertEqual(1, batch.source_writes)
        self.assertEqual(1, batch.repairs)
        self.assertFalse(engine.resume_external_blockers())
        graph.invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual(1, batch.repairs)

    def test_repair_cannot_turn_blocked_work_into_success(self) -> None:
        self.assert_repair_is_rejected("status")

    def test_repair_cannot_change_project_content(self) -> None:
        self.assert_repair_is_rejected("source")

    def test_repair_cannot_change_the_git_index(self) -> None:
        self.assert_repair_is_rejected("index")

    def test_repair_cannot_change_referenced_evidence(self) -> None:
        self.assert_repair_is_rejected("evidence")

    def test_repair_cannot_change_head(self) -> None:
        self.assert_repair_is_rejected("head")

    def test_repair_cannot_rename_the_task_branch(self) -> None:
        self.assert_repair_is_rejected("branch")

    def test_ineligible_missing_kind_does_not_replay_source(self) -> None:
        for change in ("missing-evidence", "contradictory"):
            with self.subTest(change=change):
                self.run_dir = self.root / change
                (self.worktree / "feature.txt").unlink(missing_ok=True)
                batch = MissingBlockerKindBatch(repair_change=change)
                engine = self.initialize(batch)
                build_graph(engine, InMemorySaver()).invoke(
                    {"run_dir": str(self.run_dir)},
                    {"configurable": {"thread_id": change}, "recursion_limit": 150},
                )
                self.assertEqual("decision", engine.load_run()["blockers"][0]["kind"])
                self.assertEqual(1, batch.source_writes)
                self.assertEqual(0, batch.repairs)

    def test_invalid_repair_does_not_start_another_repair_or_source_writer(self) -> None:
        self.assert_repair_is_rejected("invalid")

    def test_repair_written_before_a_crash_is_recovered_without_relaunch(self) -> None:
        batch = MissingBlockerKindBatch(repair_change="crash-after-output")
        engine = self.initialize(batch)
        config = {"configurable": {"thread_id": "repair-crash"}, "recursion_limit": 150}
        with self.assertRaises(KeyboardInterrupt):
            build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual(1, batch.source_writes)
        self.assertEqual(1, batch.repairs)
        self.assertEqual("environment", engine.load_run()["blockers"][0]["kind"])

    def test_failed_repair_crash_never_relaunches_or_resets_its_attempt(self) -> None:
        for change in ("crash-after-invalid", "crash-without-output"):
            with self.subTest(change=change):
                self.run_dir = self.root / change
                batch = MissingBlockerKindBatch(repair_change=change)
                # The previous subcase's task file is only disposable fixture data.
                (self.worktree / "feature.txt").unlink(missing_ok=True)
                engine = self.initialize(batch)
                config = {"configurable": {"thread_id": change}, "recursion_limit": 150}
                with self.assertRaises(KeyboardInterrupt):
                    build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
                build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
                self.assertEqual(1, batch.source_writes)
                self.assertEqual(1, batch.repairs)
                self.assertEqual("decision", engine.load_run()["blockers"][0]["kind"])

    def test_malformed_writer_output_recovers_after_a_crash_without_source_replay(self) -> None:
        batch = MissingBlockerKindBatch(repair_change="crash-after-writer")
        engine = self.initialize(batch)
        config = {"configurable": {"thread_id": "writer-crash"}, "recursion_limit": 150}
        with self.assertRaises(KeyboardInterrupt):
            build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual(1, batch.source_writes)
        self.assertEqual(1, batch.repairs)
        self.assertEqual("environment", engine.load_run()["blockers"][0]["kind"])

    def test_external_resume_after_valid_repair_preserves_original_evidence(self) -> None:
        batch = MissingBlockerKindBatch()
        engine = self.initialize(batch)
        config = {"configurable": {"thread_id": "external-repair-resume"}, "recursion_limit": 150}
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        repair = next(a for a in batch.assignments if a.get("execution_mode") == "artifact-repair")
        original = repair["repair_of"]["artifact"]
        self.assertTrue(engine.resume_external_blockers())
        replacement = FakeSuccessfulBatch()
        engine.batch_runner = replacement
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("complete", engine.load_run()["status"])
        writer = next(a for a in replacement.assignments if a["stage"] == "implement")
        original_assignment = json.loads(Path(repair["repair_of"]["assignment"]["path"]).read_text())
        self.assertNotEqual(original_assignment["action_id"], writer["action_id"])
        self.assertNotEqual(original["path"], writer["output_artifact"])
        self.assertEqual(original["sha256"], hashlib.sha256(Path(original["path"]).read_bytes()).hexdigest())

    def test_legacy_runs_keep_their_original_replacement_policy(self) -> None:
        batch = MissingBlockerKindBatch()
        engine = self.initialize(batch)
        run = engine.load_run()
        del run["retry_limits"]["artifact_repairs_per_action"]
        engine._save_run(run)
        build_graph(engine, InMemorySaver()).invoke(
            {"run_dir": str(self.run_dir)},
            {"configurable": {"thread_id": "legacy-rejection"}, "recursion_limit": 150},
        )
        self.assertEqual(2, batch.source_writes)
        self.assertEqual(0, batch.repairs)
        self.assertEqual("infrastructure", engine.load_run()["blockers"][0]["kind"])

    def test_new_runs_pin_reasoning_and_source_fixes_never_use_medium(self) -> None:
        import workflow_tools
        batch = FakeSuccessfulBatch(round_one_finding=True, fail_first_validation=True, delivery_code_failures=1)
        engine = self.initialize(batch)
        build_graph(engine, InMemorySaver()).invoke(
            {"run_dir": str(self.run_dir)},
            {"configurable": {"thread_id": "reasoning-policy"}, "recursion_limit": 150},
        )
        self.assertEqual("stage-v1", engine.load_run()["worker_reasoning_policy"])
        for stage in ("validation-fix", "pipeline-fix", "fix-1"):
            assignment = next(a for a in batch.assignments if a["stage"] == stage)
            self.assertEqual("high", assignment["thinking"])
            self.assertEqual("high", workflow_tools.effective_thinking(assignment, engine.load_run()))
        self.assertEqual("xhigh", workflow_tools.effective_thinking({"thinking": "medium"}, {}))
        self.assertEqual("high", workflow_tools.effective_thinking({"thinking": "high"}, {"worker_reasoning_policy": "stage-v1"}))

    def github_engine(self, batch: FakeSuccessfulBatch, *, state: str = "success", crash: str | None = None,
                      failures: int = 0) -> tuple[WorkflowEngine, Any]:
        from test_delivery_tools import FakeGitHub
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        FakeSuccessfulBatch._git(self.worktree, "remote", "add", "origin", "git@github.com:example/task.git")
        self.write_spec()
        spec = json.loads(self.spec.read_text())
        spec["repositories"][0]["delivery_check_timeout_seconds"] = 0
        self.spec.write_text(json.dumps(spec))
        forge = FakeGitHub(self.worktree)
        forge.check_state, forge.crash_after, forge.failures_remaining = state, crash, failures
        engine = WorkflowEngine.initialize(
            spec_path=self.spec, run_dir=self.run_dir, skill_dir=SCRIPTS_DIR.parent,
            codebase_design_dir=self.codebase_design_dir, batch_runner=batch,
            delivery_runner=forge, now=self.now,
        )
        return engine, forge

    def test_github_delivery_needs_no_delivery_or_duplicate_validation_worker(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch)
        build_graph(engine, InMemorySaver()).invoke(
            {"run_dir": str(self.run_dir)},
            {"configurable": {"thread_id": "command-delivery"}, "recursion_limit": 150},
        )
        self.assertEqual("complete", engine.load_run()["status"])
        self.assertEqual(["plan", "implement", "review-1"], [a["stage"] for a in batch.assignments])
        self.assertEqual(3, len(engine.load_agents()["agents"]))
        self.assertEqual(1, forge.create_count)
        metrics = json.loads((self.run_dir / "metrics.json").read_text())
        self.assertEqual(1, metrics["command_attempts"])

    def test_command_delivery_uses_one_pipeline_fix_then_reconciles_the_same_pr(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch, failures=1)
        build_graph(engine, InMemorySaver()).invoke(
            {"run_dir": str(self.run_dir)},
            {"configurable": {"thread_id": "command-fix"}, "recursion_limit": 150},
        )
        self.assertEqual("complete", engine.load_run()["status"])
        self.assertEqual(1, sum(a["stage"] == "pipeline-fix" for a in batch.assignments))
        self.assertEqual(1, forge.create_count)

    def test_pending_command_delivery_does_not_spend_a_code_fix(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, _ = self.github_engine(batch, state="pending")
        build_graph(engine, InMemorySaver()).invoke(
            {"run_dir": str(self.run_dir)},
            {"configurable": {"thread_id": "command-pending"}, "recursion_limit": 150},
        )
        self.assertEqual("blocked", engine.load_run()["status"])
        self.assertEqual("infrastructure", engine.load_run()["blockers"][0]["kind"])
        self.assertFalse(any(a["stage"] == "pipeline-fix" for a in batch.assignments))

    def assert_command_crash_recovers(self, crash: str) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch, crash=crash)
        config = {"configurable": {"thread_id": "command-crash"}, "recursion_limit": 150}
        with self.assertRaises(KeyboardInterrupt):
            build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        head = FakeSuccessfulBatch._git(self.worktree, "rev-parse", "HEAD")
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("complete", engine.load_run()["status"])
        self.assertEqual(head, FakeSuccessfulBatch._git(self.worktree, "rev-parse", "HEAD"))
        self.assertEqual(1, forge.create_count)
        self.assertEqual(3, len(engine.load_agents()["agents"]))

    def test_command_reconciles_a_commit_completed_before_interruption(self) -> None:
        self.assert_command_crash_recovers("commit")

    def test_command_reconciles_a_push_completed_before_interruption(self) -> None:
        self.assert_command_crash_recovers("push")

    def test_command_reconciles_a_pr_created_before_interruption(self) -> None:
        self.assert_command_crash_recovers("pr-create")

    def test_command_reconciles_checks_completed_before_interruption(self) -> None:
        self.assert_command_crash_recovers("checks")

    def test_delivery_artifact_recovery_refreshes_forge_evidence(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch)
        execute = engine._execute_delivery_command
        def crash_after_output(path: Path, **kwargs: Any) -> dict[str, Any]:
            execute(path, **kwargs)
            raise KeyboardInterrupt("delivery artifact persisted before acceptance")
        config = {"configurable": {"thread_id": "stale-delivery"}, "recursion_limit": 150}
        with mock.patch.object(engine, "_execute_delivery_command", side_effect=crash_after_output):
            with self.assertRaises(KeyboardInterrupt):
                build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        assignment = json.loads(Path(engine.load_run()["next_actions"][0]["assignment_path"]).read_text())
        previous = json.loads(Path(assignment["output_artifact"]).read_text())
        previous_evidence = previous["command_evidence"]
        forge.required.append({"context": "new-required", "app": None})
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("blocked", engine.load_run()["status"])
        self.assertEqual("infrastructure", engine.load_run()["blockers"][0]["kind"])
        self.assertEqual(previous_evidence["sha256"], hashlib.sha256(Path(previous_evidence["path"]).read_bytes()).hexdigest())
        self.assertEqual(1, forge.create_count)
        self.assertFalse(any(a["stage"] == "pipeline-fix" for a in batch.assignments))

    def test_crash_after_delivery_acceptance_still_refreshes_before_completion(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch)
        append = engine._append_event
        def crash_after_acceptance(event: str, **kwargs: Any) -> None:
            append(event, **kwargs)
            if event == "artifact-accepted" and kwargs.get("action_id", "").startswith("deliver:"):
                raise KeyboardInterrupt("delivery accepted before completion")
        config = {"configurable": {"thread_id": "accepted-delivery-crash"}, "recursion_limit": 150}
        with mock.patch.object(engine, "_append_event", side_effect=crash_after_acceptance):
            with self.assertRaises(KeyboardInterrupt):
                build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        old = engine._latest_delivery("api")
        old_hash = hashlib.sha256(old[0].read_bytes()).hexdigest()
        forge.required.append({"context": "new-required", "app": None})
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("blocked", engine.load_run()["status"])
        self.assertEqual(old_hash, hashlib.sha256(old[0].read_bytes()).hexdigest())
        self.assertEqual(1, forge.create_count)

    def test_checkpoint_replay_does_not_execute_after_recovery_blocks(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch)
        graph = build_graph(engine, InMemorySaver())
        config = {"configurable": {"thread_id": "blocked-checkpoint"}, "recursion_limit": 150}
        append = engine._append_event
        def crash(event: str, **kwargs: Any) -> None:
            append(event, **kwargs)
            if event == "artifact-accepted" and kwargs.get("action_id", "").startswith("deliver:"):
                raise KeyboardInterrupt("accepted delivery checkpoint")
        with mock.patch.object(engine, "_append_event", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                graph.invoke({"run_dir": str(self.run_dir)}, config)
        forge.check_state = "pending"
        engine.reconcile()  # Same explicit preflight as the durable CLI.
        self.assertEqual("blocked", engine.load_run()["status"])
        command_count = len(forge.commands)
        graph.invoke(None, config)
        self.assertEqual(command_count, len(forge.commands))
        self.assertEqual("blocked", engine.load_run()["status"])

    def test_completed_delivery_refresh_survives_other_pending_actions(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch)
        config = {"configurable": {"thread_id": "mixed-delivery-recovery"}, "recursion_limit": 150}
        append = engine._append_event
        def crash(event: str, **kwargs: Any) -> None:
            append(event, **kwargs)
            if event == "artifact-accepted" and kwargs.get("action_id", "").startswith("deliver:"):
                raise KeyboardInterrupt("accepted delivery before peers settled")
        with mock.patch.object(engine, "_append_event", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        # Any independently pending action must not erase the delivery refresh
        # obligation. A validation-only peer keeps this fixture source-neutral.
        peer = engine._validation_assignment("api", "independent-recovery-peer")
        engine._install_actions([peer])
        forge.required.append({"context": "new-required", "app": None})
        engine.reconcile()
        self.assertTrue(engine.load_run()["next_actions"])
        batch([peer], run_dir=self.run_dir, worker_runtime="pi", allow_existing=False)
        engine.reconcile(refresh_completed=False)
        self.assertEqual("blocked", engine.load_run()["status"])
        self.assertEqual("infrastructure", engine.load_run()["blockers"][0]["kind"])
        self.assertEqual(1, forge.create_count)

    def test_delivery_recovered_code_failure_keeps_its_pipeline_fix(self) -> None:
        batch = FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch, failures=1)
        execute = engine._execute_delivery_command
        def crash_after_output(path: Path, **kwargs: Any) -> dict[str, Any]:
            execute(path, **kwargs)
            raise KeyboardInterrupt("failed check artifact persisted before phase handling")
        config = {"configurable": {"thread_id": "recovered-code-failure"}, "recursion_limit": 150}
        with mock.patch.object(engine, "_execute_delivery_command", side_effect=crash_after_output):
            with self.assertRaises(KeyboardInterrupt):
                build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        build_graph(engine, InMemorySaver()).invoke({"run_dir": str(self.run_dir)}, config)
        self.assertEqual("complete", engine.load_run()["status"])
        self.assertEqual(1, sum(a["stage"] == "pipeline-fix" for a in batch.assignments))
        self.assertEqual(1, forge.create_count)

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

    def test_full_graph_interrupts_for_exact_plan_bundle(
        self,
    ) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake, profile="full")
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
        self.assertEqual("user", approved["plan_review"]["approval_source"])

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
        self.assertEqual("approved", engine.load_run()["plan_review"]["status"])
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

    def test_explicit_dependent_fix_retry_clears_only_contract_drift_blocker(
        self,
    ) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake)
        engine.phase_bootstrap()
        engine.phase_plan()
        self.assertEqual("approved", engine.load_run()["plan_review"]["status"])
        engine._set_phase("fix-1")
        evidence = self.run_dir / "logs" / "contract-drift.log"
        engine._block(
            summary=(
                "The current API worktree bundle is not the hash-pinned accepted "
                "bundle used by the UI generated types."
            ),
            evidence_path=evidence,
            required_action="Regenerate the dependent consumer.",
            kind="dependency",
            repo_id="api",
        )

        self.assertTrue(engine.retry_dependent_fixes())
        run = engine.load_run()
        self.assertEqual("working", run["status"])
        self.assertEqual([], run["blockers"])

        engine._block(
            summary="A package dependency decision is required.",
            evidence_path=self.run_dir / "logs" / "dependency.log",
            required_action="Revise the plan.",
            kind="dependency",
        )
        self.assertFalse(engine.retry_dependent_fixes())
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

        old_name = workflow_tools._legacy_agent_name(json.loads(assignment_path.read_text()))
        command_log = self.root / "crash-recovery-herdr.jsonl"
        fake_herdr = self.root / "fake-crash-recovery-herdr.py"
        fake_herdr.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            f"log = pathlib.Path({str(command_log)!r})\n"
            "with log.open('a', encoding='utf-8') as handle:\n"
            "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:3] in (['agent', 'get'], ['agent', 'wait']):\n"
            f"    if sys.argv[3] != {old_name!r}: sys.exit(1)\n"
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
        self.assertEqual(old_name, recovered_agent["name"])
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
        self.assertEqual("implement", engine.phase_plan())
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

        self.assertEqual("implement", outcome)
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
        self.assertEqual("plan", outcome)
        self.assertEqual("full", run["profile"])
        self.assertEqual(["security"], run["risk_flags"])
        self.assertFalse(run["workflow_policy"]["contract_required"])
        self.assertIsNone(run["repositories"]["api"]["plan_path"])
        escalation = run["profile_escalation"]
        self.assertTrue(Path(escalation["path"]).is_file())
        self.assertIn("api", run["pending_plan_revisions"])

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
        engine = self.initialize(fake, profile="full")
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
        engine = self.initialize(fake, profile="full")
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

        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "pair one planned validation ID",
        ):
            engine.build_assignment(
                stage="validate",
                repo_id="api",
                scope="missing-validation-ids",
                instructions=["Run the planned checks."],
                validation_commands=engine._plan_commands("api"),
            )

        assignment_path = engine._validation_assignment("api", "post-implementation")
        assignment = json.loads(assignment_path.read_text(encoding="utf-8"))

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
        graph.invoke({"run_dir": str(self.run_dir)}, config=config)

        self.assertEqual("complete", engine.load_run()["status"])
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertEqual(1, stages.count("validation-fix"))
        self.assertEqual(1, stages.count("validate"))
        fixes = engine._artifacts(repo_id="api", stage="validation-fix", kind="result")
        self.assertEqual(["API-VAL-001"], fixes[-1][2]["validation_ids"])

    def test_repeated_validation_failure_blocks_after_one_fix_batch(self) -> None:
        fake = FakeSuccessfulBatch(always_fail_validation=True)
        engine = self.initialize(fake)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-validation-limit"},
            "recursion_limit": 150,
        }

        graph.invoke({"run_dir": str(self.run_dir)}, config=config)

        run = engine.load_run()
        self.assertEqual("blocked", run["status"])
        self.assertIn("Validation fix cycles exhausted", run["blockers"][0]["summary"])
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertEqual(1, stages.count("validation-fix"))

    def test_high_review_finding_runs_one_review_and_one_fix_batch(self) -> None:
        fake = FakeSuccessfulBatch(round_one_finding=True)
        engine = self.initialize(fake)
        run = engine.load_run()
        self.assertEqual(1, run["retry_limits"]["review_rounds"])
        # Prove the hard round limit wins even for a legacy policy that would
        # otherwise request targeted verification.
        run["workflow_policy"]["second_review"] = "high-risk-fixes"
        engine._save_run(run)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 150,
        }
        graph.invoke({"run_dir": str(self.run_dir)}, config=config)

        self.assertEqual("complete", engine.load_run()["status"])
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertIn("fix-1", stages)
        self.assertNotIn("review-2", stages)
        self.assertNotIn("fix-2", stages)
        fix_artifacts = engine._artifacts(repo_id="api", stage="fix-1", kind="result")
        self.assertEqual(["API-R1-001"], fix_artifacts[-1][2]["finding_ids"])

    def test_repeated_pipeline_failure_blocks_after_one_fix_batch(self) -> None:
        fake = FakeSuccessfulBatch(delivery_code_failures=2)
        engine = self.initialize(fake)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-pipeline-limit"},
            "recursion_limit": 150,
        }

        graph.invoke({"run_dir": str(self.run_dir)}, config=config)

        run = engine.load_run()
        self.assertEqual("blocked", run["status"])
        self.assertIn("required check failed", run["blockers"][0]["summary"])
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertEqual(1, stages.count("pipeline-fix"))
        self.assertEqual(2, stages.count("deliver"))

    def test_full_profile_graph_runs_risk_challenge_and_requested_report(
        self,
    ) -> None:
        self.write_spec(
            profile="full",
            risks=["security"],
            report_requested=True,
        )
        fake = FakeSuccessfulBatch(risk_flags=["security"])
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
        self.assertIsNone(run["contract_path"])
        self.assertFalse(run["workflow_policy"]["integration_required"])
        self.assertTrue(run["workflow_policy"]["report_required"])
        self.assertEqual(0, len(engine._artifacts(kind="integration")))
        reports = engine._artifacts(kind="report")
        self.assertEqual(1, len(reports))
        self.assertTrue(Path(reports[0][1]["html_path"]).is_file())
        self.assertEqual(
            [
                "plan",
                "design-challenge",
                "implement",
                "review-1",
                "deliver",
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

    def test_single_repository_full_profile_does_not_require_shared_contract(self) -> None:
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

    def test_low_risk_graph_completes_without_approval_or_duplicate_validation(self) -> None:
        fake = FakeSuccessfulBatch()
        engine = self.initialize(fake)
        graph = build_graph(engine, InMemorySaver())
        config = {
            "configurable": {"thread_id": "20260822T100000Z-langgraph-test"},
            "recursion_limit": 100,
        }
        output = graph.invoke({"run_dir": str(self.run_dir)}, config=config)

        run = engine.load_run()
        self.assertEqual(
            {
                "worker_replacements_per_stage": 1,
                "artifact_repairs_per_action": 1,
                "contract_revisions": 1,
                "plan_revision_cycles": 1,
                "validation_fix_cycles": 1,
                "review_rounds": 1,
                "pipeline_fix_cycles": 1,
            },
            run["retry_limits"],
        )
        self.assertNotIn("__interrupt__", output)
        self.assertEqual("approved", run["plan_review"]["status"])
        self.assertEqual("workflow-policy", run["plan_review"]["approval_source"])
        self.assertIn("Automatically accepted", run["plan_review"]["approval_text"])
        self.assertEqual("complete", run["status"])
        self.assertEqual("complete", run["phase"])
        self.assertTrue((self.run_dir / "metrics.json").is_file())
        stages = [assignment["stage"] for assignment in fake.assignments]
        self.assertEqual(["plan", "implement", "review-1", "deliver"], stages)
        deliveries = engine._artifacts(repo_id="api", stage="deliver", kind="delivery")
        self.assertEqual("https://example.test/pull/1", deliveries[-1][1]["pr_url"])
        (self.worktree / "uncommitted-after-delivery.txt").write_text(
            "not delivered\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "read-only worker changed repository content",
        ):
            engine._validate_worker_output(deliveries[-1][2], deliveries[-1][0])

    def test_cli_persists_plan_interrupt_in_sqlite(self) -> None:
        fake = FakePlanningBatch()
        engine = self.initialize(fake, profile="full")
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
