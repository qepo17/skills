"""Execute one allowlisted read-only check and preserve reusable validation facts."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import artifact_guard
import workflow_tools


def reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_assignment_pin(assignment_path: Path, *, required: bool = False) -> None:
    """Check coordinator-owned intent before trusting a potentially changed file."""
    run = workflow_tools.load_json(assignment_path.parent.parent / "run.json")
    pins = [ref for ref in run.get("coordinator_validation_assignments", {}).values()
            if Path(ref["path"]).resolve() == assignment_path.resolve()]
    if (required and not pins) or (pins and pins != [reference(assignment_path)]):
        raise artifact_guard.ValidationError("immutable coordinator validation assignment changed or is unpinned")


def execute(assignment_path: Path) -> None:
    """Never execute arbitrary plan strings, rewrite source evidence, or rerun suites.

    The durable command result is reusable after a crash even if the final result
    artifact was not yet written. A crash before capture may repeat only this
    read-only command, never an implementation/fix worker.
    """
    verify_assignment_pin(assignment_path, required=True)
    assignment = workflow_tools.load_json(assignment_path)
    artifact_guard.validate_assignment(assignment)
    context = assignment["coordinator_validation"]
    worktree = Path(assignment["cwd"])
    expected_state = context["repository_state"]
    if workflow_tools.repository_state(worktree) != expected_state:
        raise artifact_guard.ValidationError("coordinator check repository/Git state changed before execution")
    output = Path(assignment["output_artifact"])
    if output.exists():
        return  # Acceptance checks it; an invalid output is never overwritten.
    log_dir = Path(assignment["log_dir"])
    evidence_path = log_dir / f"{output.stem}-command.json"
    if not evidence_path.exists():
        result = subprocess.run(
            ["git", "diff", "--check"], cwd=worktree, capture_output=True,
            text=True, check=False, timeout=60,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        log_path = log_dir / f"{output.stem}-{uuid4().hex}.log"
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode < 0 or workflow_tools.repository_state(worktree) != expected_state:
            raise artifact_guard.ValidationError("coordinator check did not settle on its pinned repository/Git state")
        workflow_tools.atomic_write_json(evidence_path, {
            "assignment": reference(assignment_path), "repository_state": expected_state,
            "argv": ["git", "diff", "--check"], "exit_code": result.returncode,
            "completed_at": artifact_guard._utc_now(), "log": reference(log_path),
        })
    artifact = artifact_guard.coordinator_check_artifact(assignment_path, assignment, reference(evidence_path))
    # The serial acceptance seam validates the full result and saved command
    # evidence. Do not touch the guard's process-global artifact cursor here:
    # independent repository commands may be executing concurrently.
    workflow_tools.atomic_write_json(output, artifact)
