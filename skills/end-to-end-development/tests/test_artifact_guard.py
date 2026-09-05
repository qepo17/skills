from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "artifact_guard.py"
SPEC = importlib.util.spec_from_file_location("artifact_guard", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
artifact_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact_guard)


class ArtifactGuardDesignChallengeTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.repo_root = self.root / "repo"
        self.worktree = self.root / "worktree"
        self.artifact_dir = self.root / "run" / "repos" / "api"
        self.log_dir = self.artifact_dir / "logs"
        for directory in (self.repo_root, self.worktree, self.artifact_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.initial_status = self.artifact_dir / "initial-status.txt"
        self.initial_status.write_text("", encoding="utf-8")
        self.contract = self.root / "run" / "contract-v1.json"
        self.contract.parent.mkdir(parents=True, exist_ok=True)
        self.contract.write_text('{"artifact_kind":"contract"}\n', encoding="utf-8")
        self.requirements = self.root / "run" / "requirements.json"
        self.requirements.write_text(
            '{"artifact_kind":"requirements","requirements":[]}\n', encoding="utf-8"
        )
        self.request = self.root / "run" / "request.md"
        self.request.write_text("request\n", encoding="utf-8")
        self.guidance = self.root / "SIMPLICITY-CHALLENGE.md"
        self.guidance.write_text("subtractive guidance\n", encoding="utf-8")
        self.codebase_design_dir = self.root / "codebase-design"
        self.codebase_design_dir.mkdir()
        self.codebase_skill = self.codebase_design_dir / "SKILL.md"
        self.codebase_skill.write_text("---\nname: codebase-design\n---\n", encoding="utf-8")
        self.deepening = self.codebase_design_dir / "DEEPENING.md"
        self.deepening.write_text("deepening guidance\n", encoding="utf-8")
        self.artifact_contract = SCRIPT_PATH.parents[1] / "ARTIFACTS.md"
        self.baseline = "a" * 40
        self.run_id = "20260816T120000Z-simplicity"
        self.contract_hash = self.sha(self.contract)

    def tearDown(self) -> None:
        artifact_guard.CURRENT_ARTIFACT_PATH = None
        self.tempdir.cleanup()

    @staticmethod
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def assignment(
        self,
        *,
        stage: str,
        output_kind: str,
        output_path: Path,
        input_paths: list[Path],
        attempt: int = 1,
        project_access: str = "none",
        repository_access: str = "read",
        thinking: str = "xhigh",
        profile: str | None = None,
        task_ids: list[str] | None = None,
        finding_ids: list[str] | None = None,
        validation_ids: list[str] | None = None,
        packet_id: str | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        assignment_path = self.root / "run" / "assignments" / f"{stage}-api-{attempt}.json"
        assignment = {
            "schema_version": 1,
            "artifact_kind": "assignment",
            "run_id": self.run_id,
            "action_id": f"{stage}:api:{attempt}",
            "created_at": "2026-08-16T12:00:00Z",
            "stage": stage,
            "attempt": attempt,
            "repo_id": "api",
            "cwd": str(self.worktree),
            "thinking": thinking,
            "timeout_seconds": 3600,
            "project_file_access": project_access,
            "git_access": "none",
            "forge_access": "none",
            "repositories": [
                {
                    "repo_id": "api",
                    "root": str(self.repo_root),
                    "worktree": str(self.worktree),
                    "access": repository_access,
                }
            ],
            "baseline": self.baseline,
            "preexisting_status_path": str(self.initial_status),
            "input_artifacts": [
                {"path": str(path), "sha256": self.sha(path)}
                for path in sorted(input_paths)
            ],
            "requirement_ids": ["REQ-001"],
            "instructions": ["Follow the immutable assignment."],
            "validation_commands": [],
            "output_kind": output_kind,
            "output_artifact": str(output_path),
            "log_dir": str(self.log_dir),
            "artifact_contract_path": str(self.artifact_contract),
            "validator_path": str(SCRIPT_PATH),
        }
        if profile is not None:
            assignment.update(
                {
                    "profile": profile,
                    "task_ids": task_ids or [],
                    "finding_ids": finding_ids or [],
                    "validation_ids": validation_ids or [],
                    "packet_id": packet_id,
                    "artifact_schema_path": str(
                        SCRIPT_PATH.parents[1] / "schemas" / f"{output_kind}.md"
                    ),
                }
            )
            assignment.pop("artifact_contract_path")
        self.write_json(assignment_path, assignment)
        return assignment_path, assignment

    def candidate_plan(
        self,
        *,
        with_trigger: bool = False,
        profile: str | None = None,
        challenge_required: bool = True,
        risk_flags: list[str] | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        plan_path = self.artifact_dir / "plan-v1.json"
        plan_inputs = [self.contract] if profile is None else [self.request, self.requirements]
        assignment_path, _ = self.assignment(
            stage="plan",
            output_kind="plan",
            output_path=plan_path,
            input_paths=plan_inputs,
            profile=profile,
        )
        mechanism_ids = ["API-MECH-001"] if with_trigger else []
        mechanisms: list[dict[str, Any]] = []
        if with_trigger:
            mechanisms.append(
                {
                    "id": "API-MECH-001",
                    "type": "database-trigger",
                    "requirement_ids": ["REQ-001"],
                    "task_ids": ["API-TASK-001"],
                    "summary": "Enforce a write invariant.",
                    "necessity": "Independent writers must observe the invariant.",
                    "repository_evidence": "An importer writes to the table directly.",
                    "simpler_alternatives": [
                        "A check constraint cannot reference the related table."
                    ],
                    "operational_considerations": [
                        "Validate locking, deployment ordering, and rollback."
                    ],
                    "validation_ids": ["API-VAL-001"],
                }
            )
        plan = {
            "schema_version": 1,
            "artifact_kind": "plan",
            "run_id": self.run_id,
            "assignment_path": str(assignment_path),
            "assignment_sha256": self.sha(assignment_path),
            "repo_id": "api",
            "revision": 1,
            "supersedes_plan": None,
            "design_challenge": None,
            "created_at": "2026-08-16T12:01:00Z",
            "status": "complete",
            "baseline": self.baseline,
            "contract_sha256": self.contract_hash if profile is None else None,
            "tasks": [
                {
                    "id": "API-TASK-001",
                    "requirement_ids": ["REQ-001"],
                    "depends_on": [],
                    "summary": "Implement the required behavior.",
                    "steps": ["Use the existing repository convention."],
                    "expected_files": ["src/example.py"],
                    "validation_ids": ["API-VAL-001"],
                    "mechanism_ids": mechanism_ids,
                }
            ],
            "validations": [
                {
                    "id": "API-VAL-001",
                    "command": "python -m unittest",
                    "cwd": str(self.worktree),
                    "scope": "focused",
                    "migration_capable": False,
                }
            ],
            "complexity_mechanisms": mechanisms,
            "finding_resolutions": [],
            "non_goals": [],
            "risks": [],
            "blockers": [],
        }
        if profile is not None:
            plan.update(
                {
                    "requirements_sha256": self.sha(self.requirements),
                    "risk_flags": risk_flags or [],
                    "design_challenge_required": challenge_required,
                    "work_packets": [
                        {
                            "id": "API-PACKET-001",
                            "summary": "Implement and verify the required behavior.",
                            "task_ids": ["API-TASK-001"],
                            "depends_on": [],
                            "estimated_minutes": 30,
                        }
                    ],
                }
            )
        self.write_json(plan_path, plan)
        return plan_path, plan

    def design_challenge(
        self,
        plan_path: Path,
        *,
        verdict: str = "accept",
        with_remove_finding: bool = False,
        attempt: int = 1,
        mode: str = "full",
    ) -> tuple[Path, dict[str, Any]]:
        challenge_path = self.artifact_dir / f"design-challenge-v{attempt}.json"
        assignment_path, _ = self.assignment(
            stage="design-challenge",
            output_kind="design-challenge",
            output_path=challenge_path,
            input_paths=[
                self.contract,
                plan_path,
                self.guidance,
                self.codebase_skill,
                self.deepening,
            ],
            attempt=attempt,
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assessments: list[dict[str, Any]] = []
        for mechanism in plan["complexity_mechanisms"]:
            assessments.append(
                {
                    "mechanism_id": mechanism["id"],
                    "decision": "remove" if with_remove_finding else "retain",
                    "necessity_assessment": (
                        "The current requirements were traced to this mechanism."
                    ),
                    "repository_evidence": "The repository write paths were inspected.",
                    "simpler_alternative": (
                        "Use the existing application transaction where possible."
                    ),
                    "operational_risk": (
                        "Deployment, rollback, locks, observability, and tests were assessed."
                    ),
                }
            )
        findings: list[dict[str, Any]] = []
        if with_remove_finding:
            findings.append(
                {
                    "id": f"API-D{attempt}-001",
                    "target": "plan",
                    "category": "database",
                    "severity": "high",
                    "actionable": True,
                    "requirement_ids": ["REQ-001"],
                    "task_ids": ["API-TASK-001"],
                    "mechanism_id": "API-MECH-001",
                    "summary": "The trigger is not necessary.",
                    "evidence": "Only one application write path exists.",
                    "simpler_alternative": "Use the existing application transaction.",
                    "required_change": "Remove the trigger from the plan.",
                }
            )
        challenge = {
            "schema_version": 1,
            "artifact_kind": "design-challenge",
            "run_id": self.run_id,
            "assignment_path": str(assignment_path),
            "assignment_sha256": self.sha(assignment_path),
            "repo_id": "api",
            "attempt": attempt,
            "created_at": "2026-08-16T12:02:00Z",
            "status": "complete",
            "baseline": self.baseline,
            "contract_sha256": self.contract_hash,
            "plan": {"path": str(plan_path), "sha256": self.sha(plan_path)},
            "mode": mode,
            "verdict": verdict,
            "summary": "Applied the subtractive simplicity rubric.",
            "mechanism_assessments": assessments,
            "findings": findings,
            "blockers": [],
        }
        self.write_json(challenge_path, challenge)
        return challenge_path, challenge

    def revised_plan(
        self,
        plan_path: Path,
        challenge_path: Path,
        *,
        resolve_findings: bool,
    ) -> tuple[Path, dict[str, Any]]:
        revised_path = self.artifact_dir / "plan-v2.json"
        assignment_path, _ = self.assignment(
            stage="plan",
            output_kind="plan",
            output_path=revised_path,
            input_paths=[self.contract, plan_path, challenge_path],
            attempt=2,
        )
        revised = json.loads(plan_path.read_text(encoding="utf-8"))
        resolutions = []
        if resolve_findings:
            resolutions.append(
                {
                    "finding_id": "API-D1-001",
                    "outcome": "resolved",
                    "summary": "Removed the unnecessary trigger.",
                    "evidence": "The revised task uses the existing application transaction.",
                }
            )
        revised.update(
            {
                "assignment_path": str(assignment_path),
                "assignment_sha256": self.sha(assignment_path),
                "revision": 2,
                "supersedes_plan": {"path": str(plan_path), "sha256": self.sha(plan_path)},
                "design_challenge": {
                    "path": str(challenge_path),
                    "sha256": self.sha(challenge_path),
                },
                "created_at": "2026-08-16T12:03:00Z",
                "complexity_mechanisms": [],
                "finding_resolutions": resolutions,
            }
        )
        revised["tasks"][0]["mechanism_ids"] = []
        self.write_json(revised_path, revised)
        return revised_path, revised

    def validate_worker_artifact(self, kind: str, path: Path, value: dict[str, Any]) -> None:
        artifact_guard.CURRENT_ARTIFACT_PATH = path
        getattr(artifact_guard, f"validate_{kind.replace('-', '_')}")(value)

    def test_accepts_simple_candidate_plan_and_challenge(self) -> None:
        plan_path, plan = self.candidate_plan()
        self.validate_worker_artifact("plan", plan_path, plan)

        challenge_path, challenge = self.design_challenge(plan_path)
        self.validate_worker_artifact("design-challenge", challenge_path, challenge)

    def test_rejects_trigger_without_a_simpler_alternative(self) -> None:
        plan_path, plan = self.candidate_plan(with_trigger=True)
        plan["complexity_mechanisms"][0]["simpler_alternatives"] = []
        self.write_json(plan_path, plan)

        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "simpler_alternatives.*must not be empty",
        ):
            self.validate_worker_artifact("plan", plan_path, plan)

    def test_rejects_challenge_with_wrong_plan_hash(self) -> None:
        plan_path, _ = self.candidate_plan()
        challenge_path, challenge = self.design_challenge(plan_path)
        challenge["plan"]["sha256"] = "0" * 64
        self.write_json(challenge_path, challenge)

        with self.assertRaisesRegex(artifact_guard.ValidationError, "expected .* from"):
            self.validate_worker_artifact("design-challenge", challenge_path, challenge)

    def test_accepts_resolved_revised_plan_and_verification_challenge(self) -> None:
        plan_path, _ = self.candidate_plan(with_trigger=True)
        challenge_path, _ = self.design_challenge(
            plan_path,
            verdict="revise-plan",
            with_remove_finding=True,
        )
        revised_path, revised = self.revised_plan(
            plan_path,
            challenge_path,
            resolve_findings=True,
        )
        self.validate_worker_artifact("plan", revised_path, revised)

        verification_path, verification = self.design_challenge(
            revised_path,
            verdict="accept",
            attempt=2,
            mode="verification",
        )
        self.validate_worker_artifact("design-challenge", verification_path, verification)

    def test_rejects_unresolved_findings_in_revised_plan(self) -> None:
        plan_path, _ = self.candidate_plan(with_trigger=True)
        challenge_path, _ = self.design_challenge(
            plan_path,
            verdict="revise-plan",
            with_remove_finding=True,
        )
        revised_path, revised = self.revised_plan(
            plan_path,
            challenge_path,
            resolve_findings=False,
        )

        with self.assertRaisesRegex(artifact_guard.ValidationError, "must resolve exactly"):
            self.validate_worker_artifact("plan", revised_path, revised)

    def test_implementation_assignment_requires_canonical_plan_and_challenge(self) -> None:
        plan_path, _ = self.candidate_plan()
        challenge_path, _ = self.design_challenge(plan_path)
        output_path = self.artifact_dir / "implementation-api-task-001-1.json"
        _, valid_assignment = self.assignment(
            stage="implement",
            output_kind="result",
            output_path=output_path,
            input_paths=[self.contract, plan_path, challenge_path],
            project_access="write",
            repository_access="write",
            thinking="high",
        )
        artifact_guard.validate_assignment(valid_assignment)

        _, missing_challenge = self.assignment(
            stage="implement",
            output_kind="result",
            output_path=output_path,
            input_paths=[self.contract, plan_path],
            attempt=2,
            project_access="write",
            repository_access="write",
            thinking="high",
        )
        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "canonical plan's accepting design challenge",
        ):
            artifact_guard.validate_assignment(missing_challenge)

    def test_rejects_design_challenge_assignment_without_pinned_guidance(self) -> None:
        plan_path, _ = self.candidate_plan()
        output_path = self.artifact_dir / "design-challenge-without-guidance.json"
        _, assignment = self.assignment(
            stage="design-challenge",
            output_kind="design-challenge",
            output_path=output_path,
            input_paths=[self.contract, plan_path],
        )

        with self.assertRaisesRegex(artifact_guard.ValidationError, "SIMPLICITY-CHALLENGE.md"):
            artifact_guard.validate_assignment(assignment)

    def test_rejects_write_access_for_design_challenge_assignment(self) -> None:
        plan_path, _ = self.candidate_plan()
        output_path = self.artifact_dir / "design-challenge-write.json"
        _, assignment = self.assignment(
            stage="design-challenge",
            output_kind="design-challenge",
            output_path=output_path,
            input_paths=[self.contract, plan_path],
            project_access="write",
            repository_access="write",
        )

        with self.assertRaisesRegex(artifact_guard.ValidationError, "may not write project files"):
            artifact_guard.validate_assignment(assignment)

    def test_run_requires_an_accepting_challenge_after_plan_phase(self) -> None:
        plan_path, _ = self.candidate_plan()
        challenge_path, _ = self.design_challenge(plan_path)
        request = self.root / "run" / "request.md"
        requirements = self.root / "run" / "requirements.json"
        request.write_text("request\n", encoding="utf-8")
        requirements.write_text("{}\n", encoding="utf-8")
        run = {
            "schema_version": 1,
            "artifact_kind": "run",
            "run_id": self.run_id,
            "created_at": "2026-08-16T12:00:00Z",
            "updated_at": "2026-08-16T12:04:00Z",
            "status": "working",
            "phase": "implement",
            "request_path": str(request),
            "request_sha256": self.sha(request),
            "requirements_path": str(requirements),
            "requirements_sha256": self.sha(requirements),
            "contract_path": str(self.contract),
            "contract_sha256": self.contract_hash,
            "retry_limits": {
                "worker_replacements_per_stage": 1,
                "contract_revisions": 1,
                "plan_revision_cycles": 1,
                "validation_fix_cycles": 2,
                "review_rounds": 2,
                "pipeline_fix_cycles": 2,
            },
            "repositories": {
                "api": {
                    "root": str(self.repo_root),
                    "worktree": str(self.worktree),
                    "artifact_dir": str(self.artifact_dir),
                    "base_branch": "main",
                    "branch": "feat/example",
                    "baseline": self.baseline,
                    "initial_status_path": str(self.initial_status),
                    "stage": "implement",
                    "status": "pending",
                    "active_writer": None,
                    "plan_path": str(plan_path),
                    "plan_sha256": self.sha(plan_path),
                    "design_challenge_path": str(challenge_path),
                    "design_challenge_sha256": self.sha(challenge_path),
                    "accepted_artifacts": {
                        "design-challenge-v1": {
                            "path": str(challenge_path),
                            "sha256": self.sha(challenge_path),
                        },
                        "plan-v1": {"path": str(plan_path), "sha256": self.sha(plan_path)},
                    },
                }
            },
            "next_actions": [],
            "blockers": [],
        }

        artifact_guard.validate_run(run)
        run["repositories"]["api"]["design_challenge_path"] = None
        run["repositories"]["api"]["design_challenge_sha256"] = None
        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "requires an accepting design challenge",
        ):
            artifact_guard.validate_run(run)

    def test_accepts_profiled_plan_with_bounded_work_packet(self) -> None:
        plan_path, plan = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        self.validate_worker_artifact("plan", plan_path, plan)

    def test_profiled_run_can_advance_with_an_explicitly_waived_challenge(self) -> None:
        plan_path, plan = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        self.validate_worker_artifact("plan", plan_path, plan)
        plan_hash = self.sha(plan_path)
        review_path = self.root / "run" / "plan-review-v1.md"
        review_path.write_text(
            f"# Plan review\n\napi\n\n{plan_path}\n\n{plan_hash}\n",
            encoding="utf-8",
        )
        request = self.request
        requirements = self.requirements
        run = {
            "schema_version": 1,
            "artifact_kind": "run",
            "run_id": self.run_id,
            "created_at": "2026-08-16T12:00:00Z",
            "updated_at": "2026-08-16T12:04:00Z",
            "status": "working",
            "phase": "implement",
            "profile": "standard",
            "profile_reasons": ["Single repository with no declared high-risk surface."],
            "risk_flags": [],
            "workflow_policy": {
                "contract_required": False,
                "design_challenge": "risk-only",
                "integration_required": False,
                "report_required": False,
                "max_tasks_per_packet": 3,
                "max_packet_minutes": 45,
                "second_review": "high-risk-fixes",
                "blocking_severities": ["critical", "high", "medium"],
                "coordinator_attempt_budget": 30,
                "auto_resume": True,
            },
            "request_path": str(request),
            "request_sha256": self.sha(request),
            "requirements_path": str(requirements),
            "requirements_sha256": self.sha(requirements),
            "contract_path": None,
            "contract_sha256": None,
            "retry_limits": {
                "worker_replacements_per_stage": 1,
                "contract_revisions": 1,
                "plan_revision_cycles": 1,
                "validation_fix_cycles": 2,
                "review_rounds": 2,
                "pipeline_fix_cycles": 2,
            },
            "repositories": {
                "api": {
                    "root": str(self.repo_root),
                    "worktree": str(self.worktree),
                    "artifact_dir": str(self.artifact_dir),
                    "base_branch": "main",
                    "branch": "feat/example",
                    "baseline": self.baseline,
                    "initial_status_path": str(self.initial_status),
                    "stage": "implement",
                    "status": "pending",
                    "active_writer": None,
                    "plan_path": str(plan_path),
                    "plan_sha256": plan_hash,
                    "design_challenge_required": False,
                    "design_challenge_path": None,
                    "design_challenge_sha256": None,
                    "accepted_artifacts": {
                        "plan-v1": {"path": str(plan_path), "sha256": plan_hash}
                    },
                }
            },
            "accepted_artifacts": {},
            "next_actions": [],
            "blockers": [],
        }
        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "plan_review",
        ):
            artifact_guard.validate_run(run)

        run["plan_review"] = {
            "status": "approved",
            "requested_at": "2026-08-16T12:03:00Z",
            "review_path": str(review_path),
            "review_sha256": self.sha(review_path),
            "contract_sha256": None,
            "plans": {
                "api": {
                    "plan_path": str(plan_path),
                    "plan_sha256": plan_hash,
                    "design_challenge_path": None,
                    "design_challenge_sha256": None,
                }
            },
            "approved_at": "2026-08-16T12:04:00Z",
            "approval_text": "I approve the complete plan review bundle.",
        }
        artifact_guard.validate_run(run)

    def test_mandatory_plan_review_hard_stops_until_explicit_user_approval(self) -> None:
        plan_path, plan = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        self.validate_worker_artifact("plan", plan_path, plan)
        plan_hash = self.sha(plan_path)
        review_path = self.root / "run" / "plan-review-v1.md"
        review_path.write_text(
            f"# Plan review\n\napi\n\n{plan_path}\n\n{plan_hash}\n",
            encoding="utf-8",
        )
        run = {
            "schema_version": 1,
            "artifact_kind": "run",
            "run_id": self.run_id,
            "created_at": "2026-08-16T12:00:00Z",
            "updated_at": "2026-08-16T12:04:00Z",
            "status": "awaiting-user",
            "phase": "plan-review",
            "profile": "standard",
            "profile_reasons": ["Single repository with no declared high-risk surface."],
            "risk_flags": [],
            "workflow_policy": {
                "contract_required": False,
                "design_challenge": "risk-only",
                "integration_required": False,
                "report_required": False,
                "max_tasks_per_packet": 3,
                "max_packet_minutes": 45,
                "second_review": "high-risk-fixes",
                "blocking_severities": ["critical", "high", "medium"],
                "coordinator_attempt_budget": 30,
                "auto_resume": True,
                "user_plan_approval_required": True,
            },
            "request_path": str(self.request),
            "request_sha256": self.sha(self.request),
            "requirements_path": str(self.requirements),
            "requirements_sha256": self.sha(self.requirements),
            "contract_path": None,
            "contract_sha256": None,
            "retry_limits": {
                "worker_replacements_per_stage": 1,
                "contract_revisions": 1,
                "plan_revision_cycles": 1,
                "validation_fix_cycles": 2,
                "review_rounds": 2,
                "pipeline_fix_cycles": 2,
            },
            "repositories": {
                "api": {
                    "root": str(self.repo_root),
                    "worktree": str(self.worktree),
                    "artifact_dir": str(self.artifact_dir),
                    "base_branch": "main",
                    "branch": "feat/example",
                    "baseline": self.baseline,
                    "initial_status_path": str(self.initial_status),
                    "stage": "plan-review",
                    "status": "pending",
                    "active_writer": None,
                    "plan_path": str(plan_path),
                    "plan_sha256": plan_hash,
                    "design_challenge_required": False,
                    "design_challenge_path": None,
                    "design_challenge_sha256": None,
                    "accepted_artifacts": {
                        "plan-v1": {"path": str(plan_path), "sha256": plan_hash}
                    },
                }
            },
            "plan_review": {
                "status": "pending",
                "requested_at": "2026-08-16T12:04:00Z",
                "review_path": str(review_path),
                "review_sha256": self.sha(review_path),
                "contract_sha256": None,
                "plans": {
                    "api": {
                        "plan_path": str(plan_path),
                        "plan_sha256": plan_hash,
                        "design_challenge_path": None,
                        "design_challenge_sha256": None,
                    }
                },
                "approved_at": None,
                "approval_text": None,
            },
            "accepted_artifacts": {},
            "next_actions": [],
            "blockers": [],
        }
        artifact_guard.validate_run(run)

        run["phase"] = "implement"
        run["status"] = "working"
        run["repositories"]["api"]["stage"] = "implement"
        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "pending review requires the plan-review phase",
        ):
            artifact_guard.validate_run(run)

        run["plan_review"].update(
            {
                "status": "approved",
                "approved_at": "2026-08-16T12:05:00Z",
                "approval_text": "I approve all plans in this review bundle.",
            }
        )
        artifact_guard.validate_run(run)

    def test_project_writer_assignment_can_pin_the_approved_plan_review(self) -> None:
        plan_path, _ = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        review_path = self.root / "run" / "plan-review-v1.md"
        review_path.write_text("Approved plan bundle.\n", encoding="utf-8")
        output_path = self.artifact_dir / "implementation-approved.json"
        assignment_path, assignment = self.assignment(
            stage="implement",
            output_kind="result",
            output_path=output_path,
            input_paths=[self.request, self.requirements, plan_path, review_path],
            project_access="write",
            repository_access="write",
            thinking="high",
            profile="standard",
            task_ids=["API-TASK-001"],
            packet_id="API-PACKET-001",
        )
        assignment["plan_review"] = {
            "path": str(review_path),
            "sha256": self.sha(review_path),
        }
        self.write_json(assignment_path, assignment)
        artifact_guard.validate_assignment(assignment)

        assignment["plan_review"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(artifact_guard.ValidationError, "expected .* from"):
            artifact_guard.validate_assignment(assignment)

    def test_rejects_work_packet_over_the_standard_three_task_limit(self) -> None:
        plan_path, plan = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        for number in range(2, 5):
            task = dict(plan["tasks"][0])
            task["id"] = f"API-TASK-{number:03d}"
            plan["tasks"].append(task)
        plan["work_packets"][0]["task_ids"] = [task["id"] for task in plan["tasks"]]
        self.write_json(plan_path, plan)

        with self.assertRaisesRegex(artifact_guard.ValidationError, "at most 3 tasks"):
            self.validate_worker_artifact("plan", plan_path, plan)

    def test_migration_capable_validation_requires_declared_migration_risk(self) -> None:
        plan_path, plan = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        plan["validations"][0]["migration_capable"] = True
        self.write_json(plan_path, plan)
        artifact_guard.CURRENT_ARTIFACT_PATH = plan_path

        with self.assertRaisesRegex(
            artifact_guard.ValidationError,
            "migration-capable validation requires the database-migration risk flag",
        ):
            artifact_guard.validate_plan(plan)

    def test_rejects_waived_challenge_for_high_risk_plan(self) -> None:
        plan_path, plan = self.candidate_plan(
            profile="standard",
            challenge_required=False,
            risk_flags=["concurrency"],
        )
        with self.assertRaisesRegex(artifact_guard.ValidationError, "high-risk plans"):
            self.validate_worker_artifact("plan", plan_path, plan)

    def test_accepts_implementation_packet_when_low_risk_challenge_is_waived(self) -> None:
        plan_path, plan = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        self.validate_worker_artifact("plan", plan_path, plan)
        output_path = self.artifact_dir / "implementation-api-packet-001-1.json"
        _, assignment = self.assignment(
            stage="implement",
            output_kind="result",
            output_path=output_path,
            input_paths=[self.request, self.requirements, plan_path],
            project_access="write",
            repository_access="write",
            thinking="high",
            profile="standard",
            task_ids=["API-TASK-001"],
            packet_id="API-PACKET-001",
        )
        artifact_guard.validate_assignment(assignment)

    def test_typed_blocker_only_writes_an_active_unaccepted_output(self) -> None:
        output = self.artifact_dir / "validation.json"
        assignment_path, assignment = self.assignment(
            stage="validate", output_kind="result", output_path=output, input_paths=[self.contract],
        )
        artifact_guard.initialize_artifact(assignment_path)
        run_path = self.root / "run" / "run.json"
        run = {"run_id": self.run_id, "next_actions": [{"assignment_path": str(assignment_path),
               "output_artifact": str(output)}], "accepted_artifacts": {}, "repositories": {}}
        self.write_json(run_path, run)
        evidence = self.log_dir / "environment.log"
        evidence.write_text("The test service is unavailable.\n")
        artifact_guard.record_blocker(
            assignment_path, kind="environment", summary="Test service unavailable.",
            evidence_path=evidence, required_action="Restore the isolated test service.",
        )
        data = json.loads(output.read_text())
        self.assertEqual("blocked", data["status"])
        artifact_guard.validate_blockers(data["blockers"])
        self.assertEqual("environment", data["blockers"][0]["kind"])
        before = output.read_bytes()
        run["accepted_artifacts"]["validation"] = {"path": str(output), "sha256": self.sha(output)}
        self.write_json(run_path, run)
        with self.assertRaisesRegex(artifact_guard.ValidationError, "accepted artifact"):
            artifact_guard.record_blocker(assignment_path, kind="code", summary="No overwrite",
                                         evidence_path=evidence, required_action="Inspect")
        self.assertEqual(before, output.read_bytes())
        run["accepted_artifacts"] = {}
        run["next_actions"] = []
        self.write_json(run_path, run)
        with self.assertRaisesRegex(artifact_guard.ValidationError, "active assignment"):
            artifact_guard.record_blocker(assignment_path, kind="code", summary="No arbitrary writes",
                                         evidence_path=evidence, required_action="Inspect")
        self.assertEqual(before, output.read_bytes())

    def test_missing_blocker_kind_has_a_structured_failure_location(self) -> None:
        evidence = self.log_dir / "test.log"
        evidence.write_text("unavailable\n")
        with self.assertRaises(artifact_guard.ValidationError) as raised:
            artifact_guard.validate_blockers([{"id": "BLOCK-001", "summary": "Unavailable",
                                              "evidence_path": str(evidence), "required_action": "Restore"}])
        self.assertEqual("missing-field", raised.exception.code)
        self.assertEqual("$.blockers[0].kind", raised.exception.path)
        self.assertIn("missing required field 'kind'", str(raised.exception))

    def test_delivery_rejects_checks_for_a_different_head(self) -> None:
        output = self.artifact_dir / "delivery.json"
        assignment_path, assignment = self.assignment(
            stage="deliver", output_kind="delivery", output_path=output,
            input_paths=[self.contract], thinking="medium",
        )
        assignment.update(git_access="write", forge_access="write", delivery_evidence_version=2)
        self.write_json(assignment_path, assignment)
        log = self.log_dir / "checks.log"
        log.write_text("Checks passed for the earlier commit.\n")
        artifact = artifact_guard.artifact_skeleton(assignment_path, assignment)
        artifact.update(
            status="complete", branch="feat/example", base_branch="main",
            commits=["a" * 40], pr_url="https://example.test/pull/1",
            head_sha="a" * 40, pushed_head_sha="a" * 40, checked_head_sha="b" * 40,
            check_policy={"status": "required", "required_checks": [{"name": "tests", "app_id": None}],
                          "evidence": [{"path": str(log), "sha256": self.sha(log)}]},
            checks=[{"name": "tests", "url": "https://example.test/check/1", "required": True,
                     "state": "passed", "evidence_path": str(log)}], blockers=[],
        )
        self.write_json(output, artifact)
        artifact_guard.CURRENT_ARTIFACT_PATH = output
        with self.assertRaisesRegex(artifact_guard.ValidationError, "head"):
            artifact_guard.validate_delivery(artifact)

    def test_routes_medium_thinking_to_mechanical_stages_only(self) -> None:
        validation_output = self.artifact_dir / "validation-1.json"
        _, validation_assignment = self.assignment(
            stage="validate",
            output_kind="result",
            output_path=validation_output,
            input_paths=[self.contract],
            thinking="medium",
            profile="standard",
        )
        artifact_guard.validate_assignment(validation_assignment)

        plan_path, _ = self.candidate_plan(
            profile="standard",
            challenge_required=False,
        )
        implementation_output = self.artifact_dir / "implementation-medium.json"
        _, implementation_assignment = self.assignment(
            stage="implement",
            output_kind="result",
            output_path=implementation_output,
            input_paths=[self.request, self.requirements, plan_path],
            project_access="write",
            repository_access="write",
            thinking="medium",
            profile="standard",
            task_ids=["API-TASK-001"],
            packet_id="API-PACKET-001",
        )
        with self.assertRaisesRegex(artifact_guard.ValidationError, "require high or xhigh"):
            artifact_guard.validate_assignment(implementation_assignment)

    def test_initializes_stage_specific_result_skeleton(self) -> None:
        output_path = self.artifact_dir / "validation-skeleton.json"
        assignment_path, _ = self.assignment(
            stage="validate",
            output_kind="result",
            output_path=output_path,
            input_paths=[self.contract],
            thinking="medium",
            profile="standard",
        )
        initialized = artifact_guard.initialize_artifact(assignment_path)
        self.assertEqual(output_path, initialized)
        skeleton = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual("result", skeleton["artifact_kind"])
        self.assertEqual("validate", skeleton["stage"])
        self.assertIn("tree_fingerprint", skeleton)
        with self.assertRaisesRegex(artifact_guard.ValidationError, "refusing to overwrite"):
            artifact_guard.initialize_artifact(assignment_path)

    def test_next_action_bound_and_narrow_repair_eligibility(self) -> None:
        output = self.artifact_dir / "handoff.json"
        assignment_path, assignment = self.assignment(
            stage="validate", output_kind="result", output_path=output, input_paths=[self.contract],
        )
        result = artifact_guard.artifact_skeleton(assignment_path, assignment)
        result["git"]["status_short_path"] = str(self.initial_status)
        for value in (None, "x" * 300, "x" * 301, "界" * 301, "", 301):
            with self.subTest(value=value):
                result["next_action"] = value
                self.write_json(output, result)
                oversized = isinstance(value, str) and len(value) > 300
                if value is None or value == "x" * 300:
                    self.validate_worker_artifact("result", output, result)
                else:
                    with self.assertRaises(artifact_guard.ValidationError) as rejected:
                        self.validate_worker_artifact("result", output, result)
                    self.assertEqual("$.next_action", rejected.exception.path)
                before = output.read_bytes()
                if oversized:
                    artifact_guard.repairable_result(result, output)
                else:
                    with self.assertRaises(artifact_guard.ValidationError):
                        artifact_guard.repairable_result(result, output)
                self.assertEqual(before, output.read_bytes())
        del result["next_action"]
        with self.assertRaises(artifact_guard.ValidationError):
            artifact_guard.repairable_result(result, output)

    def test_handoff_repair_preserves_genuine_blockers_and_other_fields(self) -> None:
        output = self.artifact_dir / "handoff-blocked.json"
        assignment_path, assignment = self.assignment(
            stage="validate", output_kind="result", output_path=output, input_paths=[self.contract],
        )
        result = artifact_guard.artifact_skeleton(assignment_path, assignment)
        result.update(status="blocked", next_action="x" * 301, blockers=[{
            "id": "BLOCK-001", "summary": "Test service unavailable.",
            "evidence_path": str(self.initial_status), "required_action": "Restore the service.",
        }])
        result["git"]["status_short_path"] = str(self.initial_status)
        self.write_json(output, result)
        artifact_guard.repairable_result(result, output)
        repaired = json.loads(output.read_text())
        repaired["next_action"] = None
        repaired["blockers"][0]["kind"] = "environment"
        repair = {"repair_of": {"artifact": {"path": str(output)}}}
        artifact_guard.validate_repaired_payload(repair, repaired)
        self.validate_worker_artifact("result", output, repaired)
        for field, value in (("status", "complete"), ("summary", "Different facts"), ("task_ids", ["NEW-TASK"])):
            with self.subTest(field=field):
                modified = {**repaired, field: value}
                with self.assertRaisesRegex(artifact_guard.ValidationError, "semantic evidence"):
                    artifact_guard.validate_repaired_payload(repair, modified)
        result["next_action"] = "Already concise."
        self.write_json(output, result)
        with self.assertRaisesRegex(artifact_guard.ValidationError, "semantic evidence"):
            artifact_guard.validate_repaired_payload(repair, repaired)

    def test_batched_review_fix_resolves_every_assigned_finding(self) -> None:
        output_path = self.artifact_dir / "fix-1-batch-1.json"
        assignment_path, _ = self.assignment(
            stage="fix-1",
            output_kind="result",
            output_path=output_path,
            input_paths=[self.contract],
            project_access="write",
            repository_access="write",
            thinking="medium",
            profile="standard",
            finding_ids=["API-R1-001", "API-R1-002"],
        )
        status_path = self.log_dir / "fix-status.txt"
        status_path.write_text(" M src/example.py\n", encoding="utf-8")
        evidence_one = self.log_dir / "finding-one.txt"
        evidence_two = self.log_dir / "finding-two.txt"
        evidence_one.write_text("fixed one\n", encoding="utf-8")
        evidence_two.write_text("fixed two\n", encoding="utf-8")
        result = {
            "schema_version": 1,
            "artifact_kind": "result",
            "run_id": self.run_id,
            "assignment_path": str(assignment_path),
            "assignment_sha256": self.sha(assignment_path),
            "repo_id": "api",
            "stage": "fix-1",
            "attempt": 1,
            "created_at": "2026-08-16T12:10:00Z",
            "status": "complete",
            "summary": "Resolved the compatible review findings in one batch.",
            "requirement_ids": ["REQ-001"],
            "task_ids": [],
            "changed_files": ["src/example.py"],
            "tree_fingerprint": "c" * 64,
            "validations": [],
            "decisions": [],
            "resolutions": [
                {
                    "finding_id": "API-R1-001",
                    "outcome": "fixed",
                    "summary": "Fixed the first finding.",
                    "evidence_path": str(evidence_one),
                },
                {
                    "finding_id": "API-R1-002",
                    "outcome": "fixed",
                    "summary": "Fixed the second finding.",
                    "evidence_path": str(evidence_two),
                },
            ],
            "git": {"head": self.baseline, "status_short_path": str(status_path)},
            "blockers": [],
            "next_action": "validate",
        }
        self.write_json(output_path, result)
        self.validate_worker_artifact("result", output_path, result)

        result["resolutions"].pop()
        self.write_json(output_path, result)
        with self.assertRaisesRegex(artifact_guard.ValidationError, "assigned findings"):
            self.validate_worker_artifact("result", output_path, result)

    def test_reused_validation_requires_matching_passing_command_and_tree(self) -> None:
        output_path = self.artifact_dir / "validation-reused.json"
        assignment_path, _ = self.assignment(
            stage="validate",
            output_kind="result",
            output_path=output_path,
            input_paths=[self.contract],
            thinking="medium",
            profile="standard",
        )
        tree = "d" * 64
        command = "python -m unittest"
        command_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
        source_path = self.artifact_dir / "validation-source.json"
        source = {
            "artifact_kind": "result",
            "tree_fingerprint": tree,
            "validations": [
                {
                    "id": "API-VAL-001",
                    "command": command,
                    "command_sha256": command_hash,
                    "tree_fingerprint": tree,
                    "result": "pass",
                }
            ],
        }
        self.write_json(source_path, source)
        log_path = self.log_dir / "reused.log"
        log_path.write_text("reused passing evidence\n", encoding="utf-8")
        status_path = self.log_dir / "validation-status.txt"
        status_path.write_text("", encoding="utf-8")
        result = {
            "schema_version": 1,
            "artifact_kind": "result",
            "run_id": self.run_id,
            "assignment_path": str(assignment_path),
            "assignment_sha256": self.sha(assignment_path),
            "repo_id": "api",
            "stage": "validate",
            "attempt": 1,
            "created_at": "2026-08-16T12:20:00Z",
            "status": "complete",
            "summary": "Reused validation for an identical command and worktree.",
            "requirement_ids": ["REQ-001"],
            "task_ids": [],
            "changed_files": [],
            "tree_fingerprint": tree,
            "validations": [
                {
                    "id": "API-VAL-001",
                    "command": command,
                    "command_sha256": command_hash,
                    "cwd": str(self.worktree),
                    "tree_fingerprint": tree,
                    "cache_status": "reused",
                    "source_artifact": {
                        "path": str(source_path),
                        "sha256": self.sha(source_path),
                    },
                    "exit_code": 0,
                    "result": "pass",
                    "summary": "Reused a matching passing result.",
                    "log_path": str(log_path),
                }
            ],
            "decisions": [],
            "resolutions": [],
            "git": {"head": self.baseline, "status_short_path": str(status_path)},
            "blockers": [],
            "next_action": "review-1",
        }
        self.write_json(output_path, result)
        self.validate_worker_artifact("result", output_path, result)

        source["tree_fingerprint"] = "e" * 64
        self.write_json(source_path, source)
        result["validations"][0]["source_artifact"]["sha256"] = self.sha(source_path)
        self.write_json(output_path, result)
        with self.assertRaisesRegex(artifact_guard.ValidationError, "same tree fingerprint"):
            self.validate_worker_artifact("result", output_path, result)


if __name__ == "__main__":
    unittest.main()
