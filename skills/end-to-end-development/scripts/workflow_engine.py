#!/usr/bin/env python3
"""Durable LangGraph control plane for the end-to-end-development skill.

The graph owns phase routing, bounded retries, worker batching, approval
interrupts, and recovery. Immutable artifacts remain the evidence interface;
Git and forge side effects are always reconciled through those artifacts.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

sys.dont_write_bytecode = True

import artifact_guard  # noqa: E402
import worker_supervisor  # noqa: E402
import workflow_tools  # noqa: E402


PROJECT_WRITE_STAGES = {"implement", "validation-fix", "fix-1", "fix-2", "pipeline-fix"}
GLOBAL_STAGES = {"contract", "integrate", "report"}
OUTPUT_KIND_BY_STAGE = {
    "contract": "contract",
    "plan": "plan",
    "design-challenge": "design-challenge",
    "implement": "result",
    "validate": "result",
    "validation-fix": "result",
    "review-1": "review",
    "fix-1": "result",
    "review-2": "review",
    "fix-2": "result",
    "integrate": "integration",
    "deliver": "delivery",
    "pipeline-fix": "result",
    "report": "report",
}
SCHEMA_BY_KIND = {
    kind: f"schemas/{kind}.md"
    for kind in {
        "contract",
        "plan",
        "design-challenge",
        "result",
        "review",
        "integration",
        "delivery",
        "report",
    }
}
PHASE_NODE = {
    "bootstrap": "bootstrap",
    "contract": "contract",
    "plan": "plan",
    "plan-review": "plan_review",
    "implement": "implement",
    "validate": "validate",
    "review-1": "review_1",
    "fix-1": "fix_1",
    "review-2": "review_2",
    "fix-2": "fix_2",
    "integrate": "integrate",
    "deliver": "deliver",
    "report": "report",
    "complete": "complete",
}
EXPLICIT_APPROVAL_RE = re.compile(
    r"\b(approve|approved|accept|accepted)\b.*\b(all|entire|complete|bundle|plans?)\b"
    r"|\b(all|entire|complete)\b.*\b(approve|approved|accept|accepted)\b",
    re.IGNORECASE,
)
NEGATED_APPROVAL_RE = re.compile(
    r"\b(do\s+not|don't|cannot|can't|not)\s+(approve|accept)\b|\b(reject|decline)\b",
    re.IGNORECASE,
)
QUALIFIED_APPROVAL_RE = re.compile(
    r"\b(except|excluding|exclude|apart\s+from|other\s+than|but|however|although)\b"
    r"|\b(subject\s+to|provided\s+that|on\s+condition)\b",
    re.IGNORECASE,
)


class WorkflowState(TypedDict, total=False):
    run_dir: str
    last_transition: str
    outcome: str
    attempt_baseline: int


class BatchRunner(Protocol):
    def __call__(
        self,
        assignment_paths: list[Path],
        *,
        run_dir: Path,
        worker_runtime: str,
        allow_existing: bool,
    ) -> tuple[int, dict[str, Any]]: ...


@dataclass(frozen=True)
class BatchResult:
    accepted: tuple[tuple[dict[str, Any], dict[str, Any]], ...]
    rejected: tuple[tuple[dict[str, Any], dict[str, Any]], ...]
    manifest_path: Path


class WorkflowError(RuntimeError):
    """A recoverable orchestration or state error."""


class RunLock:
    """Cross-process lock for the mutable projection files of one run."""

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / ".orchestrator.lock"
        self.handle: Any = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: object) -> None:
        assert self.handle is not None
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {"path": str(resolved), "sha256": _sha256(resolved)}


def _load_json(path: Path) -> dict[str, Any]:
    return workflow_tools.load_json(path)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.").lower()
    return slug[:120] or "action"


def _git(worktree: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(worktree), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode:
        raise WorkflowError(
            f"git {' '.join(args)} failed in {worktree}: {process.stderr.strip()}"
        )
    return process.stdout.strip()


def _default_batch_runner(
    assignment_paths: list[Path],
    *,
    run_dir: Path,
    worker_runtime: str,
    allow_existing: bool,
) -> tuple[int, dict[str, Any]]:
    return workflow_tools.run_assignment_batch(
        assignment_paths,
        run_dir=run_dir,
        worker_runtime=worker_runtime,
        allow_existing=allow_existing,
    )


class WorkflowEngine:
    """Deep orchestration module used by every LangGraph phase node.

    Its external interface is intentionally small: reconcile, execute one
    named phase, and process the plan-review decision. Worker launching and
    filesystem details remain internal and are exercised through this seam.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        skill_dir: Path | None = None,
        codebase_design_dir: Path | None = None,
        batch_runner: BatchRunner = _default_batch_runner,
        worker_runtime: str = "auto",
        report_root: Path | None = None,
        now: Callable[[], str] = workflow_tools.utc_now,
    ) -> None:
        self.run_dir = run_dir.resolve()
        self.skill_dir = (skill_dir or Path(__file__).resolve().parents[1]).resolve()
        self.codebase_design_dir = (
            codebase_design_dir.resolve() if codebase_design_dir else None
        )
        self.batch_runner = batch_runner
        self.worker_runtime = worker_runtime
        self.report_root = (report_root or Path.home() / "src" / "artifacts").resolve()
        self.now = now

    # ---------- Durable state and reconciliation ----------

    @property
    def run_path(self) -> Path:
        return self.run_dir / "run.json"

    @property
    def agents_path(self) -> Path:
        return self.run_dir / "agents.json"

    def load_run(self, *, validate: bool = True) -> dict[str, Any]:
        run = _load_json(self.run_path)
        if validate:
            artifact_guard.validate_run(run)
        return run

    def load_agents(self, *, validate: bool = True) -> dict[str, Any]:
        agents = _load_json(self.agents_path)
        if validate:
            artifact_guard.validate_agents(agents)
        return agents

    def _save_run(self, run: dict[str, Any]) -> None:
        run["updated_at"] = self.now()
        artifact_guard.validate_run(run)
        workflow_tools.atomic_write_json(self.run_path, run)

    def _save_agents(self, agents: dict[str, Any]) -> None:
        agents["updated_at"] = self.now()
        artifact_guard.validate_agents(agents)
        workflow_tools.atomic_write_json(self.agents_path, agents)

    def _append_event(self, event: str, **fields: Any) -> None:
        run = self.load_run(validate=False)
        entry = {
            "at": self.now(),
            "run_id": run["run_id"],
            "event": event,
            "phase": run["phase"],
            **fields,
        }
        path = self.run_dir / "events.jsonl"
        serialized = json.dumps(entry, separators=(",", ":"))
        previous = ""
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            previous = lines[-1] if lines else ""
        if previous != serialized:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")

    def _set_phase(self, phase: str, *, repository_phase: str | None = None) -> None:
        with RunLock(self.run_dir):
            run = self.load_run()
            old_phase = run["phase"]
            run["phase"] = phase
            run["status"] = "working"
            run["next_actions"] = []
            run["blockers"] = []
            target = repository_phase or phase
            for repository in run["repositories"].values():
                repository["stage"] = target
                repository["status"] = "pending"
                repository["active_writer"] = None
            self._save_run(run)
        if old_phase != phase:
            self._append_event(
                "phase-changed", previous_phase=old_phase, next_action=phase
            )

    def _block(
        self,
        *,
        summary: str,
        evidence_path: Path,
        required_action: str,
        kind: str = "code",
        repo_id: str | None = None,
    ) -> None:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        if not evidence_path.exists():
            evidence_path.write_text(summary + "\n", encoding="utf-8")
        blocker = {
            "id": f"BLOCK-{hashlib.sha256((summary + str(evidence_path)).encode()).hexdigest()[:8].upper()}",
            "kind": kind,
            "summary": summary[:1200],
            "evidence_path": str(evidence_path.resolve()),
            "required_action": required_action[:2000],
        }
        with RunLock(self.run_dir):
            run = self.load_run()
            run["status"] = "blocked"
            run["next_actions"] = []
            run["blockers"] = [blocker]
            for key, repository in run["repositories"].items():
                repository["active_writer"] = None
                if repo_id is None or repo_id == key:
                    repository["status"] = "blocked"
            self._save_run(run)
        self._append_event("blocked", blocker_id=blocker["id"], next_action=None)

    def _block_from_artifact(self, artifact: dict[str, Any]) -> None:
        blockers = artifact.get("blockers", [])
        if blockers:
            blocker = blockers[0]
            self._block(
                summary=blocker["summary"],
                evidence_path=Path(blocker["evidence_path"]),
                required_action=blocker["required_action"],
                kind=blocker["kind"],
                repo_id=artifact.get("repo_id"),
            )
            return
        path = Path(artifact["assignment_path"])
        self._block(
            summary=f"{artifact['artifact_kind']} worker returned {artifact.get('status', 'failed')}",
            evidence_path=path,
            required_action="Inspect the accepted worker artifact and resume with a concrete recovery.",
            repo_id=artifact.get("repo_id"),
        )

    def _wait_for_crash_survivor(
        self, assignment_path: Path, assignment: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Adopt an orphaned worker through its durably recorded backend."""
        return workflow_tools.recover_assignment_worker(
            assignment_path,
            assignment,
            run_dir=self.run_dir,
        )

    def resume_external_blockers(self) -> bool:
        """Retry only blockers whose external condition can change between invocations."""
        with RunLock(self.run_dir):
            run = self.load_run()
            if run["status"] != "blocked" or not run["blockers"]:
                return False
            retryable = {
                "environment",
                "authentication",
                "permission",
                "infrastructure",
            }
            if any(blocker["kind"] not in retryable for blocker in run["blockers"]):
                return False
            run["status"] = "working"
            run["blockers"] = []
            for repository in run["repositories"].values():
                if repository["status"] == "blocked":
                    repository["status"] = "pending"
            self._save_run(run)
        self._append_event(
            "resumed", reason="retry-external-blocker", next_action=run["phase"]
        )
        return True

    def retry_validation_evidence(self) -> bool:
        """Retry only the exact validation-coverage blocker after an engine fix."""
        with RunLock(self.run_dir):
            run = self.load_run()
            if (
                run["status"] != "blocked"
                or run["phase"] != "validate"
                or not run["blockers"]
            ):
                return False
            expected_summaries = {
                f"Validation for {repo_id} did not cover the current tree and planned checks."
                for repo_id in run["repositories"]
            }
            if any(
                blocker["kind"] != "code"
                or blocker["summary"] not in expected_summaries
                or blocker["required_action"]
                != "Correct the validation evidence before resuming."
                for blocker in run["blockers"]
            ):
                return False
            run["status"] = "working"
            run["blockers"] = []
            for repository in run["repositories"].values():
                if repository["status"] == "blocked":
                    repository["status"] = "pending"
            self._save_run(run)
        self._append_event(
            "resumed", reason="retry-validation-evidence", next_action="validate"
        )
        return True

    def reconcile(self) -> str:
        """Validate durable facts and recover completed outputs after a crash."""
        cleanup_outcomes = workflow_tools.retry_worker_cleanups(run_dir=self.run_dir)
        preflight = self.load_run()
        recovered_workers: dict[str, dict[str, Any]] = {}
        for action in preflight["next_actions"]:
            assignment_path = action.get("assignment_path")
            if action.get("status") != "working" or not assignment_path:
                continue
            resolved_assignment_path = Path(assignment_path)
            assignment = _load_json(resolved_assignment_path)
            worker = self._wait_for_crash_survivor(
                resolved_assignment_path, assignment
            )
            if worker is not None:
                recovered_workers[assignment["action_id"]] = worker

        with RunLock(self.run_dir):
            run = self.load_run()
            agents = self.load_agents()
            if run["run_id"] != agents["run_id"]:
                raise WorkflowError("run.json and agents.json have different run IDs")

            changed = False
            for outcome in cleanup_outcomes:
                agent = next(
                    (
                        item
                        for item in agents["agents"]
                        if item["name"] == outcome.get("agent_name")
                    ),
                    None,
                )
                if agent is None:
                    continue
                agent["cleanup_status"] = outcome["cleanup_status"]
                agent["cleanup_error"] = outcome.get("cleanup_error")
                if (
                    outcome["cleanup_status"] == "complete"
                    and agent["status"] in {"starting", "working", "blocked", "idle"}
                ):
                    agent["status"] = "closed"
                changed = True
            recovered: list[tuple[dict[str, Any], dict[str, Any]]] = []
            remaining_actions: list[dict[str, Any]] = []
            for action in run["next_actions"]:
                assignment_path_value = action.get("assignment_path")
                if not assignment_path_value:
                    remaining_actions.append(action)
                    continue
                assignment_path = Path(assignment_path_value)
                assignment = _load_json(assignment_path)
                artifact_guard.validate_assignment(assignment)
                output_path = Path(assignment["output_artifact"])
                if not output_path.exists():
                    action["status"] = "pending"
                    changed = True
                    repository_id = assignment.get("repo_id")
                    if repository_id:
                        run["repositories"][repository_id]["active_writer"] = None
                    remaining_actions.append(action)
                    continue
                try:
                    artifact = self._validate_worker_output(assignment, output_path)
                except (OSError, ValueError, artifact_guard.ValidationError):
                    action["status"] = "pending"
                    changed = True
                    repository_id = assignment.get("repo_id")
                    if repository_id:
                        run["repositories"][repository_id]["active_writer"] = None
                    remaining_actions.append(action)
                    continue
                self._record_accepted_reference(run, assignment, output_path)
                self._apply_recovered_projection(run, assignment, artifact, output_path)
                recovered.append((assignment, artifact))
                agent_name = workflow_tools._agent_name(assignment)
                if not any(item["name"] == agent_name for item in agents["agents"]):
                    recovered_at = self.now()
                    worker = recovered_workers.get(assignment["action_id"], {})
                    cleanup_status = worker.get("cleanup_status", "complete")
                    agents["agents"].append(
                        {
                            "name": agent_name,
                            "stage": assignment["stage"],
                            "repo_id": assignment.get("repo_id"),
                            "attempt": assignment["attempt"],
                            "backend": worker.get("backend", "recovered"),
                            "handle_id": worker.get("handle_id", agent_name),
                            "status": (
                                "closed"
                                if cleanup_status == "complete"
                                else "idle"
                            ),
                            "cleanup_status": cleanup_status,
                            "cleanup_error": worker.get("cleanup_error"),
                            "started_at": worker.get("started_at", recovered_at),
                            "ended_at": worker.get("ended_at", recovered_at),
                            "output_artifact": assignment["output_artifact"],
                        }
                    )
                repository_id = assignment.get("repo_id")
                if repository_id:
                    run["repositories"][repository_id]["active_writer"] = None
                changed = True
            if changed:
                run["next_actions"] = remaining_actions
                self._save_agents(agents)
                self._save_run(run)
            # A stale writer with no live action cannot survive reconciliation.
            active_action_ids = {action["action_id"] for action in remaining_actions}
            for repository in run["repositories"].values():
                if repository.get("active_writer") not in active_action_ids:
                    repository["active_writer"] = None
            if changed:
                self._save_run(run)

        for assignment, artifact in recovered:
            self._append_event(
                "artifact-accepted",
                action_id=assignment["action_id"],
                artifact=assignment["output_artifact"],
                recovery=True,
                next_action=None,
            )
            if artifact.get("status") in {"blocked", "failed"}:
                self._block_from_artifact(artifact)
                break
        return self.load_run()["phase"]

    def _apply_recovered_projection(
        self,
        run: dict[str, Any],
        assignment: dict[str, Any],
        artifact: dict[str, Any],
        output_path: Path,
    ) -> None:
        """Apply phase-specific canonical pointers without repeating side effects."""
        if artifact.get("status") != "complete":
            return
        stage = assignment["stage"]
        if stage == "contract":
            run["contract_path"] = str(output_path.resolve())
            run["contract_sha256"] = _sha256(output_path)
            pending = run.setdefault("pending_plan_revisions", {})
            for repo_id, repository in run["repositories"].items():
                if repository.get("plan_path") and repo_id not in pending:
                    pending[repo_id] = {
                        "plan": {
                            "path": repository["plan_path"],
                            "sha256": repository["plan_sha256"],
                        },
                        "basis": {
                            "kind": "contract-revision",
                            "artifact": _reference(output_path),
                        },
                    }
                repository["plan_path"] = None
                repository["plan_sha256"] = None
                repository["design_challenge_path"] = None
                repository["design_challenge_sha256"] = None
        elif stage == "plan":
            repository = run["repositories"][assignment["repo_id"]]
            repository["plan_path"] = str(output_path.resolve())
            repository["plan_sha256"] = _sha256(output_path)
            repository["design_challenge_required"] = artifact[
                "design_challenge_required"
            ]
            repository["design_challenge_path"] = None
            repository["design_challenge_sha256"] = None
            run.get("pending_plan_revisions", {}).pop(assignment["repo_id"], None)
        elif stage == "design-challenge" and artifact.get("verdict") == "accept":
            repository = run["repositories"][assignment["repo_id"]]
            repository["design_challenge_path"] = str(output_path.resolve())
            repository["design_challenge_sha256"] = _sha256(output_path)

    # ---------- Immutable assignment construction ----------

    def _requirements(self) -> dict[str, Any]:
        run = self.load_run(validate=False)
        return _load_json(Path(run["requirements_path"]))

    def _requirement_ids(self, repo_id: str | None = None) -> list[str]:
        requirements = self._requirements()["requirements"]
        return sorted(
            requirement["id"]
            for requirement in requirements
            if repo_id is None or repo_id in requirement["repository_ids"]
        )

    def _repository_scope(
        self, run: dict[str, Any], repo_id: str | None, *, write: bool
    ) -> list[dict[str, str]]:
        selected = (
            run["repositories"].items()
            if repo_id is None
            else [(repo_id, run["repositories"][repo_id])]
        )
        return [
            {
                "repo_id": key,
                "root": repository["root"],
                "worktree": repository["worktree"],
                "access": "write" if write and key == repo_id else "read",
            }
            for key, repository in sorted(selected)
        ]

    def _canonical_inputs(self, run: dict[str, Any], repo_id: str | None) -> list[Path]:
        """Return current canonical inputs without stale plan/critic generations."""
        paths = [Path(run["request_path"]), Path(run["requirements_path"])]
        if run.get("contract_path"):
            paths.append(Path(run["contract_path"]))

        def add_repository(repository: dict[str, Any]) -> None:
            if repository.get("plan_path"):
                paths.append(Path(repository["plan_path"]))
            if repository.get("design_challenge_path"):
                paths.append(Path(repository["design_challenge_path"]))
            for reference in repository.get("accepted_artifacts", {}).values():
                candidate_path = Path(reference["path"])
                if not candidate_path.exists() or candidate_path.suffix != ".json":
                    continue
                try:
                    candidate = _load_json(candidate_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if candidate.get("artifact_kind") in {"plan", "design-challenge"}:
                    continue
                paths.append(candidate_path)

        if repo_id is not None:
            add_repository(run["repositories"][repo_id])
        else:
            for repository in run["repositories"].values():
                add_repository(repository)
            for reference in run.get("accepted_artifacts", {}).values():
                candidate_path = Path(reference["path"])
                if not candidate_path.exists() or candidate_path.suffix != ".json":
                    continue
                try:
                    candidate = _load_json(candidate_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if candidate.get("artifact_kind") == "contract":
                    continue
                paths.append(candidate_path)
        if run.get("plan_review") and run["plan_review"].get("status") == "approved":
            paths.append(Path(run["plan_review"]["review_path"]))
        return sorted(set(path.resolve() for path in paths if path.exists()))

    def _thinking(self, profile: str, stage: str) -> str:
        if profile == "full" and stage in {
            "contract",
            "plan",
            "design-challenge",
            "review-1",
            "review-2",
            "integrate",
        }:
            return "xhigh"
        if stage in {
            "plan",
            "design-challenge",
            "implement",
            "review-1",
            "review-2",
            "fix-1",
            "fix-2",
        }:
            return "high"
        return "medium"

    def _output_path(
        self,
        stage: str,
        repo_id: str | None,
        scope: str,
        attempt: int,
    ) -> Path:
        base = self.run_dir if repo_id is None else self.run_dir / "repos" / repo_id
        suffix = "" if attempt == 1 else f"-attempt-{attempt}"
        if stage == "contract":
            name = f"contract-{_slug(scope)}{suffix}.json"
        elif stage == "plan":
            name = f"plan-{_slug(scope)}{suffix}.json"
        elif stage == "design-challenge":
            name = f"design-challenge-{_slug(scope)}{suffix}.json"
        elif stage == "implement":
            name = f"implementation-{_slug(scope)}{suffix}.json"
        elif stage == "validate":
            name = f"validation-{_slug(scope)}{suffix}.json"
        elif stage == "validation-fix":
            name = f"validation-fix-{_slug(scope)}{suffix}.json"
        elif stage in {"review-1", "review-2"}:
            name = f"{stage}-{_slug(scope)}{suffix}.json"
        elif stage in {"fix-1", "fix-2"}:
            name = f"{stage}-batch-{_slug(scope)}{suffix}.json"
        elif stage == "integrate":
            name = f"integration-{_slug(scope)}{suffix}.json"
        elif stage == "deliver":
            name = f"delivery-{_slug(scope)}{suffix}.json"
        elif stage == "pipeline-fix":
            name = f"pipeline-fix-{_slug(scope)}{suffix}.json"
        elif stage == "report":
            name = f"report-{_slug(scope)}{suffix}.json"
        else:  # pragma: no cover - callers use the stage map
            raise WorkflowError(f"unsupported assignment stage: {stage}")
        return base / name

    def build_assignment(
        self,
        *,
        stage: str,
        repo_id: str | None,
        scope: str,
        attempt: int = 1,
        inputs: Iterable[Path] | None = None,
        instructions: Iterable[str],
        validation_commands: Iterable[str] = (),
        task_ids: Iterable[str] = (),
        finding_ids: Iterable[str] = (),
        validation_ids: Iterable[str] = (),
        packet_id: str | None = None,
        extras: Mapping[str, Any] | None = None,
    ) -> Path:
        run = self.load_run()
        profile = run["profile"]
        write = stage in PROJECT_WRITE_STAGES
        output_kind = OUTPUT_KIND_BY_STAGE[stage]
        action_id = f"{stage}:{repo_id or 'global'}:{scope}:attempt-{attempt}"
        assignment_path = self.run_dir / "assignments" / f"{_slug(action_id)}.json"
        if assignment_path.exists():
            while True:
                assignment = _load_json(assignment_path)
                artifact_guard.validate_assignment(assignment)
                output_path = Path(assignment["output_artifact"])
                if not output_path.exists():
                    return assignment_path
                try:
                    existing = _load_json(output_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    return assignment_path
                if existing.get("status") not in {"blocked", "failed"}:
                    return assignment_path
                assignment_path = self._replacement(assignment)

        if inputs is None:
            selected_inputs = self._canonical_inputs(run, repo_id)
        else:
            selected_inputs = sorted(set(Path(path).resolve() for path in inputs))
        references = [_reference(path) for path in selected_inputs]
        repository = run["repositories"].get(repo_id) if repo_id else None
        output_path = self._output_path(stage, repo_id, scope, attempt)
        log_dir = (
            self.run_dir / "logs"
            if repo_id is None
            else self.run_dir / "repos" / repo_id / "logs"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        assignment: dict[str, Any] = {
            "schema_version": 1,
            "artifact_kind": "assignment",
            "run_id": run["run_id"],
            "action_id": action_id,
            "created_at": self.now(),
            "stage": stage,
            "attempt": attempt,
            "profile": profile,
            "repo_id": repo_id,
            "cwd": repository["worktree"] if repository else str(self.run_dir),
            "thinking": self._thinking(profile, stage),
            "timeout_seconds": 3600 if stage not in {"deliver", "report"} else 1800,
            "project_file_access": "write" if write else "none",
            "git_access": "write" if stage == "deliver" else "none",
            "forge_access": "write" if stage == "deliver" else "none",
            "repositories": self._repository_scope(run, repo_id, write=write),
            "baseline": repository["baseline"] if repository else None,
            "preexisting_status_path": repository["initial_status_path"]
            if repository
            else None,
            "input_artifacts": references,
            "requirement_ids": self._requirement_ids(repo_id),
            "task_ids": sorted(task_ids),
            "finding_ids": sorted(finding_ids),
            "validation_ids": sorted(validation_ids),
            "packet_id": packet_id,
            "instructions": sorted(set(instructions)),
            "validation_commands": list(dict.fromkeys(validation_commands)),
            "output_kind": output_kind,
            "output_artifact": str(output_path.resolve()),
            "log_dir": str(log_dir.resolve()),
            "artifact_schema_path": str(
                (self.skill_dir / SCHEMA_BY_KIND[output_kind]).resolve()
            ),
            "validator_path": str(
                (self.skill_dir / "scripts" / "artifact_guard.py").resolve()
            ),
        }
        if stage not in {"implement"}:
            assignment.pop("packet_id")
        if stage not in {"implement"}:
            assignment["task_ids"] = []
        if stage not in {"fix-1", "fix-2", "review-2"}:
            assignment["finding_ids"] = []
        if stage not in {"validate", "validation-fix"}:
            assignment["validation_ids"] = []
        if write:
            review = run.get("plan_review")
            if not isinstance(review, dict) or review.get("status") != "approved":
                raise WorkflowError(
                    "cannot build a writer assignment before plan approval"
                )
            assignment["plan_review"] = {
                "path": review["review_path"],
                "sha256": review["review_sha256"],
            }
            if not any(ref["path"] == review["review_path"] for ref in references):
                references.append(
                    {"path": review["review_path"], "sha256": review["review_sha256"]}
                )
                references.sort(key=lambda ref: ref["path"])
        if extras:
            assignment.update(dict(extras))
        assignment_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_tools.atomic_write_json(assignment_path, assignment)
        artifact_guard.validate_assignment(assignment)
        return assignment_path

    def _install_actions(self, assignment_paths: list[Path]) -> None:
        assignments = [(path, _load_json(path)) for path in assignment_paths]
        actions = []
        for order, (path, assignment) in enumerate(
            sorted(assignments, key=lambda item: item[1]["action_id"]), start=1
        ):
            actions.append(
                {
                    "order": order,
                    "action_id": assignment["action_id"],
                    "phase": self.load_run(validate=False)["phase"],
                    "repo_id": assignment["repo_id"],
                    "attempt": assignment["attempt"],
                    "input_artifacts": sorted(
                        reference["path"] for reference in assignment["input_artifacts"]
                    ),
                    "output_artifact": assignment["output_artifact"],
                    "status": "pending",
                    "assignment_path": str(path.resolve()),
                }
            )
        with RunLock(self.run_dir):
            run = self.load_run()
            if run["next_actions"]:
                existing = [
                    action.get("assignment_path") for action in run["next_actions"]
                ]
                expected = [str(path.resolve()) for path in assignment_paths]
                if sorted(existing) != sorted(expected):
                    raise WorkflowError(
                        "refusing to replace a different pending action batch"
                    )
                return
            run["next_actions"] = actions
            for assignment in (value for _, value in assignments):
                repo_id = assignment.get("repo_id")
                if repo_id:
                    run["repositories"][repo_id]["status"] = "pending"
            self._save_run(run)

    def _validate_worker_output(
        self, assignment: dict[str, Any], output_path: Path
    ) -> dict[str, Any]:
        raw = output_path.read_bytes()
        if len(raw) > artifact_guard.MAX_BYTES[assignment["output_kind"]]:
            raise artifact_guard.ValidationError("artifact exceeds its size limit")
        artifact = json.loads(raw)
        artifact_guard.CURRENT_ARTIFACT_PATH = output_path
        artifact_guard.VALIDATORS[assignment["output_kind"]](
            artifact_guard.obj(artifact, "$")
        )
        repo_id = assignment.get("repo_id")
        if repo_id is None:
            return artifact
        worktree = Path(assignment["cwd"])
        if (
            artifact.get("baseline") is not None
            and artifact["baseline"] != assignment["baseline"]
        ):
            raise artifact_guard.ValidationError(
                "worker artifact baseline does not match its immutable assignment"
            )
        if artifact["artifact_kind"] == "result":
            actual_fingerprint = workflow_tools.worktree_fingerprint(worktree)
            if artifact.get("tree_fingerprint") != actual_fingerprint:
                raise artifact_guard.ValidationError(
                    "result tree fingerprint does not match the current worktree"
                )
            actual_head = _git(worktree, "rev-parse", "HEAD")
            if artifact.get("git", {}).get("head") != actual_head:
                raise artifact_guard.ValidationError(
                    "result Git HEAD does not match the current worktree"
                )
            status_path = Path(artifact["git"]["status_short_path"])
            if (
                status_path.read_text(encoding="utf-8", errors="replace").strip()
                != _git(worktree, "status", "--short").strip()
            ):
                raise artifact_guard.ValidationError(
                    "result status evidence does not match the current worktree"
                )
        elif artifact["artifact_kind"] == "review":
            status_path = Path(artifact["reviewed_status_path"])
            if (
                status_path.read_text(encoding="utf-8", errors="replace").strip()
                != _git(worktree, "status", "--short").strip()
            ):
                raise artifact_guard.ValidationError(
                    "review status evidence does not match the current worktree"
                )
        elif artifact["artifact_kind"] == "delivery":
            if artifact.get("status") == "complete":
                actual_head = _git(worktree, "rev-parse", "HEAD")
                actual_branch = _git(worktree, "branch", "--show-current")
                if actual_head not in artifact.get("commits", []):
                    raise artifact_guard.ValidationError(
                        "delivery commits do not contain the current worktree HEAD"
                    )
                if artifact.get("branch") != actual_branch:
                    raise artifact_guard.ValidationError(
                        "delivery branch does not match the current worktree"
                    )
                current_status = _git(worktree, "status", "--short").strip()
                preexisting_status = (
                    Path(assignment["preexisting_status_path"])
                    .read_text(encoding="utf-8", errors="replace")
                    .strip()
                )
                if current_status != preexisting_status:
                    raise artifact_guard.ValidationError(
                        "delivery worktree differs from its pre-existing status; "
                        "task changes may be missing from the delivered commits"
                    )
        return artifact

    def _record_accepted_reference(
        self, run: dict[str, Any], assignment: dict[str, Any], output_path: Path
    ) -> None:
        target = (
            run["accepted_artifacts"]
            if assignment.get("repo_id") is None
            else run["repositories"][assignment["repo_id"]]["accepted_artifacts"]
        )
        target[assignment["action_id"]] = _reference(output_path)

    def _replacement(self, assignment: dict[str, Any]) -> Path:
        replacement = dict(assignment)
        attempt = assignment["attempt"] + 1
        replacement["attempt"] = attempt
        replacement["created_at"] = self.now()
        replacement["action_id"] = re.sub(
            r":attempt-[0-9]+$", f":attempt-{attempt}", assignment["action_id"]
        )
        old_output = Path(assignment["output_artifact"])
        stem = re.sub(r"-attempt-[0-9]+$", "", old_output.stem)
        replacement["output_artifact"] = str(
            old_output.with_name(
                f"{stem}-attempt-{attempt}{old_output.suffix}"
            ).resolve()
        )
        path = self.run_dir / "assignments" / f"{_slug(replacement['action_id'])}.json"
        if not path.exists():
            workflow_tools.atomic_write_json(path, replacement)
        artifact_guard.validate_assignment(_load_json(path))
        return path

    def _execute_assignments(self, paths: list[Path]) -> BatchResult:
        self._install_actions(paths)
        with RunLock(self.run_dir):
            run = self.load_run()
            for action in run["next_actions"]:
                action["status"] = "working"
                assignment = _load_json(Path(action["assignment_path"]))
                repo_id = assignment.get("repo_id")
                if assignment["project_file_access"] == "write" and repo_id:
                    if run["repositories"][repo_id].get("active_writer") not in {
                        None,
                        assignment["action_id"],
                    }:
                        raise WorkflowError(
                            f"writer lease is already held for {repo_id}"
                        )
                    run["repositories"][repo_id]["active_writer"] = assignment[
                        "action_id"
                    ]
                    self._append_event(
                        "writer-acquired",
                        repository_id=repo_id,
                        action_id=assignment["action_id"],
                        next_action=assignment["action_id"],
                    )
                if repo_id:
                    run["repositories"][repo_id]["status"] = "working"
            self._save_run(run)

        # A crash can leave a batch with a mixture of existing and absent
        # outputs. Permit existing files for the entire recovery batch so one
        # partial output cannot prevent its independent peers from resuming.
        allow_existing = any(
            Path(_load_json(path)["output_artifact"]).exists() for path in paths
        )
        code, manifest = self.batch_runner(
            paths,
            run_dir=self.run_dir,
            worker_runtime=self.worker_runtime,
            allow_existing=allow_existing,
        )
        manifest_dir = self.run_dir / "supervisor"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
        manifest_path = manifest_dir / f"manifest-{manifest_hash}.json"
        if not manifest_path.exists():
            workflow_tools.atomic_write_json(manifest_path, manifest)

        by_action = {
            worker["action_id"]: worker for worker in manifest.get("workers", [])
        }
        accepted: list[tuple[dict[str, Any], dict[str, Any]]] = []
        rejected: list[tuple[dict[str, Any], dict[str, Any]]] = []
        with RunLock(self.run_dir):
            run = self.load_run()
            agents = self.load_agents()
            for path in paths:
                assignment = _load_json(path)
                worker = by_action.get(
                    assignment["action_id"],
                    {
                        "action_id": assignment["action_id"],
                        "agent_name": _slug(assignment["action_id"]),
                        "terminal_id": "unavailable",
                        "started_at": self.now(),
                        "ended_at": self.now(),
                        "status": "rejected",
                        "reason": "batch manifest omitted the assignment",
                    },
                )
                agent_name = worker.get("agent_name") or _slug(assignment["action_id"])
                existing_agent = next(
                    (item for item in agents["agents"] if item["name"] == agent_name),
                    None,
                )
                cleanup_status = worker.get("cleanup_status")
                if cleanup_status is None:
                    # Legacy batch adapters owned pane cleanup but exposed only
                    # pane_closed. Normalize that old manifest at the seam.
                    cleanup_status = (
                        "complete" if worker.get("pane_closed", True) else "retained"
                    )
                agent_record = {
                    "name": agent_name,
                    "stage": assignment["stage"],
                    "repo_id": assignment.get("repo_id"),
                    "attempt": assignment["attempt"],
                    "backend": worker.get("backend") or "legacy",
                    "handle_id": worker.get("handle_id")
                    or worker.get("pane_id")
                    or worker.get("terminal_id")
                    or agent_name,
                    "status": (
                        "closed"
                        if worker.get("status") == "accepted"
                        and cleanup_status == "complete"
                        else "idle"
                        if worker.get("status") == "accepted"
                        else "failed"
                    ),
                    "cleanup_status": cleanup_status,
                    "cleanup_error": worker.get("cleanup_error")
                    or worker.get("pane_close_error"),
                    "started_at": worker.get("started_at") or self.now(),
                    "ended_at": worker.get("ended_at") or self.now(),
                    "output_artifact": assignment["output_artifact"],
                }
                if existing_agent is None:
                    agents["agents"].append(agent_record)
                else:
                    existing_agent.update(agent_record)
                repo_id = assignment.get("repo_id")
                if repo_id:
                    repository = run["repositories"][repo_id]
                    repository["active_writer"] = None
                    repository["status"] = (
                        "pending" if worker.get("status") == "accepted" else "failed"
                    )
                if worker.get("status") == "accepted":
                    output_path = Path(assignment["output_artifact"])
                    try:
                        artifact = self._validate_worker_output(assignment, output_path)
                    except Exception as error:  # validated again at the trust boundary
                        worker = dict(worker)
                        worker["status"] = "rejected"
                        worker["reason"] = str(error)
                    else:
                        self._record_accepted_reference(run, assignment, output_path)
                        accepted.append((assignment, artifact))
                if worker.get("status") != "accepted":
                    rejected.append((assignment, worker))
            run["next_actions"] = []
            self._save_agents(agents)
            self._save_run(run)

        for assignment, _artifact in accepted:
            self._append_event(
                "artifact-accepted",
                action_id=assignment["action_id"],
                artifact=assignment["output_artifact"],
                next_action=None,
            )
            if assignment["project_file_access"] == "write":
                self._append_event(
                    "writer-released",
                    repository_id=assignment["repo_id"],
                    action_id=assignment["action_id"],
                    next_action=None,
                )
        for assignment, worker in rejected:
            self._append_event(
                "artifact-rejected",
                action_id=assignment["action_id"],
                artifact=assignment["output_artifact"],
                reason=worker.get("reason"),
                next_action=None,
            )

        if code and not rejected:
            raise WorkflowError(
                "batch runner failed without identifying a rejected assignment"
            )
        return BatchResult(tuple(accepted), tuple(rejected), manifest_path)

    def _run_with_replacements(self, paths: list[Path]) -> tuple[dict[str, Any], ...]:
        current = paths
        accepted: list[dict[str, Any]] = []
        replacement_limit = self.load_run()["retry_limits"][
            "worker_replacements_per_stage"
        ]
        replacement_round = 0
        while current:
            result = self._execute_assignments(current)
            accepted.extend(artifact for _, artifact in result.accepted)
            if not result.rejected:
                break
            replacements: list[Path] = []
            for assignment, worker in result.rejected:
                if replacement_round < replacement_limit:
                    replacements.append(self._replacement(assignment))
                    continue
                self._block(
                    summary=(
                        f"Worker replacements exhausted for {assignment['action_id']}: "
                        f"{worker.get('reason') or worker.get('status')}"
                    ),
                    evidence_path=result.manifest_path,
                    required_action="Inspect the supervisor manifest and choose a recovery.",
                    kind="infrastructure",
                    repo_id=assignment.get("repo_id"),
                )
                return tuple(accepted)
            replacement_round += 1
            current = replacements
        return tuple(accepted)

    # ---------- Artifact queries ----------

    def _artifacts(
        self,
        *,
        repo_id: str | None = None,
        stage: str | None = None,
        kind: str | None = None,
    ) -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
        run = self.load_run(validate=False)
        references = (
            run.get("accepted_artifacts", {})
            if repo_id is None
            else run["repositories"][repo_id].get("accepted_artifacts", {})
        )
        results: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
        for reference in references.values():
            path = Path(reference["path"])
            if not path.exists() or path.suffix != ".json":
                continue
            try:
                artifact = _load_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if kind is not None and artifact.get("artifact_kind") != kind:
                continue
            assignment: dict[str, Any] = {}
            assignment_path = artifact.get("assignment_path")
            if assignment_path and Path(assignment_path).exists():
                assignment = _load_json(Path(assignment_path))
            if (
                stage is not None
                and assignment.get("stage", artifact.get("stage")) != stage
            ):
                continue
            results.append((path, artifact, assignment))
        return sorted(
            results,
            key=lambda item: (
                item[1].get("created_at", ""),
                item[2].get("attempt", 0),
                str(item[0]),
            ),
        )

    @staticmethod
    def _assignment_pins(
        assignment: dict[str, Any], path: Path, digest: str | None = None
    ) -> bool:
        resolved = path.resolve()
        return any(
            Path(reference["path"]).resolve() == resolved
            and (digest is None or reference["sha256"] == digest)
            for reference in assignment.get("input_artifacts", [])
        )

    def _current_plan(self, repo_id: str) -> tuple[Path, dict[str, Any]]:
        repository = self.load_run()["repositories"][repo_id]
        if not repository.get("plan_path"):
            raise WorkflowError(f"repository {repo_id} has no canonical plan")
        path = Path(repository["plan_path"])
        return path, _load_json(path)

    def _plan_commands(self, repo_id: str) -> list[str]:
        _, plan = self._current_plan(repo_id)
        return [validation["command"] for validation in plan["validations"]]

    def _plan_validation_ids(self, repo_id: str) -> list[str]:
        _, plan = self._current_plan(repo_id)
        return [validation["id"] for validation in plan["validations"]]

    def _latest_writer_artifact(
        self, repo_id: str
    ) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
        writers = [
            item
            for item in self._artifacts(repo_id=repo_id, kind="result")
            if item[2].get("stage") in PROJECT_WRITE_STAGES
            and item[1].get("status") == "complete"
        ]
        return writers[-1] if writers else None

    def _current_validation(
        self, repo_id: str, *, require_pass: bool
    ) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
        fingerprint = workflow_tools.worktree_fingerprint(
            Path(self.load_run(validate=False)["repositories"][repo_id]["worktree"])
        )
        latest_writer = self._latest_writer_artifact(repo_id)
        expected = {
            (
                validation["id"],
                hashlib.sha256(validation["command"].encode()).hexdigest(),
            )
            for validation in self._current_plan(repo_id)[1]["validations"]
        }
        for item in reversed(
            self._artifacts(repo_id=repo_id, stage="validate", kind="result")
        ):
            _, artifact, assignment = item
            if (
                artifact.get("status") != "complete"
                or artifact.get("tree_fingerprint") != fingerprint
            ):
                continue
            if latest_writer is not None and not self._assignment_pins(
                assignment,
                latest_writer[0],
                _sha256(latest_writer[0]),
            ):
                continue
            evidence = {
                (record["id"], record.get("command_sha256"))
                for record in artifact.get("validations", [])
                if not require_pass or record.get("result") == "pass"
            }
            if expected <= evidence:
                if require_pass and any(
                    record.get("result") != "pass"
                    for record in artifact.get("validations", [])
                ):
                    continue
                return item
        return None

    def _latest_review(
        self, repo_id: str, round_number: int
    ) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
        stage = f"review-{round_number}"
        values = [
            item
            for item in self._artifacts(repo_id=repo_id, stage=stage, kind="review")
            if item[1].get("status") == "complete"
        ]
        return values[-1] if values else None

    @staticmethod
    def _must_fix(review: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(
            [
                finding
                for finding in review.get("findings", [])
                if finding.get("actionable")
                and finding.get("disposition") == "must-fix"
            ],
            key=lambda finding: finding["id"],
        )

    def _migration_guard(self, repo_id: str) -> bool:
        _, plan = self._current_plan(repo_id)
        if not any(
            validation.get("migration_capable") for validation in plan["validations"]
        ):
            return True
        repository = self.load_run()["repositories"][repo_id]
        evidence = repository.get("database_target_evidence")
        if isinstance(evidence, dict):
            try:
                path = Path(evidence["path"])
                data = _load_json(path)
                if _sha256(path) == evidence["sha256"] and data.get(
                    "classification"
                ) in {
                    "isolated-local",
                    "isolated-test",
                }:
                    return True
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                pass
        log = self.run_dir / "repos" / repo_id / "logs" / "database-target-required.log"
        self._block(
            summary=f"Migration-capable validation for {repo_id} has no safe database target evidence.",
            evidence_path=log,
            required_action=(
                "Record an isolated local/test database target with orchestrator.py database-target "
                "before resuming. Production, staging, shared, or ambiguous targets are forbidden."
            ),
            kind="environment",
            repo_id=repo_id,
        )
        return False

    # ---------- Phase implementations ----------

    def execute_phase(self, phase: str) -> str:
        handler = getattr(self, f"phase_{phase.replace('-', '_')}", None)
        if handler is None:
            raise WorkflowError(f"no phase handler for {phase}")
        return str(handler())

    def _external_preflight_error(self, run: dict[str, Any]) -> str | None:
        if self.batch_runner is not _default_batch_runner:
            return None
        pinned = run.get("worker_execution")
        try:
            context = worker_supervisor.detect_execution_context(
                requested_backend=(
                    pinned["backend"] if isinstance(pinned, dict) else "auto"
                ),
                requested_runtime=(
                    pinned["runtime"]
                    if isinstance(pinned, dict)
                    else self.worker_runtime
                ),
            )
        except (OSError, RuntimeError, ValueError) as error:
            return f"Worker execution preflight failed: {error}"
        if not isinstance(pinned, dict):
            with RunLock(self.run_dir):
                current = self.load_run()
                if current.get("worker_execution") is None:
                    current["worker_execution"] = context.as_dict()
                    self._save_run(current)
            run["worker_execution"] = context.as_dict()
        for repo_id, repository in run["repositories"].items():
            worktree = Path(repository["worktree"])
            try:
                remote = _git(worktree, "remote", "get-url", "origin")
            except WorkflowError as error:
                return f"Forge delivery preflight failed for {repo_id}: {error}"
            if "github" in remote.lower():
                if shutil.which("gh") is None:
                    return "GitHub repository delivery requires the gh CLI."
                auth_command = ["gh", "auth", "status"]
            elif "gitlab" in remote.lower():
                if shutil.which("glab") is None:
                    return "GitLab repository delivery requires the glab CLI."
                auth_command = ["glab", "auth", "status"]
            else:
                auth_command = []
            if auth_command:
                auth = subprocess.run(
                    auth_command,
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
                if auth.returncode != 0:
                    return f"Forge CLI authentication is unavailable for {repo_id}."
        return None

    def phase_bootstrap(self) -> str:
        run = self.load_run()
        preflight_error = self._external_preflight_error(run)
        if preflight_error:
            log = self.run_dir / "logs" / "bootstrap-preflight.log"
            self._block(
                summary=preflight_error,
                evidence_path=log,
                required_action="Restore worker-runtime/Git/forge access, then resume the graph.",
                kind="environment",
            )
            return "blocked"
        for repo_id, repository in run["repositories"].items():
            worktree = Path(repository["worktree"])
            if _git(worktree, "rev-parse", "HEAD") != repository["baseline"]:
                self._block(
                    summary=f"Bootstrap baseline drifted for {repo_id}.",
                    evidence_path=Path(repository["initial_status_path"]),
                    required_action="Recreate or reconcile the dedicated worktree baseline.",
                    kind="environment",
                    repo_id=repo_id,
                )
                return "blocked"
        next_phase = (
            "contract" if run["workflow_policy"]["contract_required"] else "plan"
        )
        self._set_phase(next_phase)
        return next_phase

    def _contract_revision_needed(self, run: dict[str, Any]) -> tuple[int, Path | None]:
        current_revision = 0
        if run.get("contract_path"):
            current_revision = int(_load_json(Path(run["contract_path"]))["revision"])
        for _path, challenge, _assignment in reversed(
            [
                item
                for repo in run["repositories"]
                for item in self._artifacts(repo_id=repo, kind="design-challenge")
            ]
        ):
            if challenge.get("verdict") == "revise-contract" and challenge.get(
                "contract_sha256"
            ) == run.get("contract_sha256"):
                return current_revision + 1, Path(challenge["assignment_path"])
        return max(1, current_revision), None

    def phase_contract(self) -> str:
        run = self.load_run()
        revision, challenge_assignment = self._contract_revision_needed(run)
        needs_contract = (
            run.get("contract_path") is None or challenge_assignment is not None
        )
        if (
            challenge_assignment is not None
            and revision - 1 > run["retry_limits"]["contract_revisions"]
        ):
            challenge = _load_json(challenge_assignment)
            self._block(
                summary="Contract revision limit exhausted without an acceptable plan set.",
                evidence_path=Path(challenge["output_artifact"]),
                required_action="Make a material contract/product decision before resuming.",
                kind="dependency",
            )
            return "blocked"
        if needs_contract:
            inputs = [Path(run["request_path"]), Path(run["requirements_path"])]
            if run.get("contract_path"):
                inputs.append(Path(run["contract_path"]))
            if challenge_assignment:
                challenge = _load_json(challenge_assignment)
                challenge_output = Path(challenge["output_artifact"])
                inputs.append(challenge_output)
            assignment = self.build_assignment(
                stage="contract",
                repo_id=None,
                scope=f"v{revision}",
                inputs=inputs,
                instructions=[
                    "Define only observable cross-repository behavior and concrete dependencies.",
                    "Leave no unresolved question in a complete contract.",
                ],
                extras={"contract_revision": revision},
            )
            artifacts = self._run_with_replacements([assignment])
            if self.load_run()["status"] == "blocked":
                return "blocked"
            contract = artifacts[-1]
            if contract.get("status") != "complete":
                self._block_from_artifact(contract)
                return "blocked"
            output = Path(contract["assignment_path"])
            output_path = Path(_load_json(output)["output_artifact"])
            with RunLock(self.run_dir):
                run = self.load_run()
                run["contract_path"] = str(output_path.resolve())
                run["contract_sha256"] = _sha256(output_path)
                pending = run.setdefault("pending_plan_revisions", {})
                for repo_id, repository in run["repositories"].items():
                    if repository.get("plan_path") and repo_id not in pending:
                        pending[repo_id] = {
                            "plan": {
                                "path": repository["plan_path"],
                                "sha256": repository["plan_sha256"],
                            },
                            "basis": {
                                "kind": "contract-revision",
                                "artifact": _reference(output_path),
                            },
                        }
                    repository["plan_path"] = None
                    repository["plan_sha256"] = None
                    repository["design_challenge_path"] = None
                    repository["design_challenge_sha256"] = None
                self._save_run(run)
        self._set_phase("plan")
        return "plan"

    def _latest_plan_basis(self, repo_id: str) -> tuple[str, Path] | None:
        run = self.load_run(validate=False)
        repository = run["repositories"][repo_id]
        current_hash = repository.get("plan_sha256")
        feedback = run.get("plan_feedback")
        if isinstance(feedback, dict) and repo_id in feedback.get("repository_ids", []):
            plan_path = (
                Path(repository["plan_path"]) if repository.get("plan_path") else None
            )
            if plan_path:
                assignment = _load_json(Path(_load_json(plan_path)["assignment_path"]))
                if not self._assignment_pins(
                    assignment, Path(feedback["path"]), feedback["sha256"]
                ):
                    return "user-feedback", Path(feedback["path"])
        if current_hash:
            for path, challenge, _assignment in reversed(
                self._artifacts(repo_id=repo_id, kind="design-challenge")
            ):
                if challenge.get("plan", {}).get("sha256") != current_hash:
                    continue
                if challenge.get("verdict") in {"revise-plan", "revise-contract"}:
                    return "design-challenge", path
                break
        if repository.get("plan_path"):
            plan = _load_json(Path(repository["plan_path"]))
            if plan.get("contract_sha256") != run.get("contract_sha256"):
                return "contract-revision", Path(run["contract_path"])
            assignment = _load_json(Path(plan["assignment_path"]))
            if assignment.get("profile") != run["profile"]:
                escalation = run.get("profile_escalation")
                if isinstance(escalation, dict):
                    return "profile-escalation", Path(escalation["path"])
        return None

    def _write_profile_escalation(
        self, old_profile: str, policy: dict[str, Any]
    ) -> dict[str, Any]:
        path = (
            self.run_dir
            / f"profile-escalation-{old_profile}-to-{policy['profile']}.json"
        )
        value = {
            "schema_version": 1,
            "artifact_kind": "profile-escalation",
            "run_id": self.load_run(validate=False)["run_id"],
            "created_at": self.now(),
            "from_profile": old_profile,
            "to_profile": policy["profile"],
            "reasons": policy["profile_reasons"],
            "risk_flags": policy["risk_flags"],
        }
        if not path.exists():
            workflow_tools.atomic_write_json(path, value)
        return _reference(path)

    def _accept_plan(self, repo_id: str, artifact: dict[str, Any]) -> None:
        assignment = _load_json(Path(artifact["assignment_path"]))
        output = Path(assignment["output_artifact"])
        with RunLock(self.run_dir):
            run = self.load_run()
            repository = run["repositories"][repo_id]
            repository["plan_path"] = str(output.resolve())
            repository["plan_sha256"] = _sha256(output)
            repository["design_challenge_required"] = artifact[
                "design_challenge_required"
            ]
            repository["design_challenge_path"] = None
            repository["design_challenge_sha256"] = None
            run.get("pending_plan_revisions", {}).pop(repo_id, None)
            self._save_run(run)

    def _schedule_plans(self, run: dict[str, Any]) -> list[Path]:
        assignments: list[Path] = []
        for repo_id, repository in run["repositories"].items():
            pending = run.get("pending_plan_revisions", {}).get(repo_id)
            basis = self._latest_plan_basis(repo_id)
            if pending is not None:
                previous_path = Path(pending["plan"]["path"])
                basis = (
                    pending["basis"]["kind"],
                    Path(pending["basis"]["artifact"]["path"]),
                )
            else:
                previous_path = (
                    Path(repository["plan_path"])
                    if repository.get("plan_path")
                    else None
                )
            if repository.get("plan_path") and basis is None:
                continue
            previous_plan = _load_json(previous_path) if previous_path else None
            revision = int(previous_plan.get("revision", 0)) + 1 if previous_plan else 1
            inputs = [Path(run["request_path"]), Path(run["requirements_path"])]
            if run.get("contract_path"):
                inputs.append(Path(run["contract_path"]))
            extras: dict[str, Any] = {"plan_revision": revision}
            if previous_path and basis:
                basis_kind, basis_path = basis
                inputs.extend([previous_path, basis_path])
                if basis_kind != "design-challenge":
                    extras["revision_basis"] = {
                        "kind": basis_kind,
                        "artifact": _reference(basis_path),
                    }
            assignments.append(
                self.build_assignment(
                    stage="plan",
                    repo_id=repo_id,
                    scope=f"v{revision}",
                    inputs=inputs,
                    instructions=[
                        "Produce the smallest outcome-oriented plan that covers every assigned requirement.",
                        "Group related tasks into bounded work packets and declare every risk and high-cost mechanism.",
                    ],
                    extras=extras,
                )
            )
        return assignments

    def _resolve_codebase_design_dir(self) -> Path:
        configured = os.environ.get("E2E_CODEBASE_DESIGN_DIR")
        if self.codebase_design_dir is not None:
            candidates = [self.codebase_design_dir]
        elif configured:
            candidates = [Path(configured).expanduser().resolve()]
        else:
            candidates = [
                self.skill_dir.parent / "codebase-design",
                Path.home() / ".pi" / "agent" / "skills" / "codebase-design",
                Path.home() / ".agents" / "skills" / "codebase-design",
                Path.home() / ".codex" / "skills" / "codebase-design",
            ]

        required_files = ("SKILL.md", "DEEPENING.md")
        for candidate in dict.fromkeys(path.resolve() for path in candidates):
            if all((candidate / name).is_file() for name in required_files):
                return candidate

        searched = ", ".join(str(path) for path in candidates)
        raise WorkflowError(
            "the codebase-design skill with SKILL.md and DEEPENING.md is required "
            f"for design challenges; searched: {searched}. Install it beside this skill "
            "or set E2E_CODEBASE_DESIGN_DIR."
        )

    def _challenge_inputs(self, run: dict[str, Any], repo_id: str) -> list[Path]:
        repository = run["repositories"][repo_id]
        codebase_dir = self._resolve_codebase_design_dir()
        paths = [
            Path(run["request_path"]),
            Path(run["requirements_path"]),
            Path(repository["plan_path"]),
            self.skill_dir / "SIMPLICITY-CHALLENGE.md",
            codebase_dir / "SKILL.md",
            codebase_dir / "DEEPENING.md",
        ]
        if run.get("contract_path"):
            paths.append(Path(run["contract_path"]))
        return paths

    def _plan_ready(self, run: dict[str, Any], repo_id: str) -> bool:
        repository = run["repositories"][repo_id]
        if not repository.get("plan_path"):
            return False
        plan = _load_json(Path(repository["plan_path"]))
        if not plan.get("design_challenge_required"):
            return True
        if not repository.get("design_challenge_path"):
            return False
        challenge = _load_json(Path(repository["design_challenge_path"]))
        return (
            challenge.get("verdict") == "accept"
            and challenge.get("plan", {}).get("sha256") == repository["plan_sha256"]
        )

    def phase_plan(self) -> str:
        run = self.load_run()
        plan_assignments = self._schedule_plans(run)
        if plan_assignments:
            artifacts = self._run_with_replacements(plan_assignments)
            if self.load_run()["status"] == "blocked":
                return "blocked"
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"
                self._accept_plan(artifact["repo_id"], artifact)

            run = self.load_run()
            discovered = sorted(
                set(run["risk_flags"])
                | {
                    risk
                    for repo_id in run["repositories"]
                    for risk in _load_json(
                        Path(run["repositories"][repo_id]["plan_path"])
                    )["risk_flags"]
                }
            )
            if any(
                _load_json(Path(repository["plan_path"]))["complexity_mechanisms"]
                for repository in run["repositories"].values()
            ):
                discovered = sorted(set(discovered) | {"high-cost-mechanism"})
            policy = workflow_tools.workflow_policy(
                repository_count=len(run["repositories"]),
                risk_flags=discovered,
                requested_profile=run["profile"],
                report_requested=run["workflow_policy"]["report_required"],
            )
            with RunLock(self.run_dir):
                current = self.load_run()
                current["risk_flags"] = discovered
                self._save_run(current)
            run = self.load_run()
            profile_order = {"fast": 0, "standard": 1, "full": 2}
            if profile_order[policy["profile"]] > profile_order[run["profile"]]:
                escalation = self._write_profile_escalation(run["profile"], policy)
                with RunLock(self.run_dir):
                    run = self.load_run()
                    run.update(policy)
                    run["profile_escalation"] = escalation
                    run["contract_path"] = None
                    run["contract_sha256"] = None
                    pending = run.setdefault("pending_plan_revisions", {})
                    for repo_id, repository in run["repositories"].items():
                        if repository.get("plan_path"):
                            pending[repo_id] = {
                                "plan": {
                                    "path": repository["plan_path"],
                                    "sha256": repository["plan_sha256"],
                                },
                                "basis": {
                                    "kind": "profile-escalation",
                                    "artifact": escalation,
                                },
                            }
                        repository["plan_path"] = None
                        repository["plan_sha256"] = None
                        repository["design_challenge_path"] = None
                        repository["design_challenge_sha256"] = None
                    run["phase"] = (
                        "contract"
                        if policy["workflow_policy"]["contract_required"]
                        else "plan"
                    )
                    for repository in run["repositories"].values():
                        repository["stage"] = run["phase"]
                    self._save_run(run)
                self._append_event(
                    "phase-changed",
                    reason="profile-escalated",
                    next_action=self.load_run()["phase"],
                )
                return self.load_run()["phase"]

        run = self.load_run()
        challenge_assignments: list[Path] = []
        for repo_id, repository in run["repositories"].items():
            if not repository.get("plan_path"):
                continue
            plan = _load_json(Path(repository["plan_path"]))
            if not plan["design_challenge_required"]:
                continue
            current_challenge = repository.get("design_challenge_path")
            if current_challenge:
                challenge = _load_json(Path(current_challenge))
                if challenge.get("plan", {}).get("sha256") == repository["plan_sha256"]:
                    continue
            revision = plan["revision"]
            challenge_assignments.append(
                self.build_assignment(
                    stage="design-challenge",
                    repo_id=repo_id,
                    scope=f"v{revision}",
                    inputs=self._challenge_inputs(run, repo_id),
                    instructions=[
                        "Apply the pinned simplicity rubric and subtract unnecessary mechanisms.",
                        "Accept only when no actionable simplicity finding remains.",
                    ],
                )
            )
        if challenge_assignments:
            artifacts = self._run_with_replacements(challenge_assignments)
            if self.load_run()["status"] == "blocked":
                return "blocked"
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"
                if artifact["verdict"] == "accept":
                    assignment = _load_json(Path(artifact["assignment_path"]))
                    output = Path(assignment["output_artifact"])
                    with RunLock(self.run_dir):
                        run = self.load_run()
                        repository = run["repositories"][artifact["repo_id"]]
                        repository["design_challenge_path"] = str(output.resolve())
                        repository["design_challenge_sha256"] = _sha256(output)
                        self._save_run(run)
                elif artifact["verdict"] == "revise-plan":
                    revision_count = (
                        _load_json(
                            Path(
                                self.load_run()["repositories"][artifact["repo_id"]][
                                    "plan_path"
                                ]
                            )
                        )["revision"]
                        - 1
                    )
                    if (
                        revision_count
                        >= self.load_run()["retry_limits"]["plan_revision_cycles"]
                    ):
                        self._block_from_artifact(
                            {
                                **artifact,
                                "status": "blocked",
                                "blockers": artifact.get("blockers")
                                or [
                                    {
                                        "id": "BLOCK-PLAN-REVISION",
                                        "kind": "code",
                                        "summary": "Plan revision limit exhausted without an accepting challenge.",
                                        "evidence_path": _load_json(
                                            Path(artifact["assignment_path"])
                                        )["output_artifact"],
                                        "required_action": "Make a material product/design decision before resuming.",
                                    }
                                ],
                            }
                        )
                        return "blocked"
                elif artifact["verdict"] == "revise-contract":
                    self._set_phase("contract")
                    return "contract"
                else:
                    self._block_from_artifact(artifact)
                    return "blocked"
            return "plan"

        run = self.load_run()
        if not all(self._plan_ready(run, repo_id) for repo_id in run["repositories"]):
            return "plan"
        self._prepare_plan_review(run)
        return "plan-review"

    def _prepare_plan_review(self, run: dict[str, Any]) -> None:
        versions = [
            int(match.group(1))
            for path in self.run_dir.glob("plan-review-v*.md")
            if (match := re.fullmatch(r"plan-review-v([0-9]+)\.md", path.name))
        ]
        version = max(versions, default=0) + 1
        path = self.run_dir / f"plan-review-v{version}.md"
        lines = [
            f"# Plan review — {run['run_id']} (v{version})",
            "",
            "This bundle is complete and hash-pinned. Approval applies only to this exact bundle.",
            "",
            "## Requirements",
        ]
        requirements = _load_json(Path(run["requirements_path"]))
        for requirement in requirements["requirements"]:
            lines.append(
                f"- **{requirement['id']}** ({', '.join(requirement['repository_ids'])}): "
                f"{requirement['source_text']}"
            )
            for criterion in requirement["acceptance_criteria"]:
                lines.append(f"  - {criterion}")
        if run.get("contract_path"):
            lines.extend(
                [
                    "",
                    "## Shared contract",
                    f"- Path: `{run['contract_path']}`",
                    f"- SHA-256: `{run['contract_sha256']}`",
                ]
            )
        plans: dict[str, Any] = {}
        for repo_id, repository in sorted(run["repositories"].items()):
            plan = _load_json(Path(repository["plan_path"]))
            lines.extend(
                [
                    "",
                    f"## Repository: {repo_id}",
                    f"- Plan: `{repository['plan_path']}`",
                    f"- Plan SHA-256: `{repository['plan_sha256']}`",
                    f"- Challenge: `{repository.get('design_challenge_path')}`",
                    f"- Challenge SHA-256: `{repository.get('design_challenge_sha256')}`",
                    f"- Risks: {', '.join(plan['risk_flags']) or 'none'}",
                    "- Tasks:",
                ]
            )
            for task in plan["tasks"]:
                lines.append(
                    f"  - **{task['id']}** [{', '.join(task['requirement_ids'])}]: {task['summary']}"
                )
            lines.append("- Work packets:")
            for packet in plan["work_packets"]:
                lines.append(
                    f"  - **{packet['id']}** ({packet['estimated_minutes']} min; "
                    f"tasks {', '.join(packet['task_ids'])}): {packet['summary']}"
                )
            lines.append("- Validation commands:")
            for validation in plan["validations"]:
                migration = (
                    " (migration-capable)" if validation["migration_capable"] else ""
                )
                lines.append(f"  - `{validation['command']}`{migration}")
            lines.append("- Complexity mechanisms:")
            if plan["complexity_mechanisms"]:
                for mechanism in plan["complexity_mechanisms"]:
                    lines.append(
                        f"  - **{mechanism['id']} / {mechanism['type']}**: {mechanism['summary']}"
                    )
            else:
                lines.append("  - none")
            lines.append(f"- Non-goals: {', '.join(plan['non_goals']) or 'none'}")
            plans[repo_id] = {
                "plan_path": repository["plan_path"],
                "plan_sha256": repository["plan_sha256"],
                "design_challenge_path": repository.get("design_challenge_path"),
                "design_challenge_sha256": repository.get("design_challenge_sha256"),
            }
        lines.extend(
            [
                "",
                "## Approval",
                "Approve all plans in this exact review bundle, or send the changes you want.",
            ]
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        review = {
            "status": "pending",
            "requested_at": self.now(),
            "review_path": str(path.resolve()),
            "review_sha256": _sha256(path),
            "contract_sha256": run.get("contract_sha256"),
            "plans": plans,
            "approved_at": None,
            "approval_text": None,
        }
        with RunLock(self.run_dir):
            current = self.load_run()
            current["phase"] = "plan-review"
            current["status"] = "awaiting-user"
            current["plan_review"] = review
            current["next_actions"] = []
            current["blockers"] = []
            for repository in current["repositories"].values():
                repository["stage"] = "plan-review"
                repository["status"] = "pending"
                repository["active_writer"] = None
            self._save_run(current)
        self._append_event(
            "plan-review-requested",
            artifact=str(path.resolve()),
            bundle_sha256=review["review_sha256"],
            next_action=None,
        )

    def plan_review_payload(self) -> dict[str, Any]:
        run = self.load_run()
        review = run.get("plan_review")
        if not isinstance(review, dict) or review.get("status") != "pending":
            raise WorkflowError("the run is not waiting for a plan-review decision")
        return {
            "kind": "plan-review",
            "run_id": run["run_id"],
            "review_path": review["review_path"],
            "review_sha256": review["review_sha256"],
            "prompt": "Approve all plans in this exact review bundle, or send the changes you want.",
        }

    def apply_plan_decision(self, decision: Mapping[str, Any]) -> str:
        run = self.load_run()
        review = run.get("plan_review")
        if not isinstance(review, dict) or review.get("status") != "pending":
            raise WorkflowError("no current pending plan review")
        if decision.get("review_sha256") != review["review_sha256"]:
            raise WorkflowError(
                "plan decision does not match the current bundle SHA-256"
            )
        text = str(decision.get("text", "")).strip()
        if not text:
            raise WorkflowError("plan decision text must not be empty")
        kind = decision.get("decision")
        if kind == "approve":
            if text.lower() in {"continue", "go on", "proceed", "yes", "ok", "okay"}:
                raise WorkflowError(
                    "generic continuation is not explicit whole-bundle approval"
                )
            if (
                NEGATED_APPROVAL_RE.search(text)
                or QUALIFIED_APPROVAL_RE.search(text)
                or not EXPLICIT_APPROVAL_RE.search(text)
            ):
                raise WorkflowError(
                    "approval text must explicitly and affirmatively approve all plans/the complete bundle"
                )
            with RunLock(self.run_dir):
                run = self.load_run()
                if run["plan_review"]["review_sha256"] != decision["review_sha256"]:
                    raise WorkflowError(
                        "the plan bundle changed while approval was being recorded"
                    )
                run["plan_review"]["status"] = "approved"
                run["plan_review"]["approved_at"] = self.now()
                run["plan_review"]["approval_text"] = text
                run["phase"] = "implement"
                run["status"] = "working"
                for repository in run["repositories"].values():
                    repository["stage"] = "implement"
                    repository["status"] = "pending"
                self._save_run(run)
            self._append_event(
                "plan-approved", approval_text=text, next_action="implement"
            )
            return "implement"
        if kind != "changes":
            raise WorkflowError("plan decision must be approve or changes")
        requested_repositories = decision.get("repository_ids")
        if requested_repositories is None:
            repository_ids = sorted(run["repositories"])
        else:
            repository_ids = sorted(set(str(item) for item in requested_repositories))
            unknown = set(repository_ids) - set(run["repositories"])
            if unknown or not repository_ids:
                raise WorkflowError(
                    f"invalid feedback repository IDs: {sorted(unknown)}"
                )
        version = len(list(self.run_dir.glob("plan-feedback-v*.json"))) + 1
        path = self.run_dir / f"plan-feedback-v{version}.json"
        feedback = {
            "schema_version": 1,
            "artifact_kind": "plan-feedback",
            "run_id": run["run_id"],
            "created_at": self.now(),
            "review_path": review["review_path"],
            "review_sha256": review["review_sha256"],
            "repository_ids": repository_ids,
            "text": text,
        }
        workflow_tools.atomic_write_json(path, feedback)
        with RunLock(self.run_dir):
            run = self.load_run()
            run["plan_feedback"] = {
                **_reference(path),
                "repository_ids": repository_ids,
            }
            run["plan_review"] = None
            run["phase"] = "plan"
            run["status"] = "working"
            for repo_id, repository in run["repositories"].items():
                repository["stage"] = "plan"
                repository["status"] = "pending"
                if repo_id in repository_ids:
                    repository["design_challenge_path"] = None
                    repository["design_challenge_sha256"] = None
            self._save_run(run)
        self._append_event(
            "plan-changes-requested",
            artifact=str(path.resolve()),
            repository_ids=repository_ids,
            next_action="plan",
        )
        return "plan"

    def phase_implement(self) -> str:
        run = self.load_run()
        approved = run.get("plan_review")
        if not isinstance(approved, dict) or approved.get("status") != "approved":
            raise WorkflowError("implementation requires the approved plan bundle")
        assignments: list[Path] = []
        all_complete = True
        completed_repositories: set[str] = set()
        completed_packets_by_repo: dict[str, set[str]] = {}
        for repo_id in run["repositories"]:
            plan_path, plan = self._current_plan(repo_id)
            completed = {
                packet_id
                for _path, artifact, assignment in self._artifacts(
                    repo_id=repo_id, stage="implement", kind="result"
                )
                if artifact.get("status") == "complete"
                and self._assignment_pins(assignment, plan_path, _sha256(plan_path))
                and isinstance((packet_id := artifact.get("packet_id")), str)
            }
            completed_packets_by_repo[repo_id] = completed
            if len(completed) == len(plan["work_packets"]):
                completed_repositories.add(repo_id)
        contract_dependencies: dict[str, set[str]] = {
            repo: set() for repo in run["repositories"]
        }
        if run.get("contract_path"):
            contract = _load_json(Path(run["contract_path"]))
            for dependency in contract.get("dependencies", []):
                contract_dependencies[dependency["from_repo_id"]].add(
                    dependency["to_repo_id"]
                )

        for repo_id in sorted(run["repositories"]):
            plan_path, plan = self._current_plan(repo_id)
            completed = completed_packets_by_repo[repo_id]
            if len(completed) == len(plan["work_packets"]):
                continue
            all_complete = False
            if not contract_dependencies[repo_id] <= completed_repositories:
                continue
            eligible = [
                packet
                for packet in plan["work_packets"]
                if packet["id"] not in completed
                and set(packet["depends_on"]) <= completed
            ]
            if not eligible:
                continue
            packet = sorted(eligible, key=lambda item: item["id"])[0]
            validations = {
                task_validation
                for task in plan["tasks"]
                if task["id"] in packet["task_ids"]
                for task_validation in task["validation_ids"]
            }
            commands = [
                validation["command"]
                for validation in plan["validations"]
                if validation["id"] in validations
            ]
            assignments.append(
                self.build_assignment(
                    stage="implement",
                    repo_id=repo_id,
                    scope=packet["id"],
                    inputs=self._canonical_inputs(run, repo_id),
                    instructions=[
                        "Execute exactly the approved work packet and record any bounded plan deviation.",
                        "Stop rather than introduce an undeclared high-cost mechanism or material contract change.",
                    ],
                    validation_commands=commands,
                    task_ids=packet["task_ids"],
                    packet_id=packet["id"],
                )
            )
        if assignments:
            artifacts = self._run_with_replacements(assignments)
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"
            return "implement"
        if all_complete:
            self._set_phase("validate")
            return "validate"
        self._block(
            summary="No implementation packet is eligible although work remains.",
            evidence_path=self.run_path,
            required_action="Resolve the contract or packet dependency graph.",
            kind="dependency",
        )
        return "blocked"

    def _validation_assignment(self, repo_id: str, scope: str) -> Path:
        run = self.load_run()
        if not self._migration_guard(repo_id):
            raise WorkflowError("migration target evidence is required")
        fingerprint = workflow_tools.worktree_fingerprint(
            Path(run["repositories"][repo_id]["worktree"])
        )
        plan_path, _ = self._current_plan(repo_id)
        latest_writer = self._latest_writer_artifact(repo_id)
        context_material = (
            f"{fingerprint}:validation-ids-v1:{plan_path}:{_sha256(plan_path)}"
        )
        if latest_writer is not None:
            context_material += f":{latest_writer[0]}:{_sha256(latest_writer[0])}"
        context_hash = hashlib.sha256(context_material.encode()).hexdigest()[:12]
        return self.build_assignment(
            stage="validate",
            repo_id=repo_id,
            scope=f"{scope}-{context_hash}",
            inputs=self._canonical_inputs(run, repo_id),
            instructions=[
                "Run every assigned focused and broad check once and preserve full output in logs.",
                "Use the exact assigned validation ID for each planned command.",
                "Reuse evidence only when validation ID, exact command hash, and tree fingerprint match.",
            ],
            validation_commands=self._plan_commands(repo_id),
            validation_ids=self._plan_validation_ids(repo_id),
        )

    def _failed_validation_ids(self, artifact: dict[str, Any]) -> list[str]:
        return sorted(
            record["id"]
            for record in artifact.get("validations", [])
            if record.get("result") not in {"pass"}
        )

    def _run_validation_wave(
        self, repo_ids: Iterable[str], scope: str
    ) -> Literal["pass", "again", "blocked"]:
        ordered_repo_ids = sorted(set(repo_ids))
        missing_assignments: list[Path] = []
        for repo_id in ordered_repo_ids:
            if self._current_validation(repo_id, require_pass=False) is None:
                if not self._migration_guard(repo_id):
                    return "blocked"
                missing_assignments.append(self._validation_assignment(repo_id, scope))
        if missing_assignments:
            artifacts = self._run_with_replacements(missing_assignments)
            if self.load_run()["status"] == "blocked":
                return "blocked"
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"

        fix_assignments: list[Path] = []
        for repo_id in ordered_repo_ids:
            current_any = self._current_validation(repo_id, require_pass=False)
            if current_any is None:
                self._block(
                    summary=(
                        f"Validation for {repo_id} did not cover the current tree "
                        "and planned checks."
                    ),
                    evidence_path=self.run_path,
                    required_action="Correct the validation evidence before resuming.",
                    repo_id=repo_id,
                )
                return "blocked"
            _, validation, _ = current_any
            failed_ids = self._failed_validation_ids(validation)
            if not failed_ids:
                continue
            fixes = self._artifacts(
                repo_id=repo_id, stage="validation-fix", kind="result"
            )
            limit = self.load_run()["retry_limits"]["validation_fix_cycles"]
            if len(fixes) >= limit:
                self._block(
                    summary=(
                        f"Validation fix cycles exhausted for {repo_id}: "
                        f"{', '.join(failed_ids)}."
                    ),
                    evidence_path=Path(
                        _load_json(Path(validation["assignment_path"]))[
                            "output_artifact"
                        ]
                    ),
                    required_action=(
                        "Make a concrete recovery decision; automatic validation "
                        "fixes are exhausted."
                    ),
                    repo_id=repo_id,
                )
                return "blocked"
            fix_assignments.append(
                self.build_assignment(
                    stage="validation-fix",
                    repo_id=repo_id,
                    scope=f"cycle-{len(fixes) + 1}",
                    inputs=self._canonical_inputs(self.load_run(), repo_id),
                    instructions=[
                        "Fix all compatible assigned validation failures in one batch.",
                        "Do not broaden product scope or introduce a new mechanism.",
                    ],
                    validation_commands=self._plan_commands(repo_id),
                    validation_ids=failed_ids,
                )
            )
        if fix_assignments:
            artifacts = self._run_with_replacements(fix_assignments)
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"
            return "again"
        return "pass"

    def phase_validate(self) -> str:
        outcome = self._run_validation_wave(
            self.load_run()["repositories"], "pre-review"
        )
        if outcome == "blocked":
            return "blocked"
        if outcome == "again":
            return "validate"
        self._set_phase("review-1")
        return "review-1"

    def _review_assignment(
        self, repo_id: str, round_number: int, finding_ids: list[str]
    ) -> Path:
        stage = f"review-{round_number}"
        return self.build_assignment(
            stage=stage,
            repo_id=repo_id,
            scope=f"round-{round_number}",
            inputs=self._canonical_inputs(self.load_run(), repo_id),
            instructions=[
                "Review the complete baseline-to-worktree change independently."
                if round_number == 1
                else "Verify only the assigned findings, their fixes, and affected hunks.",
                "Report actionable correctness/spec findings without duplicating passing tool output.",
            ],
            finding_ids=finding_ids,
        )

    def phase_review_1(self) -> str:
        run = self.load_run()
        assignments = [
            self._review_assignment(repo_id, 1, [])
            for repo_id in sorted(run["repositories"])
            if self._latest_review(repo_id, 1) is None
        ]
        if assignments:
            artifacts = self._run_with_replacements(assignments)
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"
            return "review-1"
        for repo_id in run["repositories"]:
            review = self._latest_review(repo_id, 1)
            if review is not None and self._must_fix(review[1]):
                self._set_phase("fix-1")
                return "fix-1"
        return self._after_reviews()

    def _fix_complete(self, repo_id: str, stage: str, finding_ids: list[str]) -> bool:
        for _path, artifact, assignment in reversed(
            self._artifacts(repo_id=repo_id, stage=stage, kind="result")
        ):
            if (
                artifact.get("status") == "complete"
                and assignment.get("finding_ids") == finding_ids
            ):
                return True
        return False

    def _phase_fix(self, round_number: int) -> str:
        stage = f"fix-{round_number}"
        run = self.load_run()
        assignments: list[Path] = []
        for repo_id in sorted(run["repositories"]):
            review_item = self._latest_review(repo_id, round_number)
            if review_item is None:
                continue
            findings = self._must_fix(review_item[1])
            ids = [finding["id"] for finding in findings]
            if ids and not self._fix_complete(repo_id, stage, ids):
                assignments.append(
                    self.build_assignment(
                        stage=stage,
                        repo_id=repo_id,
                        scope="all-findings",
                        inputs=self._canonical_inputs(run, repo_id),
                        instructions=[
                            "Resolve every assigned must-fix finding in one compatible batch.",
                            "Run affected checks once after all fixes and record every resolution.",
                        ],
                        validation_commands=self._plan_commands(repo_id),
                        finding_ids=ids,
                    )
                )
        if assignments:
            artifacts = self._run_with_replacements(assignments)
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"
            return stage
        outcome = self._run_validation_wave(run["repositories"], f"post-{stage}")
        if outcome == "blocked":
            return "blocked"
        if outcome == "again":
            return stage
        if round_number == 1 and self._needs_second_review():
            self._set_phase("review-2")
            return "review-2"
        return self._after_reviews()

    def phase_fix_1(self) -> str:
        return self._phase_fix(1)

    def _needs_second_review(self) -> bool:
        run = self.load_run()
        if run["workflow_policy"]["second_review"] == "never":
            return False
        for repo_id in run["repositories"]:
            review = self._latest_review(repo_id, 1)
            if review is None:
                continue
            must_fix = self._must_fix(review[1])
            if any(finding["severity"] in {"critical", "high"} for finding in must_fix):
                return True
            if must_fix and self._current_plan(repo_id)[1]["risk_flags"]:
                return True
        return False

    def phase_review_2(self) -> str:
        assignments: list[Path] = []
        for repo_id in sorted(self.load_run()["repositories"]):
            round_one = self._latest_review(repo_id, 1)
            if round_one is None:
                continue
            ids = [finding["id"] for finding in self._must_fix(round_one[1])]
            if ids and self._latest_review(repo_id, 2) is None:
                assignments.append(self._review_assignment(repo_id, 2, ids))
        if assignments:
            artifacts = self._run_with_replacements(assignments)
            for artifact in artifacts:
                if artifact.get("status") != "complete":
                    self._block_from_artifact(artifact)
                    return "blocked"
            return "review-2"
        if any(
            review is not None and self._must_fix(review[1])
            for repo_id in self.load_run()["repositories"]
            if (review := self._latest_review(repo_id, 2)) is not None
        ):
            self._set_phase("fix-2")
            return "fix-2"
        return self._after_reviews()

    def phase_fix_2(self) -> str:
        outcome = self._phase_fix(2)
        if outcome == "fix-2":
            return outcome
        if outcome == "blocked":
            return outcome
        return outcome

    def _after_reviews(self) -> str:
        run = self.load_run()
        next_phase = (
            "integrate" if run["workflow_policy"]["integration_required"] else "deliver"
        )
        self._set_phase(next_phase)
        return next_phase

    def phase_integrate(self) -> str:
        existing = [
            item
            for item in self._artifacts(kind="integration")
            if item[1].get("status") == "complete"
        ]
        if not existing:
            run = self.load_run()
            assignment = self.build_assignment(
                stage="integrate",
                repo_id=None,
                scope="final",
                inputs=self._canonical_inputs(run, None),
                instructions=[
                    "Verify every requirement, interface, repository, rollout constraint, and declared mechanism.",
                    "Use only final worktrees and accepted evidence; do not edit project files.",
                ],
            )
            artifacts = self._run_with_replacements([assignment])
            artifact = artifacts[-1]
            if artifact.get("status") != "complete":
                self._block_from_artifact(artifact)
                return "blocked"
            return "integrate"
        self._set_phase("deliver")
        return "deliver"

    def _latest_delivery(
        self, repo_id: str
    ) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
        values = self._artifacts(repo_id=repo_id, stage="deliver", kind="delivery")
        complete = [item for item in values if item[1].get("status") == "complete"]
        return complete[-1] if complete else None

    def _pipeline_fix_count(self, repo_id: str) -> int:
        return len(
            self._artifacts(repo_id=repo_id, stage="pipeline-fix", kind="result")
        )

    def phase_deliver(self) -> str:
        run = self.load_run()
        assignments: list[Path] = []
        for repo_id in sorted(run["repositories"]):
            if self._latest_delivery(repo_id) is not None:
                continue
            attempts = (
                len(self._artifacts(repo_id=repo_id, stage="deliver", kind="delivery"))
                + 1
            )
            assignments.append(
                self.build_assignment(
                    stage="deliver",
                    repo_id=repo_id,
                    scope=f"cycle-{attempts}",
                    attempt=1,
                    inputs=self._canonical_inputs(run, repo_id),
                    instructions=[
                        "Audit the baseline diff, commit only task changes, push, and create or update the PR.",
                        "Wait for required checks; block on authentication, permission, or infrastructure failures.",
                    ],
                )
            )
        if assignments:
            artifacts = self._run_with_replacements(assignments)
            pipeline_fix_assignments: list[Path] = []
            for artifact in artifacts:
                if artifact.get("status") == "complete":
                    continue
                code_blockers = [
                    blocker
                    for blocker in artifact.get("blockers", [])
                    if blocker["kind"] == "code"
                ]
                repo_id = artifact["repo_id"]
                count = self._pipeline_fix_count(repo_id)
                limit = self.load_run()["retry_limits"]["pipeline_fix_cycles"]
                if code_blockers and count < limit:
                    pipeline_fix_assignments.append(
                        self.build_assignment(
                            stage="pipeline-fix",
                            repo_id=repo_id,
                            scope=f"cycle-{count + 1}",
                            inputs=self._canonical_inputs(self.load_run(), repo_id),
                            instructions=[
                                "Fix all compatible change-related pipeline failures in one batch.",
                                "Run affected local validation once; do not modify delivery/Git state.",
                            ],
                            validation_commands=self._plan_commands(repo_id),
                        )
                    )
                    continue
                self._block_from_artifact(artifact)
                return "blocked"
            if pipeline_fix_assignments:
                fixes = self._run_with_replacements(pipeline_fix_assignments)
                for fix in fixes:
                    if fix.get("status") != "complete":
                        self._block_from_artifact(fix)
                        return "blocked"
            return "deliver"

        # Delivery changes HEAD. Re-key validation to the committed tree before completion.
        outcome = self._run_validation_wave(run["repositories"], "post-delivery")
        if outcome == "blocked":
            return "blocked"
        if outcome == "again":
            return "deliver"
        next_phase = (
            "report" if run["workflow_policy"]["report_required"] else "complete"
        )
        self._set_phase(next_phase)
        return next_phase

    def phase_report(self) -> str:
        run = self.load_run()
        reports = self._artifacts(kind="report")
        if not reports:
            assignment = self.build_assignment(
                stage="report",
                repo_id=None,
                scope="final",
                inputs=self._canonical_inputs(run, None),
                instructions=["Render accepted artifacts deterministically."],
            )
            assignment_data = _load_json(assignment)
            stamp = self.now().replace(":", "").replace("-", "")
            html_path = self.report_root / f"{_slug(run['run_id'])}-{stamp}.html"
            report = workflow_tools.render_report(
                run_dir=self.run_dir,
                assignment_path=assignment,
                html_path=html_path,
                output_path=Path(assignment_data["output_artifact"]),
            )
            with RunLock(self.run_dir):
                current = self.load_run()
                self._record_accepted_reference(
                    current, assignment_data, Path(assignment_data["output_artifact"])
                )
                self._save_run(current)
            self._append_event(
                "artifact-accepted",
                action_id=assignment_data["action_id"],
                artifact=assignment_data["output_artifact"],
                next_action=None,
            )
            if report.get("status") != "complete":
                self._block_from_artifact(report)
                return "blocked"
        self._set_phase("complete")
        return "complete"

    def phase_complete(self) -> str:
        run = self.load_run()
        if run["next_actions"] or run["blockers"]:
            raise WorkflowError("completion audit found pending actions or blockers")
        unclosed_agents = [
            agent["name"]
            for agent in self.load_agents()["agents"]
            if agent["status"] in {"starting", "working", "blocked", "idle"}
            or agent.get("cleanup_status") in {"pending", "retained", "failed"}
            or agent.get("pane_closed") is False
        ]
        if unclosed_agents:
            raise WorkflowError(
                "completion audit found workflow worker handles still open: "
                + ", ".join(sorted(unclosed_agents))
            )
        for repo_id, repository in run["repositories"].items():
            if repository.get("active_writer") is not None:
                raise WorkflowError(
                    f"completion audit found an active writer for {repo_id}"
                )
            if self._latest_delivery(repo_id) is None:
                raise WorkflowError(
                    f"completion audit found no successful delivery for {repo_id}"
                )
            if self._current_validation(repo_id, require_pass=True) is None:
                raise WorkflowError(
                    f"completion audit found stale validation for {repo_id}"
                )
        metrics = workflow_tools.run_metrics(self.run_dir)
        workflow_tools.atomic_write_json(self.run_dir / "metrics.json", metrics)
        with RunLock(self.run_dir):
            run = self.load_run()
            run["phase"] = "complete"
            run["status"] = "complete"
            run["next_actions"] = []
            run["blockers"] = []
            for repository in run["repositories"].values():
                repository["stage"] = "complete"
                repository["status"] = "complete"
                repository["active_writer"] = None
            self._save_run(run)
        self._append_event(
            "completed", artifact=str(self.run_dir / "metrics.json"), next_action=None
        )
        return "complete"

    # LangGraph uses this node directly because interrupt must remain outside
    # error-catching code and must be the first operation in the node.
    def phase_plan_review(self, decision: Mapping[str, Any]) -> str:
        return self.apply_plan_decision(decision)

    # ---------- Coordinator-owned bootstrap and safety evidence ----------

    @classmethod
    def initialize(
        cls,
        *,
        spec_path: Path,
        run_dir: Path,
        skill_dir: Path | None = None,
        codebase_design_dir: Path | None = None,
        batch_runner: BatchRunner = _default_batch_runner,
        worker_runtime: str = "auto",
        report_root: Path | None = None,
        now: Callable[[], str] = workflow_tools.utc_now,
    ) -> "WorkflowEngine":
        run_dir = run_dir.resolve()
        if run_dir.exists() and any(run_dir.iterdir()):
            raise WorkflowError(f"run directory is not empty: {run_dir}")
        spec = _load_json(spec_path)
        request = str(spec.get("request", "")).strip()
        requirements_input = spec.get("requirements")
        repositories_input = spec.get("repositories")
        if (
            not request
            or not isinstance(requirements_input, list)
            or not requirements_input
        ):
            raise WorkflowError(
                "bootstrap spec requires request and non-empty requirements"
            )
        if not isinstance(repositories_input, list) or not repositories_input:
            raise WorkflowError("bootstrap spec requires non-empty repositories")
        run_dir.mkdir(parents=True, exist_ok=True)
        for directory in ("assignments", "logs", "supervisor"):
            (run_dir / directory).mkdir()
        run_id = str(spec.get("run_id") or run_dir.name)
        created_at = now()
        request_path = run_dir / "request.md"
        request_path.write_text(request + "\n", encoding="utf-8")

        repositories: dict[str, Any] = {}
        seen_worktrees: set[Path] = set()
        for raw in sorted(repositories_input, key=lambda value: value["repo_id"]):
            repo_id = str(raw["repo_id"])
            if not artifact_guard.ID_RE.fullmatch(repo_id):
                raise WorkflowError(f"invalid repository ID: {repo_id}")
            if repo_id in repositories:
                raise WorkflowError(f"duplicate repository ID: {repo_id}")
            root = Path(raw["root"]).resolve()
            worktree = Path(raw["worktree"]).resolve()
            if not root.is_dir() or not worktree.is_dir():
                raise WorkflowError(f"repository/worktree does not exist for {repo_id}")
            if root == worktree or not (worktree / ".git").is_file():
                raise WorkflowError(
                    f"{repo_id} must use a dedicated Git worktree with a .git file"
                )
            if worktree in seen_worktrees:
                raise WorkflowError(f"duplicate worktree path: {worktree}")
            seen_worktrees.add(worktree)
            _git(root, "rev-parse", "--show-toplevel")
            baseline = _git(worktree, "rev-parse", "HEAD")
            branch = _git(worktree, "branch", "--show-current")
            expected_branch = str(raw.get("branch") or branch)
            if branch != expected_branch:
                raise WorkflowError(
                    f"worktree branch mismatch for {repo_id}: expected {expected_branch}, got {branch}"
                )
            artifact_dir = run_dir / "repos" / repo_id
            log_dir = artifact_dir / "logs"
            log_dir.mkdir(parents=True)
            initial_status_value = _git(worktree, "status", "--short")
            if initial_status_value:
                raise WorkflowError(
                    f"dedicated worktree for {repo_id} must be clean before initialization"
                )
            initial_status = artifact_dir / "initial-status.txt"
            initial_status.write_text(initial_status_value + "\n", encoding="utf-8")
            repositories[repo_id] = {
                "root": str(root),
                "worktree": str(worktree),
                "artifact_dir": str(artifact_dir.resolve()),
                "base_branch": str(raw.get("base_branch") or "main"),
                "branch": expected_branch,
                "baseline": baseline,
                "initial_status_path": str(initial_status.resolve()),
                "stage": "bootstrap",
                "status": "pending",
                "active_writer": None,
                "plan_path": None,
                "plan_sha256": None,
                "design_challenge_required": False,
                "design_challenge_path": None,
                "design_challenge_sha256": None,
                "accepted_artifacts": {},
            }

        normalized_requirements = []
        for index, raw in enumerate(requirements_input, start=1):
            normalized_requirements.append(
                {
                    "id": str(raw.get("id") or f"REQ-{index:03d}"),
                    "source_text": str(raw["source_text"]),
                    "acceptance_criteria": list(raw["acceptance_criteria"]),
                    "repository_ids": sorted(raw["repository_ids"]),
                }
            )
        known_repositories = set(repositories)
        for requirement in normalized_requirements:
            unknown = set(requirement["repository_ids"]) - known_repositories
            if unknown:
                raise WorkflowError(
                    f"requirement {requirement['id']} references unknown repositories: "
                    f"{sorted(unknown)}"
                )

        requirements_path = run_dir / "requirements.json"
        requirements = {
            "schema_version": 1,
            "artifact_kind": "requirements",
            "run_id": run_id,
            "created_at": created_at,
            "requirements": sorted(
                normalized_requirements, key=lambda value: value["id"]
            ),
            "constraints": list(spec.get("constraints", [])),
        }
        workflow_tools.atomic_write_json(requirements_path, requirements)
        artifact_guard.validate_requirements(requirements)
        policy = workflow_tools.workflow_policy(
            repository_count=len(repositories),
            risk_flags=spec.get("risk_flags", []),
            requested_profile=spec.get("profile", "auto"),
            report_requested=bool(spec.get("report_requested", False)),
        )
        run = {
            "schema_version": 1,
            "artifact_kind": "run",
            "run_id": run_id,
            "created_at": created_at,
            "updated_at": created_at,
            "status": "working",
            "phase": "bootstrap",
            **policy,
            "request_path": str(request_path.resolve()),
            "request_sha256": _sha256(request_path),
            "requirements_path": str(requirements_path.resolve()),
            "requirements_sha256": _sha256(requirements_path),
            "contract_path": None,
            "contract_sha256": None,
            "plan_review": None,
            "retry_limits": {
                "worker_replacements_per_stage": 1,
                "contract_revisions": 1,
                "plan_revision_cycles": 1,
                "validation_fix_cycles": 2,
                "review_rounds": 2,
                "pipeline_fix_cycles": 2,
            },
            "repositories": repositories,
            "accepted_artifacts": {},
            "next_actions": [],
            "blockers": [],
        }
        agents = {
            "schema_version": 1,
            "artifact_kind": "agents",
            "run_id": run_id,
            "updated_at": created_at,
            "agents": [],
        }
        workflow_tools.atomic_write_json(run_dir / "run.json", run)
        workflow_tools.atomic_write_json(run_dir / "agents.json", agents)
        (run_dir / "events.jsonl").write_text("", encoding="utf-8")
        engine = cls(
            run_dir,
            skill_dir=skill_dir,
            codebase_design_dir=codebase_design_dir,
            batch_runner=batch_runner,
            worker_runtime=worker_runtime,
            report_root=report_root,
            now=now,
        )
        artifact_guard.validate_run(run)
        artifact_guard.validate_agents(agents)
        engine._append_event(
            "run-created", artifact=str(spec_path.resolve()), next_action="bootstrap"
        )
        return engine

    def record_database_target(
        self,
        *,
        repo_id: str,
        classification: str,
        description: str,
    ) -> Path:
        if classification not in {"isolated-local", "isolated-test"}:
            raise WorkflowError(
                "database target must be classified isolated-local or isolated-test; "
                "production, staging, shared, and ambiguous targets are forbidden"
            )
        description = description.strip()
        if not description or len(description) > 1000:
            raise WorkflowError(
                "database target description must contain 1-1000 characters"
            )
        if "://" in description or re.search(
            r"\b(database_url|password|passwd|secret|token)\s*[:=]",
            description,
            re.IGNORECASE,
        ):
            raise WorkflowError(
                "database target description appears to contain a URL or credential; "
                "record only non-secret classification evidence"
            )
        run = self.load_run()
        if repo_id not in run["repositories"]:
            raise WorkflowError(f"unknown repository: {repo_id}")
        path = self.run_dir / "repos" / repo_id / "database-target.json"
        value = {
            "schema_version": 1,
            "artifact_kind": "database-target",
            "run_id": run["run_id"],
            "repo_id": repo_id,
            "created_at": self.now(),
            "classification": classification,
            "description": description,
            "secrets_recorded": False,
        }
        workflow_tools.atomic_write_json(path, value)
        with RunLock(self.run_dir):
            run = self.load_run()
            run["repositories"][repo_id]["database_target_evidence"] = _reference(path)
            if run["status"] == "blocked" and any(
                "database target" in blocker["summary"].lower()
                for blocker in run["blockers"]
            ):
                run["status"] = "working"
                run["blockers"] = []
                run["repositories"][repo_id]["status"] = "pending"
            self._save_run(run)
        return path


def build_graph(engine: WorkflowEngine, checkpointer: Any) -> Any:
    """Compile the only executable phase graph for this workflow."""
    builder: Any = StateGraph(WorkflowState)

    def reconcile_node(state: WorkflowState) -> dict[str, str]:
        phase = engine.reconcile()
        return {
            "run_dir": str(engine.run_dir),
            "last_transition": f"reconciled:{phase}",
        }

    def route_after_reconcile(state: WorkflowState) -> str:
        run = engine.load_run()
        if run["status"] in {"blocked", "failed", "complete"}:
            return "terminal"
        attempts = len(engine.load_agents()["agents"]) - state.get(
            "attempt_baseline", 0
        )
        if (
            run["status"] == "working"
            and attempts >= run["workflow_policy"]["coordinator_attempt_budget"]
        ):
            return "budget_checkpoint"
        return PHASE_NODE[run["phase"]]

    builder.add_node("reconcile", reconcile_node)

    def terminal_node(state: WorkflowState) -> dict[str, str]:
        del state
        return {"outcome": engine.load_run()["status"]}

    def budget_checkpoint_node(state: WorkflowState) -> dict[str, str]:
        del state
        return {
            "outcome": "budget-checkpoint",
            "last_transition": "coordinator-attempt-budget",
        }

    builder.add_node("terminal", terminal_node)
    builder.add_node("budget_checkpoint", budget_checkpoint_node)

    for phase, node_name in PHASE_NODE.items():
        if phase == "plan-review":
            continue

        def make_node(current_phase: str) -> Callable[[WorkflowState], dict[str, str]]:
            def node(state: WorkflowState) -> dict[str, str]:
                del state
                outcome = engine.execute_phase(current_phase)
                return {
                    "last_transition": f"{current_phase}:{outcome}",
                    "outcome": outcome,
                }

            return node

        builder.add_node(node_name, make_node(phase))

    def plan_review_node(state: WorkflowState) -> dict[str, str]:
        # Must remain first: LangGraph restarts this node on resume.
        del state
        decision = interrupt(engine.plan_review_payload())
        outcome = engine.phase_plan_review(decision)
        return {"last_transition": f"plan-review:{outcome}", "outcome": outcome}

    builder.add_node("plan_review", plan_review_node)
    builder.add_edge(START, "reconcile")
    builder.add_conditional_edges(
        "reconcile",
        route_after_reconcile,
        {
            **{node: node for node in PHASE_NODE.values()},
            "terminal": "terminal",
            "budget_checkpoint": "budget_checkpoint",
        },
    )
    for node_name in PHASE_NODE.values():
        if node_name == "complete":
            builder.add_edge(node_name, END)
        else:
            builder.add_edge(node_name, "reconcile")
    builder.add_edge("terminal", END)
    builder.add_edge("budget_checkpoint", END)
    return builder.compile(checkpointer=checkpointer)
