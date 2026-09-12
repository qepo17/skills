"""Narrow, opt-in recovery of a timed-out writer / overwritten blocked handoff.

Never repair a hash in place or accept the late worker's result. Quarantine the
unavailable reference, preserve its replacement and the late output byte-for-byte,
and require the graph's one-shot read-only packet verification. This command owns
only the transition; all subsequent scheduling still belongs to LangGraph.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import artifact_guard
import worker_supervisor
import workflow_tools


def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def preserve(path: Path, content: bytes) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != content:
            raise ValueError(f"incident snapshot already exists with different bytes: {path}")
    return reference(path)


def recover(engine: Any, request: dict[str, Any], *, request_sha256: str,
            text: str, context: str | None = None, supervisor: Any = None) -> str:
    """Called under the CLI execution lock, before opening an invalid checkpoint."""
    if text.strip().lower() not in {"yes", "approved", "authorized"} or digest(request) != request_sha256:
        raise ValueError("explicit authorization of the exact incident request is required")
    required = {"run_id", "repo_id", "source_action_id", "damaged_action_id", "run_sha256",
                "source_sha256", "damaged_sha256", "plan_review_sha256", "repository_state"}
    if set(request) != required:
        raise ValueError("incident request must contain exactly the documented identity and hash fields")
    run_bytes = engine.run_path.read_bytes()
    run = json.loads(run_bytes)
    for ref in run.get("writer_incident_recoveries", {}).values():
        record = json.loads(Path(ref["path"]).read_text())
        if record["request_sha256"] == request_sha256:
            engine.load_run()
            return "already-applied"
    if reference(engine.run_path)["sha256"] != request["run_sha256"]:
        raise ValueError("run changed since incident inspection")
    repo_id, source_id, damaged_id = (request[k] for k in ("repo_id", "source_action_id", "damaged_action_id"))
    if (run["run_id"] != request["run_id"] or set(run["repositories"]) != {repo_id}
            or run["phase"] != "implement" or run["status"] not in {"working", "blocked"}
            or run.get("validation_policy_version") != 1 or run.get("delivery_policy_version") != 1
            or run.get("external_resume_generation", 0) < 1 or run.get("writer_incident_recoveries")
            or (run.get("worker_execution") or {}).get("backend") != "herdr"
            or (run.get("plan_review") or {}).get("status") != "approved"
            or run["plan_review"]["review_sha256"] != request["plan_review_sha256"]
            or any(a["action_id"] != damaged_id for a in run["next_actions"])):
        raise ValueError("not the authorized single-repository implementation incident")
    repo = run["repositories"][repo_id]
    invalidated = repo["accepted_artifacts"].get(damaged_id)
    if not invalidated or source_id in repo["accepted_artifacts"]:
        raise ValueError("requires an overwritten accepted replacement and an unaccepted late source result")
    # Strictly validate everything except this one unavailable hash. Its original
    # value is retained in the immutable incident record, not replaced by new bytes.
    projected = copy.deepcopy(run)
    del projected["repositories"][repo_id]["accepted_artifacts"][damaged_id]
    artifact_guard.validate_run(projected)
    assignments = {}
    for action_id in (source_id, damaged_id):
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", action_id).strip("-").lower()
        path = engine.run_dir / "assignments" / f"{slug}.json"
        if path.is_symlink() or not path.resolve().is_relative_to(engine.run_dir / "assignments"):
            raise ValueError("incident assignment must be a local immutable regular file")
        value = json.loads(path.read_text())
        artifact_guard.validate_assignment(value)
        if value["action_id"] != action_id or value.get("execution_mode", "worker") != "worker":
            raise ValueError("incident assignments must be original implementation workers")
        assignments[action_id] = (path, value)
    source_path, source = assignments[source_id]
    damaged_path, damaged = assignments[damaged_id]
    same = ("run_id", "repo_id", "stage", "cwd", "baseline", "packet_id", "task_ids", "validation_ids", "validation_commands")
    if (source["attempt"] != 1 or damaged["attempt"] != 2 or source["stage"] != "implement"
            or source["repo_id"] != repo_id or not source.get("packet_id")
            or any(source.get(k) != damaged.get(k) for k in same)
            or source.get("project_file_access") != "write" or damaged.get("project_file_access") != "write"
            or source["cwd"] != repo["worktree"]):
        raise ValueError("only attempts 1 and 2 of the same pinned source packet are recoverable")
    result_path, damaged_result_path = Path(source["output_artifact"]), Path(damaged["output_artifact"])
    for path, expected in ((result_path, request["source_sha256"]), (damaged_result_path, request["damaged_sha256"])):
        if path.is_symlink() or not path.resolve().is_relative_to(engine.run_dir) or reference(path)["sha256"] != expected:
            raise ValueError("incident output changed or escapes the run")
    if str(damaged_result_path) != invalidated["path"] or request["damaged_sha256"] == invalidated["sha256"]:
        raise ValueError("the accepted reference must actually be unavailable; normal runs use normal reconciliation")
    result, broken = (json.loads(p.read_text()) for p in (result_path, damaged_result_path))
    for artifact, assignment, path in ((result, source, source_path), (broken, damaged, damaged_path)):
        if (artifact.get("assignment_sha256") != reference(path)["sha256"]
                or any(artifact.get(k) != assignment.get(k) for k in ("run_id", "repo_id", "stage", "packet_id", "task_ids"))):
            raise ValueError("incident result does not match its immutable assignment")
    if (result.get("status") != "complete" or broken.get("status") != "blocked"
            or not broken.get("blockers") or any(b.get("kind") != "infrastructure" for b in broken["blockers"])
            or any(v.get("result") != "not-run" for v in broken["validations"])
            or {v["id"] for v in result["validations"]} != set(source["validation_ids"])
            or any(v.get("result") != "pass" for v in result["validations"])):
        raise ValueError("requires a late complete candidate and an infrastructure-blocked, unexecuted replacement")
    evidence = []
    timed_out = False
    for path in sorted((engine.run_dir / "supervisor").glob("manifest-*.json")):
        value = json.loads(path.read_text())
        matching = [w for w in value.get("workers", []) if w.get("action_id") in assignments]
        if matching:
            evidence.append(reference(path))
            timed_out |= any(w.get("action_id") == source_id and w.get("timed_out") is True
                             and w.get("settled") is False and w.get("cleanup_status") == "retained" for w in matching)
    if not timed_out:
        raise ValueError("missing immutable proof of the original retained timed-out handle")
    agents = engine.load_agents()
    expected = {a["name"]: repo["worktree"] for a in agents["agents"] if a.get("repo_id") == repo_id}
    if (not expected or any(a.get("backend") != "herdr" or a.get("cleanup_status") != "complete"
            for a in agents["agents"] if a.get("repo_id") == repo_id)):
        raise ValueError("settle all recorded handles first; this command only repairs proven Herdr identity loss")
    for path in sorted(workflow_tools.artifact_evidence_paths(result) | workflow_tools.artifact_evidence_paths(broken)):
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(engine.run_dir):
            raise ValueError("incident evidence must remain inside this run")
        evidence.append(reference(path))
    state = workflow_tools.repository_state(Path(repo["worktree"]))
    if (state != request["repository_state"] or state["head"] != result["git"]["head"] or state["branch"] != repo["branch"]
            or workflow_tools._git(Path(repo["worktree"]), "diff", "--cached", "--name-only")):
        raise ValueError("source candidate Git identity changed")
    directory = engine.run_dir / "logs" / "incidents" / f"writer-recovery-{request_sha256[:16]}"
    snapshots = {"run": preserve(directory / "run-before.json", run_bytes),
                 "agents": preserve(directory / "agents-before.json", engine.agents_path.read_bytes())}
    for action_id in assignments:
        path = engine.run_dir / "supervisor" / worker_supervisor.WorkerSupervisor.record_name(action_id)
        if path.exists():
            evidence.append(preserve(directory / path.name, path.read_bytes()))
    for name, path in (("late-source.json", result_path), ("overwritten-blocked.json", damaged_result_path)):
        evidence.append(preserve(directory / name, path.read_bytes()))
    if supervisor is None:
        supervisor = worker_supervisor.WorkerSupervisor(engine.run_dir,
            worker_supervisor.ExecutionContext("herdr", "pi", "authorized-writer-incident", {}))
    try:
        cleanup = supervisor.close_settled_incident_workers(expected)
    except RuntimeError as error:
        raise ValueError(str(error)) from error
    cleanup_bytes = (json.dumps(cleanup, indent=2, sort_keys=True) + "\n").encode()
    cleanup_ref = preserve(directory / f"cleanup-{hashlib.sha256(cleanup_bytes).hexdigest()[:16]}.json", cleanup_bytes)
    if (engine.run_path.read_bytes() != run_bytes or engine.agents_path.read_bytes() != Path(snapshots["agents"]["path"]).read_bytes()
            or workflow_tools.repository_state(Path(repo["worktree"])) != state
            or reference(result_path)["sha256"] != request["source_sha256"]
            or reference(damaged_result_path)["sha256"] != request["damaged_sha256"]):
        raise ValueError("run, outputs, or source changed during handle cleanup; recovery remains unapplied")
    record = {"schema_version": 1, "artifact_kind": "writer-incident-recovery", "run_id": run["run_id"],
        "action_id": damaged_id, "packet_id": source["packet_id"], "request_sha256": request_sha256,
        "authorization": {"text": text, "context": context, "recorded_at": engine.now()}, "identity_request": request,
        "request": {"repo_id": repo_id, "assignment": reference(source_path), "result": reference(result_path),
                    "damaged_assignment": reference(damaged_path), "damaged_result": reference(damaged_result_path)},
        "snapshots": snapshots, "invalidated_reference": invalidated, "historical_evidence": evidence,
        "cleanup": cleanup_ref, "previous_plan_review": run["plan_review"], "repository_states": {repo_id: state},
        "changed_files": sorted(set(result["changed_files"]) | set(broken["changed_files"]))}
    artifact_guard.validate_writer_incident_recovery(record, "$.writer_incident")
    record_ref = preserve(directory / "recovery.json", (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
    projected.setdefault("writer_incident_recoveries", {})[damaged_id] = record_ref
    projected["status"], projected["next_actions"], projected["blockers"] = "working", [], []
    projected["repositories"][repo_id]["active_writer"] = None
    projected["repositories"][repo_id]["status"] = "pending"
    # Approval, policy versions, baseline, assignments, accepted predecessors and
    # every attempt/review/fix allowance are copied unchanged. No packet completes.
    engine._save_run(projected)
    engine._append_event("resumed", reason="recover-writer-incident", artifact=record_ref["path"], next_action="implement")
    return "applied"
