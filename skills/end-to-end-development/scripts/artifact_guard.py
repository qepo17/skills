#!/usr/bin/env python3
"""Validate deterministic end-to-end-development run artifacts.

Uses only the Python standard library so every worker can validate its handoff
before returning control to the coordinator.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NoReturn

MAX_BYTES = {
    "run": 160 * 1024,
    "requirements": 64 * 1024,
    "agents": 128 * 1024,
    "assignment": 32 * 1024,
    "contract": 96 * 1024,
    "plan": 64 * 1024,
    "design-challenge": 64 * 1024,
    "result": 64 * 1024,
    "review": 64 * 1024,
    "integration": 96 * 1024,
    "delivery": 64 * 1024,
    "report": 32 * 1024,
}

PHASES = {
    "bootstrap",
    "contract",
    "plan",
    "plan-review",
    "implement",
    "validate",
    "review-1",
    "fix-1",
    "review-2",
    "fix-2",
    "integrate",
    "deliver",
    "report",
    "complete",
}
RUN_STATUSES = {"working", "awaiting-user", "blocked", "failed", "complete"}
REPO_STATUSES = {"pending", "working", "blocked", "failed", "complete"}
AGENT_STATUSES = {"starting", "working", "blocked", "idle", "failed", "closed"}
RESULT_STAGES = {"implement", "validate", "validation-fix", "fix-1", "fix-2", "pipeline-fix"}
ASSIGNMENT_STAGES = (PHASES - {"bootstrap", "plan-review", "complete"}) | {
    "design-challenge",
    "validation-fix",
    "pipeline-fix",
}
ARTIFACT_STATUSES = {"complete", "blocked", "failed"}
WORKER_ARTIFACT_KINDS = {
    "contract",
    "plan",
    "design-challenge",
    "result",
    "review",
    "integration",
    "delivery",
    "report",
}
HIGH_COST_MECHANISM_TYPES = {
    "database-trigger",
    "database-function",
    "stored-procedure",
    "data-backfill",
    "background-job",
    "event-driven-flow",
    "cache",
    "new-seam-or-adapter",
    "new-storage-system",
    "other",
}
DESIGN_FINDING_CATEGORIES = {
    "necessity",
    "scope",
    "seam",
    "database",
    "migration",
    "operability",
    "testability",
}
PHASE_ORDER = [
    "bootstrap",
    "contract",
    "plan",
    "plan-review",
    "implement",
    "validate",
    "review-1",
    "fix-1",
    "review-2",
    "fix-2",
    "integrate",
    "deliver",
    "report",
    "complete",
]
BLOCKER_KINDS = {
    "decision",
    "environment",
    "authentication",
    "permission",
    "infrastructure",
    "dependency",
    "code",
}
PROFILES = {"fast", "standard", "full"}
RISK_FLAGS = {
    "authorization",
    "background-processing",
    "concurrency",
    "cross-repository",
    "data-backfill",
    "database-migration",
    "high-cost-mechanism",
    "new-storage",
    "public-interface",
    "security",
}
# Cross-repository scope needs coordination, but is not by itself a costly or
# dangerous mechanism. It therefore does not force a design-critic worker.
HIGH_RISK_FLAGS = RISK_FLAGS - {"cross-repository"}
THINKING_LEVELS = {"medium", "high", "xhigh"}
DECISION_KINDS = {
    "implementation",
    "bounded-plan-deviation",
    "validation",
    "finding-resolution",
    "pipeline",
}
REVIEW_DISPOSITIONS = {"must-fix", "advisory"}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REQ_RE = re.compile(r"^REQ-[0-9]{3,}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CURRENT_ARTIFACT_PATH: Path | None = None


class ValidationError(Exception):
    """A readable failure with machine-checkable recovery classification."""

    def __init__(self, message: str, *, code: str = "invalid-evidence", path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def fail(location: str, message: str, *, code: str = "invalid-evidence") -> NoReturn:
    raise ValidationError(f"{location}: {message}", code=code, path=location)


def rejection_details(error: Exception) -> dict[str, str]:
    if isinstance(error, ValidationError):
        return {"error_code": error.code, "error_path": error.path}
    if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
        return {"error_code": "invalid-json", "error_path": "$"}
    return {"error_code": "execution", "error_path": "$"}


def obj(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(location, "must be an object")
    return value


def array(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        fail(location, "must be an array")
    return value


def field(mapping: dict[str, Any], name: str, location: str) -> Any:
    if name not in mapping:
        raise ValidationError(
            f"{location}: missing required field {name!r}",
            code="missing-field", path=f"{location}.{name}",
        )
    return mapping[name]


def string(
    value: Any,
    location: str,
    *,
    nonempty: bool = True,
    max_length: int | None = None,
) -> str:
    if not isinstance(value, str):
        fail(location, "must be a string")
    if nonempty and not value.strip():
        fail(location, "must not be empty")
    if max_length is not None and len(value) > max_length:
        fail(location, f"must be at most {max_length} characters")
    return value


def integer(value: Any, location: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(location, "must be an integer")
    if minimum is not None and value < minimum:
        fail(location, f"must be at least {minimum}")
    return value


def boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        fail(location, "must be a boolean")
    return value


def enum(value: Any, allowed: set[str], location: str) -> str:
    result = string(value, location)
    if result not in allowed:
        fail(location, f"must be one of {sorted(allowed)}")
    return result


def timestamp(value: Any, location: str) -> str:
    result = string(value, location)
    if not TIMESTAMP_RE.fullmatch(result):
        fail(location, "must be a UTC RFC 3339 timestamp ending in Z")
    return result


def sha(value: Any, location: str) -> str:
    result = string(value, location)
    if not SHA_RE.fullmatch(result):
        fail(location, "must be a 40- or 64-character lowercase Git object ID")
    return result


def sha256(value: Any, location: str) -> str:
    result = string(value, location)
    if not SHA256_RE.fullmatch(result):
        fail(location, "must be a 64-character lowercase SHA-256")
    return result


def optional_sha256(value: Any, location: str) -> str | None:
    if value is None:
        return None
    return sha256(value, location)


def repo_id(value: Any, location: str) -> str:
    result = string(value, location)
    if not ID_RE.fullmatch(result):
        fail(location, "must match ^[a-z0-9][a-z0-9-]*$")
    return result


def requirement_id(value: Any, location: str) -> str:
    result = string(value, location)
    if not REQ_RE.fullmatch(result):
        fail(location, "must look like REQ-001")
    return result


def absolute_path(
    value: Any,
    location: str,
    *,
    must_exist: bool = False,
    file_only: bool = False,
    directory_only: bool = False,
) -> str:
    result = string(value, location)
    path = Path(result)
    if not path.is_absolute():
        fail(location, "must be an absolute path")
    if must_exist and not path.exists():
        fail(location, f"does not exist: {result}")
    if file_only and path.exists() and not path.is_file():
        fail(location, "must refer to a file")
    if directory_only and path.exists() and not path.is_dir():
        fail(location, "must refer to a directory")
    return result


def hashed_file_reference(value: Any, location: str) -> str:
    reference = obj(value, location)
    path_value = absolute_path(
        field(reference, "path", location),
        f"{location}.path",
        must_exist=True,
        file_only=True,
    )
    recorded_hash = sha256(field(reference, "sha256", location), f"{location}.sha256")
    actual_hash = hashlib.sha256(Path(path_value).read_bytes()).hexdigest()
    if recorded_hash != actual_hash:
        fail(f"{location}.sha256", f"expected {actual_hash} from {path_value}")
    return path_value


def optional_hashed_file_reference(value: Any, location: str) -> str | None:
    if value is None:
        return None
    return hashed_file_reference(value, location)


def load_json_object(path_value: str, location: str) -> dict[str, Any]:
    try:
        return obj(json.loads(Path(path_value).read_bytes()), location)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(location, f"does not contain readable JSON: {error}")


def paired_hashed_file_fields(
    mapping: dict[str, Any],
    path_name: str,
    hash_name: str,
    location: str,
) -> tuple[str | None, str | None]:
    path_value = field(mapping, path_name, location)
    hash_value = field(mapping, hash_name, location)
    if path_value is None:
        if hash_value is not None:
            fail(f"{location}.{hash_name}", f"must be null when {path_name} is null")
        return None, None
    parsed_path = absolute_path(
        path_value,
        f"{location}.{path_name}",
        must_exist=True,
        file_only=True,
    )
    parsed_hash = sha256(hash_value, f"{location}.{hash_name}")
    actual_hash = hashlib.sha256(Path(parsed_path).read_bytes()).hexdigest()
    if parsed_hash != actual_hash:
        fail(f"{location}.{hash_name}", f"expected {actual_hash} from {path_name}")
    return parsed_path, parsed_hash


def relative_repo_path(value: Any, location: str) -> str:
    result = string(value, location)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts:
        fail(location, "must be a repository-relative path without '..'")
    return result


def string_array(
    value: Any,
    location: str,
    *,
    item_validator: Callable[[Any, str], str] = string,
    nonempty: bool = False,
    unique: bool = True,
    sorted_values: bool = False,
) -> list[str]:
    values = array(value, location)
    if nonempty and not values:
        fail(location, "must not be empty")
    parsed = [item_validator(item, f"{location}[{index}]") for index, item in enumerate(values)]
    if unique and len(parsed) != len(set(parsed)):
        fail(location, "must not contain duplicates")
    if sorted_values and parsed != sorted(parsed):
        fail(location, "must be sorted lexicographically")
    return parsed


def validate_common(data: dict[str, Any], kind: str) -> None:
    if field(data, "schema_version", "$") != 1:
        fail("$.schema_version", "must equal 1")
    if field(data, "artifact_kind", "$") != kind:
        fail("$.artifact_kind", f"must equal {kind!r}")
    string(field(data, "run_id", "$"), "$.run_id", max_length=160)
    if kind in WORKER_ARTIFACT_KINDS:
        assignment_value = absolute_path(
            field(data, "assignment_path", "$"),
            "$.assignment_path",
            must_exist=True,
            file_only=True,
        )
        recorded_hash = sha256(field(data, "assignment_sha256", "$"), "$.assignment_sha256")
        assignment_path = Path(assignment_value)
        actual_hash = hashlib.sha256(assignment_path.read_bytes()).hexdigest()
        if recorded_hash != actual_hash:
            fail("$.assignment_sha256", f"expected {actual_hash} from the assignment file")
        try:
            assignment = obj(json.loads(assignment_path.read_bytes()), "$.assignment")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            fail("$.assignment_path", f"does not contain valid JSON: {error}")
        validate_assignment(assignment)
        if assignment["run_id"] != data["run_id"]:
            fail("$.run_id", "does not match the assignment run_id")
        if assignment["output_kind"] != kind:
            fail("$.artifact_kind", "does not match the assignment output_kind")
        if CURRENT_ARTIFACT_PATH is None:
            fail("$", "validator has no current artifact path")
        expected_output = Path(assignment["output_artifact"]).resolve()
        if expected_output != CURRENT_ARTIFACT_PATH.resolve():
            fail("$.assignment_path", f"assignment output is {expected_output}")
        if "repo_id" in data and data["repo_id"] != assignment["repo_id"]:
            fail("$.repo_id", "does not match the assignment repo_id")
        if "attempt" in data and data["attempt"] != assignment["attempt"]:
            fail("$.attempt", "does not match the assignment attempt")
        if kind == "result" and data.get("stage") != assignment["stage"]:
            fail("$.stage", "does not match the assignment stage")


def validate_blockers(value: Any, location: str = "$.blockers") -> list[dict[str, Any]]:
    blockers = array(value, location)
    seen: set[str] = set()
    for index, raw in enumerate(blockers):
        loc = f"{location}[{index}]"
        blocker = obj(raw, loc)
        blocker_id = string(field(blocker, "id", loc), f"{loc}.id")
        if blocker_id in seen:
            fail(f"{loc}.id", "must be unique")
        seen.add(blocker_id)
        enum(field(blocker, "kind", loc), BLOCKER_KINDS, f"{loc}.kind")
        string(field(blocker, "summary", loc), f"{loc}.summary", max_length=1200)
        absolute_path(
            field(blocker, "evidence_path", loc),
            f"{loc}.evidence_path",
            must_exist=True,
            file_only=True,
        )
        string(field(blocker, "required_action", loc), f"{loc}.required_action", max_length=2000)
    return blockers


def validate_status_blockers(status: str, blockers: list[dict[str, Any]], location: str = "$.status") -> None:
    if status == "complete" and blockers:
        fail(location, "complete artifacts must have no blockers")
    if status == "blocked" and not blockers:
        fail(location, "blocked artifacts must have at least one blocker")


def validate_workflow_policy(value: Any, profile: str, location: str) -> dict[str, Any]:
    policy = obj(value, location)
    contract_required = boolean(
        field(policy, "contract_required", location),
        f"{location}.contract_required",
    )
    challenge_policy = enum(
        field(policy, "design_challenge", location),
        {"none", "risk-only", "all"},
        f"{location}.design_challenge",
    )
    integration_required = boolean(
        field(policy, "integration_required", location),
        f"{location}.integration_required",
    )
    report_required = boolean(
        field(policy, "report_required", location), f"{location}.report_required"
    )
    max_tasks = integer(
        field(policy, "max_tasks_per_packet", location),
        f"{location}.max_tasks_per_packet",
        minimum=1,
    )
    if max_tasks > 4:
        fail(f"{location}.max_tasks_per_packet", "must be at most 4")
    max_minutes = integer(
        field(policy, "max_packet_minutes", location),
        f"{location}.max_packet_minutes",
        minimum=10,
    )
    if max_minutes > 45:
        fail(f"{location}.max_packet_minutes", "must be at most 45")
    second_review = enum(
        field(policy, "second_review", location),
        {"never", "high-risk-fixes", "all-fixes"},
        f"{location}.second_review",
    )
    blocking_severities = string_array(
        field(policy, "blocking_severities", location),
        f"{location}.blocking_severities",
        item_validator=lambda item, item_location: enum(
            item,
            {"critical", "high", "medium", "low"},
            item_location,
        ),
        nonempty=True,
        sorted_values=True,
    )
    required_blocking = {"critical", "high", "medium"}
    if not required_blocking <= set(blocking_severities):
        fail(
            f"{location}.blocking_severities",
            "must include critical, high, and medium",
        )
    attempt_budget = integer(
        field(policy, "coordinator_attempt_budget", location),
        f"{location}.coordinator_attempt_budget",
        minimum=12,
    )
    if attempt_budget > 60:
        fail(f"{location}.coordinator_attempt_budget", "must be at most 60")
    boolean(field(policy, "auto_resume", location), f"{location}.auto_resume")
    approval_required = True
    if "user_plan_approval_required" in policy:
        approval_required = boolean(
            policy["user_plan_approval_required"],
            f"{location}.user_plan_approval_required",
        )

    if profile == "full":
        # Older full runs used `all`; new runs use risk-only. Both remain
        # resumable, while high-risk plans are independently required to opt in.
        if challenge_policy not in {"all", "risk-only"}:
            fail(
                f"{location}.design_challenge",
                "full profile challenges risk-bearing plans",
            )
        if max_tasks != 3:
            fail(f"{location}.max_tasks_per_packet", "full profile uses three-task packets")
        if second_review not in {"never", "high-risk-fixes"}:
            fail(
                f"{location}.second_review",
                "full profile uses one review or legacy targeted high-risk verification",
            )
        if not approval_required:
            fail(
                f"{location}.user_plan_approval_required",
                "full profile requires explicit user plan approval",
            )
    if profile == "standard":
        if challenge_policy != "risk-only":
            fail(f"{location}.design_challenge", "standard challenges risk-bearing plans")
        if max_tasks != 3:
            fail(f"{location}.max_tasks_per_packet", "standard uses three-task packets")
        if second_review not in {"never", "high-risk-fixes"}:
            fail(
                f"{location}.second_review",
                "standard uses one review or legacy targeted high-risk verification",
            )
    if profile == "fast":
        if contract_required:
            fail(f"{location}.contract_required", "fast profile embeds the local contract in its plan")
        if challenge_policy != "none":
            fail(f"{location}.design_challenge", "fast profile does not run a planning critic")
        if integration_required:
            fail(f"{location}.integration_required", "fast profile is single-repository")
        if max_tasks != 4:
            fail(f"{location}.max_tasks_per_packet", "fast profile uses four-task packets")
        if second_review != "never":
            fail(f"{location}.second_review", "fast profile has one independent review")
    return policy


def validate_plan_review(
    value: Any,
    *,
    repositories: dict[str, Any],
    contract_hash: str | None,
    location: str = "$.plan_review",
) -> str:
    review = obj(value, location)
    review_status = enum(
        field(review, "status", location),
        {"pending", "approved"},
        f"{location}.status",
    )
    requested_at = timestamp(
        field(review, "requested_at", location),
        f"{location}.requested_at",
    )
    review_path, _ = paired_hashed_file_fields(
        review,
        "review_path",
        "review_sha256",
        location,
    )
    if review_path is None:
        fail(f"{location}.review_path", "must reference the review bundle")
    if not re.fullmatch(r"plan-review-v[0-9]+\.md", Path(review_path).name):
        fail(
            f"{location}.review_path",
            "must use a versioned plan-review-vN.md filename",
        )

    recorded_contract_hash = field(review, "contract_sha256", location)
    if recorded_contract_hash is not None:
        recorded_contract_hash = sha256(
            recorded_contract_hash,
            f"{location}.contract_sha256",
        )
    if recorded_contract_hash != contract_hash:
        fail(
            f"{location}.contract_sha256",
            "must match the canonical contract hash",
        )

    plans = obj(field(review, "plans", location), f"{location}.plans")
    if list(plans) != sorted(plans):
        fail(f"{location}.plans", "keys must be sorted lexicographically")
    if set(plans) != set(repositories):
        fail(
            f"{location}.plans",
            f"must cover every repository exactly once: {sorted(repositories)}",
        )

    review_text = Path(review_path).read_text(encoding="utf-8", errors="replace")
    required_review_tokens = [contract_hash] if contract_hash is not None else []
    for key, repository_value in repositories.items():
        loc = f"{location}.plans.{key}"
        entry = obj(plans[key], loc)
        plan_path, plan_hash = paired_hashed_file_fields(
            entry,
            "plan_path",
            "plan_sha256",
            loc,
        )
        challenge_path, challenge_hash = paired_hashed_file_fields(
            entry,
            "design_challenge_path",
            "design_challenge_sha256",
            loc,
        )
        repository = obj(repository_value, f"$.repositories.{key}")
        if plan_path is None:
            fail(f"{loc}.plan_path", "must reference the canonical plan")
        if (
            plan_path != repository.get("plan_path")
            or plan_hash != repository.get("plan_sha256")
        ):
            fail(loc, "plan reference must match the canonical repository plan")
        if (
            challenge_path != repository.get("design_challenge_path")
            or challenge_hash != repository.get("design_challenge_sha256")
        ):
            fail(
                loc,
                "design challenge reference must match the canonical repository challenge",
            )
        required_review_tokens.extend([key, plan_path, plan_hash])
        if challenge_path is not None and challenge_hash is not None:
            required_review_tokens.extend([challenge_path, challenge_hash])

    missing_tokens = [token for token in required_review_tokens if token not in review_text]
    if missing_tokens:
        fail(
            f"{location}.review_path",
            "review bundle must name every repository and include every canonical path/hash; "
            f"missing {missing_tokens[:3]}",
        )

    approved_at = field(review, "approved_at", location)
    approval_text = field(review, "approval_text", location)
    approval_source = review.get("approval_source")
    if approval_source is not None:
        approval_source = enum(
            approval_source,
            {"user", "workflow-policy"},
            f"{location}.approval_source",
        )
    if review_status == "pending":
        if (
            approved_at is not None
            or approval_text is not None
            or approval_source is not None
        ):
            fail(location, "pending plan review must not contain approval evidence")
    else:
        parsed_approved_at = timestamp(approved_at, f"{location}.approved_at")
        if parsed_approved_at < requested_at:
            fail(
                f"{location}.approved_at",
                "must not precede the review request",
            )
        string(
            approval_text,
            f"{location}.approval_text",
            max_length=4000,
        )
    return review_status


def validate_run(data: dict[str, Any]) -> None:
    validate_common(data, "run")
    timestamp(field(data, "created_at", "$"), "$.created_at")
    timestamp(field(data, "updated_at", "$"), "$.updated_at")
    status = enum(field(data, "status", "$"), RUN_STATUSES, "$.status")
    phase = enum(field(data, "phase", "$"), PHASES, "$.phase")
    enum(data.get("worker_reasoning_policy", "legacy-xhigh"), {"stage-v1", "legacy-xhigh"}, "$.worker_reasoning_policy")
    profile_value = data.get("profile")
    profile: str | None = None
    workflow_policy: dict[str, Any] | None = None
    if profile_value is not None:
        profile = enum(profile_value, PROFILES, "$.profile")
        string_array(
            field(data, "profile_reasons", "$"),
            "$.profile_reasons",
            nonempty=True,
            unique=True,
        )
        workflow_policy = validate_workflow_policy(
            field(data, "workflow_policy", "$"), profile, "$.workflow_policy"
        )
        run_risk_flags = string_array(
            field(data, "risk_flags", "$"),
            "$.risk_flags",
            item_validator=lambda item, item_location: enum(item, RISK_FLAGS, item_location),
            sorted_values=True,
        )
        if profile == "fast" and run_risk_flags:
            fail("$.risk_flags", "fast profile requires an empty risk list")
    worker_execution = data.get("worker_execution")
    if worker_execution is not None:
        execution = obj(worker_execution, "$.worker_execution")
        execution_schema = integer(
            field(execution, "schema_version", "$.worker_execution"),
            "$.worker_execution.schema_version",
            minimum=1,
        )
        if execution_schema != 1:
            fail("$.worker_execution.schema_version", "must equal 1")
        enum(
            field(execution, "backend", "$.worker_execution"),
            {"direct", "herdr", "paseo", "tmux"},
            "$.worker_execution.backend",
        )
        enum(
            field(execution, "runtime", "$.worker_execution"),
            {"codex", "pi"},
            "$.worker_execution.runtime",
        )
        string(
            field(execution, "detected_from", "$.worker_execution"),
            "$.worker_execution.detected_from",
        )
        obj(field(execution, "evidence", "$.worker_execution"), "$.worker_execution.evidence")
    request_path = absolute_path(
        field(data, "request_path", "$"), "$.request_path", must_exist=True, file_only=True
    )
    request_hash = sha256(field(data, "request_sha256", "$"), "$.request_sha256")
    actual_request_hash = hashlib.sha256(Path(request_path).read_bytes()).hexdigest()
    if request_hash != actual_request_hash:
        fail("$.request_sha256", f"expected {actual_request_hash} from request_path")
    requirements_path = absolute_path(
        field(data, "requirements_path", "$"),
        "$.requirements_path",
        must_exist=True,
        file_only=True,
    )
    requirements_hash = sha256(
        field(data, "requirements_sha256", "$"), "$.requirements_sha256"
    )
    actual_requirements_hash = hashlib.sha256(Path(requirements_path).read_bytes()).hexdigest()
    if requirements_hash != actual_requirements_hash:
        fail(
            "$.requirements_sha256",
            f"expected {actual_requirements_hash} from requirements_path",
        )
    contract_path = field(data, "contract_path", "$")
    contract_hash = field(data, "contract_sha256", "$")
    if contract_path is None:
        if contract_hash is not None:
            fail("$.contract_sha256", "must be null when contract_path is null")
        if (
            workflow_policy is not None
            and workflow_policy["contract_required"]
            and PHASE_ORDER.index(phase) > PHASE_ORDER.index("contract")
        ):
            fail("$.contract_path", "is required after the full-profile contract phase")
    else:
        parsed_contract_path = absolute_path(
            contract_path, "$.contract_path", must_exist=True, file_only=True
        )
        parsed_contract_hash = sha256(contract_hash, "$.contract_sha256")
        actual_contract_hash = hashlib.sha256(Path(parsed_contract_path).read_bytes()).hexdigest()
        if parsed_contract_hash != actual_contract_hash:
            fail("$.contract_sha256", f"expected {actual_contract_hash} from contract_path")

    retries = obj(field(data, "retry_limits", "$"), "$.retry_limits")
    repair_limit = integer(retries.get("artifact_repairs_per_action", 0), "$.retry_limits.artifact_repairs_per_action", minimum=0)
    if repair_limit > 1:
        fail("$.retry_limits.artifact_repairs_per_action", "must be at most one")
    for name in (
        "worker_replacements_per_stage",
        "contract_revisions",
        "plan_revision_cycles",
        "validation_fix_cycles",
        "review_rounds",
        "pipeline_fix_cycles",
    ):
        integer(
            field(retries, name, "$.retry_limits"),
            f"$.retry_limits.{name}",
            minimum=0,
        )

    repositories = obj(field(data, "repositories", "$"), "$.repositories")
    if not repositories:
        fail("$.repositories", "must not be empty")
    if profile is not None and len(repositories) > 1:
        assert workflow_policy is not None
        if profile == "fast":
            fail("$.profile", "fast profile is limited to one repository")
        if not workflow_policy["contract_required"]:
            fail(
                "$.workflow_policy.contract_required",
                "multi-repository runs require a shared contract",
            )
        if not workflow_policy["integration_required"]:
            fail(
                "$.workflow_policy.integration_required",
                "multi-repository runs require integration verification",
            )
    if list(repositories) != sorted(repositories):
        fail("$.repositories", "keys must be sorted lexicographically")
    for key, raw in repositories.items():
        loc = f"$.repositories.{key}"
        repo_id(key, loc)
        repository = obj(raw, loc)
        absolute_path(field(repository, "root", loc), f"{loc}.root", must_exist=True, directory_only=True)
        absolute_path(
            field(repository, "worktree", loc),
            f"{loc}.worktree",
            must_exist=True,
            directory_only=True,
        )
        absolute_path(
            field(repository, "artifact_dir", loc),
            f"{loc}.artifact_dir",
            must_exist=True,
            directory_only=True,
        )
        string(field(repository, "base_branch", loc), f"{loc}.base_branch")
        string(field(repository, "branch", loc), f"{loc}.branch")
        sha(field(repository, "baseline", loc), f"{loc}.baseline")
        absolute_path(
            field(repository, "initial_status_path", loc),
            f"{loc}.initial_status_path",
            must_exist=True,
            file_only=True,
        )
        repository_stage = enum(field(repository, "stage", loc), PHASES, f"{loc}.stage")
        enum(field(repository, "status", loc), REPO_STATUSES, f"{loc}.status")
        active_writer = field(repository, "active_writer", loc)
        if active_writer is not None:
            string(active_writer, f"{loc}.active_writer")

        plan_path, plan_hash = paired_hashed_file_fields(
            repository, "plan_path", "plan_sha256", loc
        )
        challenge_path, challenge_hash = paired_hashed_file_fields(
            repository,
            "design_challenge_path",
            "design_challenge_sha256",
            loc,
        )
        plan_data: dict[str, Any] | None = None
        challenge_required = True
        if plan_path is not None:
            plan_data = load_json_object(plan_path, f"{loc}.plan_path")
            if plan_data.get("artifact_kind") != "plan":
                fail(f"{loc}.plan_path", "must reference a plan artifact")
            if plan_data.get("repo_id") != key:
                fail(f"{loc}.plan_path", "plan repo_id must match the repository")
            if plan_data.get("contract_sha256") != contract_hash:
                fail(f"{loc}.plan_path", "canonical plan does not reference the canonical contract")
            challenge_required = boolean(
                plan_data.get("design_challenge_required", True),
                f"{loc}.plan_path.design_challenge_required",
            )
            recorded_requirement = repository.get("design_challenge_required")
            if recorded_requirement is not None and boolean(
                recorded_requirement, f"{loc}.design_challenge_required"
            ) != challenge_required:
                fail(
                    f"{loc}.design_challenge_required",
                    "must match the canonical plan",
                )
        if plan_path is None and challenge_path is not None:
            fail(loc, "a canonical design challenge requires a canonical plan")
        if challenge_required and plan_path is not None and challenge_path is None:
            if PHASE_ORDER.index(repository_stage) > PHASE_ORDER.index("plan"):
                fail(loc, "this canonical plan requires an accepting design challenge")
        if PHASE_ORDER.index(repository_stage) > PHASE_ORDER.index("plan") and plan_path is None:
            fail(loc, "a canonical plan is required after the plan phase")
        if plan_path is not None and challenge_path is not None:
            assert plan_data is not None
            challenge_data = load_json_object(challenge_path, f"{loc}.design_challenge_path")
            if challenge_data.get("artifact_kind") != "design-challenge":
                fail(f"{loc}.design_challenge_path", "must reference a design-challenge artifact")
            if challenge_data.get("repo_id") != key:
                fail(f"{loc}.design_challenge_path", "challenge repo_id must match the repository")
            if challenge_data.get("verdict") != "accept":
                fail(f"{loc}.design_challenge_path", "canonical challenge verdict must be accept")
            challenge_plan = obj(
                field(challenge_data, "plan", f"{loc}.design_challenge_path"),
                f"{loc}.design_challenge_path.plan",
            )
            referenced_plan_hash = sha256(
                field(challenge_plan, "sha256", f"{loc}.design_challenge_path.plan"),
                f"{loc}.design_challenge_path.plan.sha256",
            )
            if referenced_plan_hash != plan_hash:
                fail(loc, "canonical challenge does not reference the canonical plan hash")
            if challenge_data.get("contract_sha256") != contract_hash:
                fail(
                    f"{loc}.design_challenge_path",
                    "canonical challenge does not reference the canonical contract",
                )

        accepted = obj(field(repository, "accepted_artifacts", loc), f"{loc}.accepted_artifacts")
        accepted_references: set[tuple[str, str]] = set()
        for artifact_name, artifact_reference in accepted.items():
            string(artifact_name, f"{loc}.accepted_artifacts key")
            accepted_path = hashed_file_reference(
                artifact_reference,
                f"{loc}.accepted_artifacts.{artifact_name}",
            )
            accepted_hash = sha256(
                field(
                    obj(artifact_reference, f"{loc}.accepted_artifacts.{artifact_name}"),
                    "sha256",
                    f"{loc}.accepted_artifacts.{artifact_name}",
                ),
                f"{loc}.accepted_artifacts.{artifact_name}.sha256",
            )
            accepted_references.add((accepted_path, accepted_hash))
        if plan_path is not None:
            if (plan_path, plan_hash) not in accepted_references:
                fail(f"{loc}.plan_path", "canonical plan must be an accepted artifact")
            if challenge_path is not None and (challenge_path, challenge_hash) not in accepted_references:
                fail(
                    f"{loc}.design_challenge_path",
                    "canonical design challenge must be an accepted artifact",
                )

    # Profiled runs created before this gate did not have the policy key. Treat
    # omission as required so resuming an older profiled run cannot bypass the
    # user's review. Truly legacy runs without profile fields remain readable.
    plan_review_required = bool(
        workflow_policy is not None
        and workflow_policy.get("user_plan_approval_required", True) is True
    )
    plan_review_status: str | None = None
    plan_review_value = data.get("plan_review")
    current_phase_index = PHASE_ORDER.index(phase)
    plan_review_phase_index = PHASE_ORDER.index("plan-review")
    if plan_review_required:
        plan_review_value = field(data, "plan_review", "$")
        if current_phase_index < plan_review_phase_index:
            if plan_review_value is not None:
                fail(
                    "$.plan_review",
                    "must be null until all canonical plans are ready for user review",
                )
        else:
            if plan_review_value is None:
                fail(
                    "$.plan_review",
                    "is required before the run can leave planning",
                )
            plan_review_status = validate_plan_review(
                plan_review_value,
                repositories=repositories,
                contract_hash=contract_hash,
            )
            if plan_review_status == "pending":
                if phase != "plan-review" or status != "awaiting-user":
                    fail(
                        "$.plan_review.status",
                        "pending review requires the plan-review phase and awaiting-user status",
                    )
            elif current_phase_index <= plan_review_phase_index:
                fail(
                    "$.phase",
                    "an approved plan review must advance atomically to implementation",
                )
    elif plan_review_value is not None:
        plan_review_status = validate_plan_review(
            plan_review_value,
            repositories=repositories,
            contract_hash=contract_hash,
        )

    pending_refresh = obj(data.get("pending_delivery_refresh", {}), "$.pending_delivery_refresh")
    for repository_id, reference in pending_refresh.items():
        location = f"$.pending_delivery_refresh.{repository_id}"
        if repository_id not in repositories:
            fail(location, "unknown repository")
        hashed_file_reference(reference, location)
        if reference not in repositories[repository_id]["accepted_artifacts"].values():
            fail(location, "must pin an accepted delivery observation")

    global_accepted = data.get("accepted_artifacts", {})
    global_accepted_object = obj(global_accepted, "$.accepted_artifacts")
    global_accepted_kinds: set[str] = set()
    for artifact_name, artifact_reference in global_accepted_object.items():
        string(artifact_name, "$.accepted_artifacts key")
        accepted_path = hashed_file_reference(
            artifact_reference, f"$.accepted_artifacts.{artifact_name}"
        )
        accepted_data = load_json_object(
            accepted_path, f"$.accepted_artifacts.{artifact_name}.path"
        )
        accepted_kind = accepted_data.get("artifact_kind")
        if isinstance(accepted_kind, str):
            global_accepted_kinds.add(accepted_kind)

    actions = array(field(data, "next_actions", "$"), "$.next_actions")
    orders: list[int] = []
    action_ids: set[str] = set()
    for index, raw in enumerate(actions):
        loc = f"$.next_actions[{index}]"
        action = obj(raw, loc)
        orders.append(integer(field(action, "order", loc), f"{loc}.order", minimum=1))
        action_id = string(field(action, "action_id", loc), f"{loc}.action_id")
        if action_id in action_ids:
            fail(f"{loc}.action_id", "must be unique")
        action_ids.add(action_id)
        enum(field(action, "phase", loc), PHASES, f"{loc}.phase")
        action_repo_id = field(action, "repo_id", loc)
        if action_repo_id is not None:
            parsed_repo_id = repo_id(action_repo_id, f"{loc}.repo_id")
            if parsed_repo_id not in repositories:
                fail(f"{loc}.repo_id", "must identify a run repository")
        integer(field(action, "attempt", loc), f"{loc}.attempt", minimum=1)
        string_array(
            field(action, "input_artifacts", loc),
            f"{loc}.input_artifacts",
            item_validator=lambda value, item_loc: absolute_path(
                value, item_loc, must_exist=True, file_only=True
            ),
            sorted_values=True,
        )
        absolute_path(field(action, "output_artifact", loc), f"{loc}.output_artifact")
        enum(field(action, "status", loc), {"pending", "working", "blocked"}, f"{loc}.status")
    if orders != sorted(orders) or len(orders) != len(set(orders)):
        fail("$.next_actions", "order values must be unique and ascending")

    blockers = validate_blockers(field(data, "blockers", "$"))
    if status == "awaiting-user":
        if phase != "plan-review" or plan_review_status != "pending":
            fail(
                "$.status",
                "awaiting-user is reserved for a pending full-profile plan review",
            )
        if actions:
            fail("$.next_actions", "must be empty during the user plan-review hard stop")
        if blockers:
            fail("$.blockers", "must be empty while awaiting the user's plan decision")
        active_repositories = [
            key
            for key, repository in repositories.items()
            if obj(repository, f"$.repositories.{key}").get("active_writer") is not None
        ]
        if active_repositories:
            fail(
                "$.repositories",
                "no writer may remain active during plan review: "
                f"{active_repositories}",
            )
        wrong_stage_repositories = [
            key
            for key, repository in repositories.items()
            if obj(repository, f"$.repositories.{key}").get("stage") != "plan-review"
        ]
        if wrong_stage_repositories:
            fail(
                "$.repositories",
                "every repository must be parked at plan-review while awaiting the user: "
                f"{wrong_stage_repositories}",
            )
    if status == "complete":
        if pending_refresh:
            fail("$.pending_delivery_refresh", "completion requires fresh delivery observations after recovery")
        if phase != "complete":
            fail("$.phase", "must be complete when run status is complete")
        if actions:
            fail("$.next_actions", "must be empty when run status is complete")
        if blockers:
            fail("$.blockers", "must be empty when run status is complete")
        if workflow_policy is not None:
            if workflow_policy["integration_required"] and "integration" not in global_accepted_kinds:
                fail("$.accepted_artifacts", "completion requires an accepted integration artifact")
            if workflow_policy["report_required"] and "report" not in global_accepted_kinds:
                fail("$.accepted_artifacts", "completion requires an accepted report artifact")
    if status == "blocked" and not blockers:
        fail("$.blockers", "must not be empty when run status is blocked")


def validate_requirements(data: dict[str, Any]) -> None:
    validate_common(data, "requirements")
    timestamp(field(data, "created_at", "$"), "$.created_at")
    requirements = array(field(data, "requirements", "$"), "$.requirements")
    if not requirements:
        fail("$.requirements", "must not be empty")
    ids: list[str] = []
    for index, raw in enumerate(requirements):
        loc = f"$.requirements[{index}]"
        requirement = obj(raw, loc)
        ids.append(requirement_id(field(requirement, "id", loc), f"{loc}.id"))
        string(field(requirement, "source_text", loc), f"{loc}.source_text", max_length=4000)
        string_array(
            field(requirement, "acceptance_criteria", loc),
            f"{loc}.acceptance_criteria",
            nonempty=True,
            unique=True,
        )
        string_array(
            field(requirement, "repository_ids", loc),
            f"{loc}.repository_ids",
            item_validator=repo_id,
            nonempty=True,
            sorted_values=True,
        )
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        fail("$.requirements", "requirement IDs must be unique and sorted")
    string_array(field(data, "constraints", "$"), "$.constraints", unique=True)


def validate_agents(data: dict[str, Any]) -> None:
    validate_common(data, "agents")
    timestamp(field(data, "updated_at", "$"), "$.updated_at")
    agents = array(field(data, "agents", "$"), "$.agents")
    names: set[str] = set()
    for index, raw in enumerate(agents):
        loc = f"$.agents[{index}]"
        agent = obj(raw, loc)
        name = string(field(agent, "name", loc), f"{loc}.name")
        if name in names:
            fail(f"{loc}.name", "must be unique")
        names.add(name)
        enum(
            field(agent, "stage", loc),
            (PHASES - {"plan-review"})
            | {"design-challenge", "validation-fix", "pipeline-fix"},
            f"{loc}.stage",
        )
        value = field(agent, "repo_id", loc)
        if value is not None:
            repo_id(value, f"{loc}.repo_id")
        integer(field(agent, "attempt", loc), f"{loc}.attempt", minimum=1)
        if "handle_id" in agent:
            string(field(agent, "backend", loc), f"{loc}.backend")
            string(field(agent, "handle_id", loc), f"{loc}.handle_id")
            enum(
                field(agent, "cleanup_status", loc),
                {"pending", "retained", "complete", "failed"},
                f"{loc}.cleanup_status",
            )
            cleanup_error = agent.get("cleanup_error")
            if cleanup_error is not None:
                string(cleanup_error, f"{loc}.cleanup_error", max_length=2000)
        else:
            # Schema-v1 Herdr runs recorded pane lifecycle directly.
            string(field(agent, "pane_id", loc), f"{loc}.pane_id")
        status = enum(field(agent, "status", loc), AGENT_STATUSES, f"{loc}.status")
        timestamp(field(agent, "started_at", loc), f"{loc}.started_at")
        ended_at = field(agent, "ended_at", loc)
        if ended_at is not None:
            timestamp(ended_at, f"{loc}.ended_at")
        if status in {"failed", "closed"} and ended_at is None:
            fail(f"{loc}.ended_at", "must be present for failed or closed agents")
        absolute_path(field(agent, "output_artifact", loc), f"{loc}.output_artifact")


def validate_assignment(data: dict[str, Any]) -> None:
    validate_common(data, "assignment")
    string(field(data, "action_id", "$"), "$.action_id", max_length=200)
    timestamp(field(data, "created_at", "$"), "$.created_at")
    stage = enum(field(data, "stage", "$"), ASSIGNMENT_STAGES, "$.stage")
    execution_mode = enum(data.get("execution_mode", "worker"), {"worker", "artifact-repair", "command"}, "$.execution_mode")
    if execution_mode == "command" and stage not in {"deliver", "validate"}:
        fail("$.execution_mode", "only delivery or coordinator validation uses command assignments")
    if execution_mode == "command" and stage == "validate":
        hashed_file_reference(field(data, "coordinator_validation_source", "$"), "$.coordinator_validation_source")
        state = obj(field(data, "coordinator_repository_state", "$"), "$.coordinator_repository_state")
        for key in ("fingerprint", "index_sha256"):
            sha256(field(state, key, "$.coordinator_repository_state"), f"$.coordinator_repository_state.{key}")
        sha(field(state, "head", "$.coordinator_repository_state"), "$.coordinator_repository_state.head")
        string(field(state, "branch", "$.coordinator_repository_state"), "$.coordinator_repository_state.branch")
        for permission in ("project_file_access", "git_access", "forge_access"):
            if data.get(permission) != "none":
                fail(f"$.{permission}", "coordinator validation cannot grant worker write access")
    verify_only = boolean(data.get("verify_only", False), "$.verify_only")
    if verify_only and (execution_mode != "command" or stage != "deliver"):
        fail("$.verify_only", "read-only delivery verification requires a command assignment")
    if data.get("delivery_evidence_version", 1) not in {1, 2}:
        fail("$.delivery_evidence_version", "unsupported delivery evidence version")
    check_timeout = integer(data.get("check_timeout_seconds", 1800), "$.check_timeout_seconds", minimum=0)
    if check_timeout > 1800:
        fail("$.check_timeout_seconds", "must be at most 1800 seconds")
    integer(field(data, "attempt", "$"), "$.attempt", minimum=1)
    profile_value = data.get("profile")
    profile = enum(profile_value, PROFILES, "$.profile") if profile_value is not None else None
    assigned_repo = field(data, "repo_id", "$")
    if assigned_repo is not None:
        assigned_repo = repo_id(assigned_repo, "$.repo_id")
    absolute_path(field(data, "cwd", "$"), "$.cwd", must_exist=True, directory_only=True)
    thinking = enum(field(data, "thinking", "$"), THINKING_LEVELS, "$.thinking")
    enum(data.get("reasoning_policy", "legacy-xhigh"), {"stage-v1", "legacy-xhigh"}, "$.reasoning_policy")
    if stage == "design-challenge" and thinking == "medium":
        fail("$.thinking", "design-challenge assignments require high or xhigh")
    repair_mode = data.get("execution_mode") == "artifact-repair"
    if stage == "implement" and thinking == "medium" and not repair_mode:
        fail("$.thinking", "implementation assignments require high or xhigh")
    if (data.get("reasoning_policy") == "stage-v1" and not repair_mode and thinking == "medium"
            and stage in {"validation-fix", "pipeline-fix", "fix-1", "fix-2"}):
        fail("$.thinking", "source-writing fix assignments require high or xhigh")
    if profile == "full" and stage in {
        "contract",
        "plan",
        "design-challenge",
        "review-1",
        "review-2",
        "integrate",
    } and thinking != "xhigh":
        fail("$.thinking", f"full-profile {stage} assignments require xhigh")
    timeout_seconds = integer(field(data, "timeout_seconds", "$"), "$.timeout_seconds", minimum=60)
    if timeout_seconds > 7200:
        fail("$.timeout_seconds", "must be at most 7200")
    project_access = enum(
        field(data, "project_file_access", "$"), {"none", "write"}, "$.project_file_access"
    )
    git_access = enum(field(data, "git_access", "$"), {"none", "write"}, "$.git_access")
    forge_access = enum(
        field(data, "forge_access", "$"), {"none", "write"}, "$.forge_access"
    )
    if stage == "deliver":
        expected_access = "none" if verify_only else "write"
        if git_access != expected_access or forge_access != expected_access:
            fail("$", f"delivery assignment requires {expected_access} Git/forge write access")
        if project_access != "none":
            fail("$.project_file_access", "delivery assignments may not edit project files")
    elif git_access != "none" or forge_access != "none":
        fail("$", "only delivery assignments may use Git or forge write access")

    repositories = array(field(data, "repositories", "$"), "$.repositories")
    if not repositories:
        fail("$.repositories", "must not be empty")
    repository_ids: list[str] = []
    write_repositories: list[str] = []
    for index, raw in enumerate(repositories):
        loc = f"$.repositories[{index}]"
        repository = obj(raw, loc)
        current_repo = repo_id(field(repository, "repo_id", loc), f"{loc}.repo_id")
        repository_ids.append(current_repo)
        absolute_path(
            field(repository, "root", loc), f"{loc}.root", must_exist=True, directory_only=True
        )
        absolute_path(
            field(repository, "worktree", loc),
            f"{loc}.worktree",
            must_exist=True,
            directory_only=True,
        )
        access = enum(field(repository, "access", loc), {"read", "write"}, f"{loc}.access")
        if access == "write":
            write_repositories.append(current_repo)
    if repository_ids != sorted(repository_ids) or len(repository_ids) != len(set(repository_ids)):
        fail("$.repositories", "repository IDs must be unique and sorted")
    if project_access == "write":
        if stage not in {"implement", "validation-fix", "fix-1", "fix-2", "pipeline-fix"}:
            fail("$.project_file_access", "this stage may not write project files")
        if assigned_repo is None:
            fail("$.repo_id", "is required for a project-file writer")
        if write_repositories != [assigned_repo]:
            fail("$.repositories", "exactly the assigned repository must have write access")
    elif write_repositories:
        fail("$.repositories", "read-only assignments may not grant repository write access")
    if assigned_repo is not None and assigned_repo not in repository_ids:
        fail("$.repo_id", "must appear in the repository scope")
    if stage == "design-challenge":
        if assigned_repo is None:
            fail("$.repo_id", "is required for a design-challenge assignment")
        if repository_ids != [assigned_repo]:
            fail(
                "$.repositories",
                "design-challenge assignments must inspect exactly one repository",
            )

    baseline = field(data, "baseline", "$")
    preexisting = field(data, "preexisting_status_path", "$")
    if assigned_repo is None:
        if baseline is not None or preexisting is not None:
            fail("$", "global assignments must use null baseline and preexisting_status_path")
    else:
        sha(baseline, "$.baseline")
        absolute_path(
            preexisting,
            "$.preexisting_status_path",
            must_exist=True,
            file_only=True,
        )

    input_tree_fingerprint = data.get("input_tree_fingerprint")
    if input_tree_fingerprint is not None:
        sha256(input_tree_fingerprint, "$.input_tree_fingerprint")
        if assigned_repo is None or project_access == "write":
            fail(
                "$.input_tree_fingerprint",
                "is valid only for repository-scoped read-only assignments",
            )

    input_artifacts = array(field(data, "input_artifacts", "$"), "$.input_artifacts")
    if not input_artifacts:
        fail("$.input_artifacts", "must not be empty")
    input_paths = [
        hashed_file_reference(reference, f"$.input_artifacts[{index}]")
        for index, reference in enumerate(input_artifacts)
    ]
    if input_paths != sorted(input_paths) or len(input_paths) != len(set(input_paths)):
        fail("$.input_artifacts", "paths must be unique and sorted lexicographically")
    input_path_objects = [Path(path) for path in input_paths]
    plan_review_reference = data.get("plan_review")
    if plan_review_reference is not None:
        plan_review_path = hashed_file_reference(
            plan_review_reference,
            "$.plan_review",
        )
        if plan_review_path not in input_paths:
            fail(
                "$.plan_review",
                "approved plan review must also be a hash-pinned input artifact",
            )
        if stage in {"contract", "plan", "design-challenge"}:
            fail(
                "$.plan_review",
                "planning assignments cannot consume a pre-approved review bundle",
            )
    if profile is not None and stage in {
        "contract",
        "plan",
        "design-challenge",
        "implement",
        "review-1",
        "review-2",
        "integrate",
    }:
        if sum(path.name == "request.md" for path in input_path_objects) != 1:
            fail("$.input_artifacts", f"profiled {stage} assignments require request.md")
        requirements_inputs = 0
        for path in input_path_objects:
            if path.suffix != ".json":
                continue
            candidate = load_json_object(str(path), f"$.input_artifacts[{path}]")
            if candidate.get("artifact_kind") == "requirements":
                requirements_inputs += 1
        if requirements_inputs != 1:
            fail(
                "$.input_artifacts",
                f"profiled {stage} assignments require exactly one requirements artifact",
            )
    if stage == "design-challenge":
        if not any(path.name == "SIMPLICITY-CHALLENGE.md" for path in input_path_objects):
            fail(
                "$.input_artifacts",
                "design-challenge assignments must pin SIMPLICITY-CHALLENGE.md",
            )
        if not any(path.name == "DEEPENING.md" for path in input_path_objects):
            fail(
                "$.input_artifacts",
                "design-challenge assignments must pin codebase-design DEEPENING.md",
            )
        codebase_skill_paths = [path for path in input_path_objects if path.name == "SKILL.md"]
        if not any(
            "name: codebase-design" in path.read_text(encoding="utf-8", errors="replace")[:2048]
            for path in codebase_skill_paths
        ):
            fail(
                "$.input_artifacts",
                "design-challenge assignments must pin codebase-design SKILL.md",
            )
    if stage in {"implement", "review-1", "review-2"}:
        plan_inputs: list[tuple[Path, dict[str, Any]]] = []
        challenge_inputs: list[tuple[Path, dict[str, Any]]] = []
        for path in input_path_objects:
            if path.suffix != ".json":
                continue
            candidate = load_json_object(str(path), f"$.input_artifacts[{path}]")
            if candidate.get("artifact_kind") == "plan":
                plan_inputs.append((path, candidate))
            if candidate.get("artifact_kind") == "design-challenge":
                challenge_inputs.append((path, candidate))
        if len(plan_inputs) != 1:
            fail("$.input_artifacts", f"{stage} assignments require exactly one canonical plan")
        plan_path, plan_input = plan_inputs[0]
        if plan_input.get("repo_id") != assigned_repo:
            fail("$.input_artifacts", "canonical plan must match the assigned repo_id")
        # Pre-simplicity schema-v1 plans had no revision or challenge fields.
        # Preserve resumability for those durable runs; modern legacy plans
        # (revision present) retain the original mandatory-challenge behavior.
        challenge_required = boolean(
            plan_input.get("design_challenge_required", "revision" in plan_input),
            "$.input_artifacts.plan.design_challenge_required",
        )
        expected_challenges = 1 if challenge_required else 0
        if len(challenge_inputs) != expected_challenges:
            if challenge_required:
                fail(
                    "$.input_artifacts",
                    f"{stage} assignments require the canonical plan's accepting design challenge",
                )
            fail(
                "$.input_artifacts",
                f"{stage} assignments must not pin a waived design challenge",
            )
        if challenge_inputs:
            _, challenge_input = challenge_inputs[0]
            if challenge_input.get("repo_id") != assigned_repo:
                fail(
                    "$.input_artifacts",
                    "canonical challenge must match the assigned repo_id",
                )
            if challenge_input.get("verdict") != "accept":
                fail("$.input_artifacts", "implementation and review require an accepting challenge")
            challenged_plan = obj(
                field(challenge_input, "plan", "$.input_artifacts.design-challenge"),
                "$.input_artifacts.design-challenge.plan",
            )
            actual_plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            if challenged_plan.get("sha256") != actual_plan_hash:
                fail("$.input_artifacts", "accepting challenge must reference the assigned plan")
    string_array(
        field(data, "requirement_ids", "$"),
        "$.requirement_ids",
        item_validator=requirement_id,
        sorted_values=True,
    )
    string_array(field(data, "instructions", "$"), "$.instructions", nonempty=True, unique=True)
    string_array(
        field(data, "validation_commands", "$"), "$.validation_commands", unique=True
    )
    assigned_task_ids = string_array(
        data.get("task_ids", []), "$.task_ids", sorted_values=True
    )
    assigned_finding_ids = string_array(
        data.get("finding_ids", []), "$.finding_ids", sorted_values=True
    )
    assigned_validation_ids = string_array(
        data.get("validation_ids", []), "$.validation_ids", sorted_values=True
    )
    packet_id_value = data.get("packet_id")
    if packet_id_value is not None:
        string(packet_id_value, "$.packet_id")
    if profile is not None:
        if stage == "implement":
            profile_packet_max = 4 if profile == "fast" else 3
            if not assigned_task_ids or len(assigned_task_ids) > profile_packet_max:
                fail(
                    "$.task_ids",
                    f"{profile} implementation packets require between one and "
                    f"{profile_packet_max} tasks",
                )
            if packet_id_value is None:
                fail("$.packet_id", "is required for an implementation packet")
        else:
            if assigned_task_ids:
                fail("$.task_ids", "is used only by implementation assignments")
            if packet_id_value is not None:
                fail("$.packet_id", "is used only by implementation assignments")
        if stage in {"fix-1", "fix-2"} and not assigned_finding_ids:
            fail("$.finding_ids", "review fix batches require at least one finding")
        if stage not in {"fix-1", "fix-2", "review-2"} and assigned_finding_ids:
            fail("$.finding_ids", "is not valid for this stage")
        if stage == "validation-fix" and not assigned_validation_ids:
            fail("$.validation_ids", "validation fix batches require at least one validation ID")
        evidence_stages = {"implement", "validate", "fix-1", "fix-2", "pipeline-fix"}
        if stage in evidence_stages and len(assigned_validation_ids) != len(
            data["validation_commands"]
        ):
            fail(
                "$.validation_ids",
                "must pair one planned validation ID with every assigned command",
            )
    if repair_mode:
        validate_repair_assignment(data)
    output_kind = enum(
        field(data, "output_kind", "$"),
        {
            "contract",
            "plan",
            "design-challenge",
            "result",
            "review",
            "integration",
            "delivery",
            "report",
        },
        "$.output_kind",
    )
    expected_outputs = {
        "contract": "contract",
        "plan": "plan",
        "design-challenge": "design-challenge",
        "implement": "result",
        "validate": "result",
        "validation-fix": "result",
        "fix-1": "result",
        "fix-2": "result",
        "review-1": "review",
        "review-2": "review",
        "integrate": "integration",
        "deliver": "delivery",
        "pipeline-fix": "result",
        "report": "report",
    }
    if output_kind != expected_outputs[stage]:
        fail("$.output_kind", f"must be {expected_outputs[stage]!r} for stage {stage!r}")
    absolute_path(field(data, "output_artifact", "$"), "$.output_artifact")
    absolute_path(
        field(data, "log_dir", "$"), "$.log_dir", must_exist=True, directory_only=True
    )
    schema_path_value = data.get("artifact_schema_path", data.get("artifact_contract_path"))
    if schema_path_value is None:
        fail("$", "missing required field 'artifact_schema_path'")
    absolute_path(
        schema_path_value,
        "$.artifact_schema_path",
        must_exist=True,
        file_only=True,
    )
    absolute_path(
        field(data, "validator_path", "$"),
        "$.validator_path",
        must_exist=True,
        file_only=True,
    )


def validate_contract(data: dict[str, Any]) -> None:
    validate_common(data, "contract")
    integer(field(data, "revision", "$"), "$.revision", minimum=1)
    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), {"complete", "blocked"}, "$.status")
    requirement_map = obj(field(data, "requirement_map", "$"), "$.requirement_map")
    if not requirement_map:
        fail("$.requirement_map", "must not be empty")
    known_repos: set[str] = set()
    for req, repos in requirement_map.items():
        requirement_id(req, f"$.requirement_map.{req}")
        known_repos.update(
            string_array(
                repos,
                f"$.requirement_map.{req}",
                item_validator=repo_id,
                nonempty=True,
                sorted_values=True,
            )
        )

    terms = array(field(data, "domain_terms", "$"), "$.domain_terms")
    for index, raw in enumerate(terms):
        loc = f"$.domain_terms[{index}]"
        term = obj(raw, loc)
        string(field(term, "term", loc), f"{loc}.term")
        string(field(term, "meaning", loc), f"{loc}.meaning", max_length=2000)

    rules = array(field(data, "behavior_rules", "$"), "$.behavior_rules")
    for index, raw in enumerate(rules):
        loc = f"$.behavior_rules[{index}]"
        rule = obj(raw, loc)
        string(field(rule, "id", loc), f"{loc}.id")
        string_array(
            field(rule, "requirement_ids", loc),
            f"{loc}.requirement_ids",
            item_validator=requirement_id,
            nonempty=True,
            sorted_values=True,
        )
        string(field(rule, "description", loc), f"{loc}.description", max_length=2000)

    interfaces = array(field(data, "interfaces", "$"), "$.interfaces")
    interface_ids: set[str] = set()
    for index, raw in enumerate(interfaces):
        loc = f"$.interfaces[{index}]"
        interface = obj(raw, loc)
        interface_id = string(field(interface, "id", loc), f"{loc}.id")
        if interface_id in interface_ids:
            fail(f"{loc}.id", "must be unique")
        interface_ids.add(interface_id)
        producer = repo_id(field(interface, "producer_repo_id", loc), f"{loc}.producer_repo_id")
        consumers = string_array(
            field(interface, "consumer_repo_ids", loc),
            f"{loc}.consumer_repo_ids",
            item_validator=repo_id,
            nonempty=True,
            sorted_values=True,
        )
        known_repos.add(producer)
        known_repos.update(consumers)
        string(field(interface, "kind", loc), f"{loc}.kind")
        string(field(interface, "description", loc), f"{loc}.description", max_length=2000)
        string_array(
            field(interface, "evidence_paths", loc),
            f"{loc}.evidence_paths",
            item_validator=lambda value, item_loc: absolute_path(value, item_loc, must_exist=True),
            sorted_values=True,
        )

    dependencies = array(field(data, "dependencies", "$"), "$.dependencies")
    edges: set[tuple[str, str]] = set()
    graph: dict[str, set[str]] = {repo: set() for repo in known_repos}
    for index, raw in enumerate(dependencies):
        loc = f"$.dependencies[{index}]"
        dependency = obj(raw, loc)
        source = repo_id(field(dependency, "from_repo_id", loc), f"{loc}.from_repo_id")
        target = repo_id(field(dependency, "to_repo_id", loc), f"{loc}.to_repo_id")
        if source == target:
            fail(loc, "dependency cannot point to the same repository")
        edge = (source, target)
        if edge in edges:
            fail(loc, "dependency edge must be unique")
        edges.add(edge)
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())
        string(field(dependency, "reason", loc), f"{loc}.reason", max_length=2000)
        string(field(dependency, "evidence", loc), f"{loc}.evidence", max_length=2000)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            fail("$.dependencies", "dependency graph must be acyclic")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, set()):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)

    for name in ("compatibility", "rollout", "cross_repository_validation", "risks", "open_questions"):
        string_array(field(data, name, "$"), f"$.{name}", unique=True)
    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)
    if status == "complete" and data["open_questions"]:
        fail("$.open_questions", "must be empty for a complete contract")


def validate_plan(data: dict[str, Any]) -> None:
    validate_common(data, "plan")
    current_repo = repo_id(field(data, "repo_id", "$"), "$.repo_id")
    revision = integer(field(data, "revision", "$"), "$.revision", minimum=1)
    supersedes_path = optional_hashed_file_reference(
        field(data, "supersedes_plan", "$"), "$.supersedes_plan"
    )
    challenge_path = optional_hashed_file_reference(
        field(data, "design_challenge", "$"), "$.design_challenge"
    )
    revision_basis_value = data.get("revision_basis")
    revision_basis_path: str | None = None
    revision_basis_kind: str | None = None
    if revision_basis_value is not None:
        revision_basis = obj(revision_basis_value, "$.revision_basis")
        revision_basis_kind = enum(
            field(revision_basis, "kind", "$.revision_basis"),
            {"user-feedback", "profile-escalation", "contract-revision"},
            "$.revision_basis.kind",
        )
        revision_basis_path = hashed_file_reference(
            field(revision_basis, "artifact", "$.revision_basis"),
            "$.revision_basis.artifact",
        )
    if challenge_path is not None and revision_basis_path is not None:
        fail("$", "a plan revision must have exactly one revision basis")
    if revision == 1:
        if supersedes_path is not None or challenge_path is not None or revision_basis_path is not None:
            fail("$.revision", "revision 1 must not supersede another plan")
    elif supersedes_path is None or (challenge_path is None and revision_basis_path is None):
        fail(
            "$.revision",
            "later revisions must reference the superseded plan and one challenge/feedback basis",
        )

    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), {"complete", "blocked"}, "$.status")
    baseline = sha(field(data, "baseline", "$"), "$.baseline")
    contract_hash = optional_sha256(
        field(data, "contract_sha256", "$"), "$.contract_sha256"
    )
    if "requirements_sha256" in data:
        sha256(data["requirements_sha256"], "$.requirements_sha256")
    risk_flags = string_array(
        data.get("risk_flags", []),
        "$.risk_flags",
        item_validator=lambda item, item_location: enum(item, RISK_FLAGS, item_location),
        sorted_values=True,
    )
    challenge_required = boolean(
        data.get("design_challenge_required", True),
        "$.design_challenge_required",
    )
    assignment_data = load_json_object(data["assignment_path"], "$.assignment_path")
    assignment_profile = assignment_data.get("profile")
    if assignment_profile is not None:
        requirement_inputs: list[Path] = []
        contract_inputs: list[Path] = []
        for reference in assignment_data.get("input_artifacts", []):
            input_path = Path(reference["path"])
            if input_path.suffix != ".json":
                continue
            input_data = load_json_object(str(input_path), "$.assignment.input_artifacts")
            if input_data.get("artifact_kind") == "requirements":
                requirement_inputs.append(input_path)
            if input_data.get("artifact_kind") == "contract":
                contract_inputs.append(input_path)
        if len(requirement_inputs) != 1:
            fail(
                "$.assignment_path",
                "profiled plan assignments require exactly one requirements artifact",
            )
        expected_requirements_hash = hashlib.sha256(
            requirement_inputs[0].read_bytes()
        ).hexdigest()
        if data.get("requirements_sha256") != expected_requirements_hash:
            fail(
                "$.requirements_sha256",
                f"expected {expected_requirements_hash} from the assigned requirements",
            )
        expected_contract_count = (
            1
            if assignment_data.get(
                "contract_required", assignment_profile == "full"
            )
            else 0
        )
        if len(contract_inputs) != expected_contract_count:
            fail(
                "$.assignment_path",
                f"{assignment_profile} plan assignments require "
                f"{expected_contract_count} contract artifacts",
            )
        expected_contract_hash = (
            hashlib.sha256(contract_inputs[0].read_bytes()).hexdigest()
            if contract_inputs
            else None
        )
        if contract_hash != expected_contract_hash:
            fail(
                "$.contract_sha256",
                "must match the contract selected by the workflow profile",
            )
    challenge_policy = assignment_data.get(
        "design_challenge_policy", "all" if assignment_profile == "full" else "risk-only"
    )
    if challenge_policy == "all" and not challenge_required:
        fail(
            "$.design_challenge_required",
            "the assignment policy requires a design challenge",
        )

    validations = array(field(data, "validations", "$"), "$.validations")
    validation_ids: list[str] = []
    validation_commands: list[str] = []
    has_migration_capable_validation = False
    for index, raw in enumerate(validations):
        loc = f"$.validations[{index}]"
        validation = obj(raw, loc)
        validation_ids.append(string(field(validation, "id", loc), f"{loc}.id"))
        validation_commands.append(
            string(field(validation, "command", loc), f"{loc}.command", max_length=2000)
        )
        absolute_path(field(validation, "cwd", loc), f"{loc}.cwd", must_exist=True, directory_only=True)
        enum(field(validation, "scope", loc), {"focused", "broad", "integration"}, f"{loc}.scope")
        migration_capable = boolean(
            field(validation, "migration_capable", loc), f"{loc}.migration_capable"
        )
        has_migration_capable_validation = has_migration_capable_validation or migration_capable
    if validation_ids != sorted(validation_ids) or len(validation_ids) != len(set(validation_ids)):
        fail("$.validations", "validation IDs must be unique and sorted")
    if len(validation_commands) != len(set(validation_commands)):
        fail("$.validations", "validation commands must be unique")
    if (
        assignment_profile is not None
        and has_migration_capable_validation
        and "database-migration" not in risk_flags
    ):
        fail(
            "$.risk_flags",
            "migration-capable validation requires the database-migration risk flag",
        )

    tasks = array(field(data, "tasks", "$"), "$.tasks")
    task_ids: list[str] = []
    task_requirements: dict[str, set[str]] = {}
    task_mechanisms: dict[str, set[str]] = {}
    for index, raw in enumerate(tasks):
        loc = f"$.tasks[{index}]"
        task = obj(raw, loc)
        task_id = string(field(task, "id", loc), f"{loc}.id")
        task_ids.append(task_id)
        task_requirements[task_id] = set(
            string_array(
                field(task, "requirement_ids", loc),
                f"{loc}.requirement_ids",
                item_validator=requirement_id,
                nonempty=True,
                sorted_values=True,
            )
        )
        string_array(field(task, "depends_on", loc), f"{loc}.depends_on", sorted_values=True)
        string(field(task, "summary", loc), f"{loc}.summary", max_length=1200)
        string_array(field(task, "steps", loc), f"{loc}.steps", nonempty=True)
        string_array(
            field(task, "expected_files", loc),
            f"{loc}.expected_files",
            item_validator=relative_repo_path,
            sorted_values=True,
        )
        referenced_validations = string_array(
            field(task, "validation_ids", loc),
            f"{loc}.validation_ids",
            nonempty=True,
            sorted_values=True,
        )
        missing = set(referenced_validations) - set(validation_ids)
        if missing:
            fail(f"{loc}.validation_ids", f"unknown validation IDs: {sorted(missing)}")
        task_mechanisms[task_id] = set(
            string_array(
                field(task, "mechanism_ids", loc),
                f"{loc}.mechanism_ids",
                sorted_values=True,
            )
        )
    if task_ids != sorted(task_ids) or len(task_ids) != len(set(task_ids)):
        fail("$.tasks", "task IDs must be unique and sorted")

    dependency_graph: dict[str, set[str]] = {}
    for index, raw in enumerate(tasks):
        dependencies = set(raw["depends_on"])
        unknown = dependencies - set(task_ids)
        if unknown:
            fail(f"$.tasks[{index}].depends_on", f"unknown task IDs: {sorted(unknown)}")
        if raw["id"] in dependencies:
            fail(f"$.tasks[{index}].depends_on", "task cannot depend on itself")
        dependency_graph[raw["id"]] = dependencies
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_task(task_id: str) -> None:
        if task_id in visiting:
            fail("$.tasks", "task dependency graph must be acyclic")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependency_graph.get(task_id, set()):
            visit_task(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(dependency_graph):
        visit_task(task_id)

    work_packets_value = data.get("work_packets")
    if assignment_profile is not None and status == "complete" and work_packets_value is None:
        fail("$.work_packets", "profiled plans must define bounded work packets")
    if work_packets_value is not None:
        work_packets = array(work_packets_value, "$.work_packets")
        packet_ids: list[str] = []
        packet_task_owner: dict[str, str] = {}
        packet_dependencies: dict[str, set[str]] = {}
        for index, raw in enumerate(work_packets):
            loc = f"$.work_packets[{index}]"
            packet = obj(raw, loc)
            packet_id = string(field(packet, "id", loc), f"{loc}.id")
            packet_ids.append(packet_id)
            string(field(packet, "summary", loc), f"{loc}.summary", max_length=1200)
            packet_tasks = string_array(
                field(packet, "task_ids", loc),
                f"{loc}.task_ids",
                nonempty=True,
                sorted_values=True,
            )
            profile_packet_max = 4 if assignment_profile in {None, "fast"} else 3
            if len(packet_tasks) > profile_packet_max:
                fail(
                    f"{loc}.task_ids",
                    f"a {assignment_profile or 'legacy'} work packet may contain at most "
                    f"{profile_packet_max} tasks",
                )
            for packet_task in packet_tasks:
                if packet_task not in task_ids:
                    fail(f"{loc}.task_ids", f"unknown task ID: {packet_task}")
                if packet_task in packet_task_owner:
                    fail(
                        f"{loc}.task_ids",
                        f"task {packet_task} is already in {packet_task_owner[packet_task]}",
                    )
                packet_task_owner[packet_task] = packet_id
            packet_dependencies[packet_id] = set(
                string_array(
                    field(packet, "depends_on", loc),
                    f"{loc}.depends_on",
                    sorted_values=True,
                )
            )
            estimated = integer(
                field(packet, "estimated_minutes", loc),
                f"{loc}.estimated_minutes",
                minimum=5,
            )
            max_estimated = 45 if assignment_profile is not None else 60
            if estimated > max_estimated:
                fail(f"{loc}.estimated_minutes", f"must be at most {max_estimated}")
        if packet_ids != sorted(packet_ids) or len(packet_ids) != len(set(packet_ids)):
            fail("$.work_packets", "packet IDs must be unique and sorted")
        if set(packet_task_owner) != set(task_ids):
            missing_tasks = sorted(set(task_ids) - set(packet_task_owner))
            fail("$.work_packets", f"must cover every task exactly once; missing {missing_tasks}")
        known_packets = set(packet_ids)
        for packet_id, dependencies in packet_dependencies.items():
            unknown_packets = dependencies - known_packets
            if unknown_packets:
                fail(
                    "$.work_packets",
                    f"packet {packet_id} has unknown dependencies: {sorted(unknown_packets)}",
                )
            if packet_id in dependencies:
                fail("$.work_packets", f"packet {packet_id} cannot depend on itself")
        for task_id_value, dependencies in dependency_graph.items():
            owner = packet_task_owner[task_id_value]
            required_packet_dependencies = {
                packet_task_owner[dependency]
                for dependency in dependencies
                if packet_task_owner[dependency] != owner
            }
            if not required_packet_dependencies <= packet_dependencies[owner]:
                fail(
                    "$.work_packets",
                    f"packet {owner} must depend on {sorted(required_packet_dependencies)}",
                )
        visiting_packets: set[str] = set()
        visited_packets: set[str] = set()

        def visit_packet(packet_id: str) -> None:
            if packet_id in visiting_packets:
                fail("$.work_packets", "packet dependency graph must be acyclic")
            if packet_id in visited_packets:
                return
            visiting_packets.add(packet_id)
            for dependency in packet_dependencies[packet_id]:
                visit_packet(dependency)
            visiting_packets.remove(packet_id)
            visited_packets.add(packet_id)

        for packet_id in packet_ids:
            visit_packet(packet_id)

    mechanisms = array(field(data, "complexity_mechanisms", "$"), "$.complexity_mechanisms")
    mechanism_ids: list[str] = []
    mechanism_tasks: dict[str, set[str]] = {}
    for index, raw in enumerate(mechanisms):
        loc = f"$.complexity_mechanisms[{index}]"
        mechanism = obj(raw, loc)
        mechanism_id = string(field(mechanism, "id", loc), f"{loc}.id")
        mechanism_ids.append(mechanism_id)
        enum(field(mechanism, "type", loc), HIGH_COST_MECHANISM_TYPES, f"{loc}.type")
        mechanism_requirements = set(
            string_array(
                field(mechanism, "requirement_ids", loc),
                f"{loc}.requirement_ids",
                item_validator=requirement_id,
                nonempty=True,
                sorted_values=True,
            )
        )
        referenced_tasks = set(
            string_array(
                field(mechanism, "task_ids", loc),
                f"{loc}.task_ids",
                nonempty=True,
                sorted_values=True,
            )
        )
        unknown_tasks = referenced_tasks - set(task_ids)
        if unknown_tasks:
            fail(f"{loc}.task_ids", f"unknown task IDs: {sorted(unknown_tasks)}")
        linked_requirements = set().union(
            *(task_requirements[task_id] for task_id in referenced_tasks)
        )
        if not mechanism_requirements <= linked_requirements:
            fail(f"{loc}.requirement_ids", "must be covered by the referenced tasks")
        mechanism_tasks[mechanism_id] = referenced_tasks
        string(field(mechanism, "summary", loc), f"{loc}.summary", max_length=1200)
        string(field(mechanism, "necessity", loc), f"{loc}.necessity", max_length=2000)
        string(
            field(mechanism, "repository_evidence", loc),
            f"{loc}.repository_evidence",
            max_length=2000,
        )
        string_array(
            field(mechanism, "simpler_alternatives", loc),
            f"{loc}.simpler_alternatives",
            nonempty=True,
        )
        string_array(
            field(mechanism, "operational_considerations", loc),
            f"{loc}.operational_considerations",
            nonempty=True,
        )
        mechanism_validations = set(
            string_array(
                field(mechanism, "validation_ids", loc),
                f"{loc}.validation_ids",
                nonempty=True,
                sorted_values=True,
            )
        )
        missing_validations = mechanism_validations - set(validation_ids)
        if missing_validations:
            fail(f"{loc}.validation_ids", f"unknown validation IDs: {sorted(missing_validations)}")
    if mechanism_ids != sorted(mechanism_ids) or len(mechanism_ids) != len(set(mechanism_ids)):
        fail("$.complexity_mechanisms", "mechanism IDs must be unique and sorted")

    if mechanisms and not challenge_required:
        fail(
            "$.design_challenge_required",
            "plans with high-cost mechanisms require a design challenge",
        )
    if set(risk_flags) & HIGH_RISK_FLAGS and not challenge_required:
        fail(
            "$.design_challenge_required",
            "high-risk plans require a design challenge",
        )
    if assignment_profile == "fast" and challenge_required and not (mechanisms or risk_flags):
        fail(
            "$.design_challenge_required",
            "a low-risk fast-profile plan must use the bounded no-critic path",
        )

    known_mechanisms = set(mechanism_ids)
    for index, task_id in enumerate(task_ids):
        unknown_mechanisms = task_mechanisms[task_id] - known_mechanisms
        if unknown_mechanisms:
            fail(
                f"$.tasks[{index}].mechanism_ids",
                f"unknown mechanism IDs: {sorted(unknown_mechanisms)}",
            )
    for mechanism_id, referenced_tasks in mechanism_tasks.items():
        linked_from_tasks = {
            task_id for task_id, references in task_mechanisms.items() if mechanism_id in references
        }
        if linked_from_tasks != referenced_tasks:
            fail(
                "$.complexity_mechanisms",
                f"task links for {mechanism_id} must be reciprocal",
            )

    resolutions = array(field(data, "finding_resolutions", "$"), "$.finding_resolutions")
    resolution_ids: list[str] = []
    for index, raw in enumerate(resolutions):
        loc = f"$.finding_resolutions[{index}]"
        resolution = obj(raw, loc)
        resolution_ids.append(string(field(resolution, "finding_id", loc), f"{loc}.finding_id"))
        enum(field(resolution, "outcome", loc), {"resolved", "inapplicable"}, f"{loc}.outcome")
        string(field(resolution, "summary", loc), f"{loc}.summary", max_length=1200)
        string(field(resolution, "evidence", loc), f"{loc}.evidence", max_length=2000)
    if resolution_ids != sorted(resolution_ids) or len(resolution_ids) != len(set(resolution_ids)):
        fail("$.finding_resolutions", "finding IDs must be unique and sorted")

    if revision == 1 and resolutions:
        fail("$.finding_resolutions", "revision 1 cannot resolve a preceding challenge")
    if supersedes_path is not None and revision_basis_path is not None:
        superseded = load_json_object(supersedes_path, "$.supersedes_plan.path")
        if superseded.get("artifact_kind") != "plan":
            fail("$.supersedes_plan.path", "must reference a plan artifact")
        if superseded.get("repo_id") != current_repo or superseded.get("baseline") != baseline:
            fail("$.supersedes_plan", "must reference the preceding plan for this repository/baseline")
        previous_revision = integer(
            field(superseded, "revision", "$.supersedes_plan"),
            "$.supersedes_plan.revision",
            minimum=1,
        )
        if revision != previous_revision + 1:
            fail("$.revision", "must be exactly one greater than the superseded plan revision")
        if resolutions:
            fail(
                "$.finding_resolutions",
                "feedback/profile/contract revisions do not resolve design-challenge finding IDs",
            )
        assignment = load_json_object(data["assignment_path"], "$.assignment_path")
        assignment_inputs = {
            reference["path"]
            for reference in array(
                assignment.get("input_artifacts"),
                "$.assignment.input_artifacts",
            )
        }
        if supersedes_path not in assignment_inputs or revision_basis_path not in assignment_inputs:
            fail(
                "$.assignment_path",
                f"{revision_basis_kind} revision must pin the prior plan and its revision basis",
            )

    if supersedes_path is not None and challenge_path is not None:
        superseded = load_json_object(supersedes_path, "$.supersedes_plan.path")
        challenge = load_json_object(challenge_path, "$.design_challenge.path")
        if superseded.get("artifact_kind") != "plan":
            fail("$.supersedes_plan.path", "must reference a plan artifact")
        if challenge.get("artifact_kind") != "design-challenge":
            fail("$.design_challenge.path", "must reference a design-challenge artifact")
        if superseded.get("repo_id") != current_repo or challenge.get("repo_id") != current_repo:
            fail("$", "revision references must have the same repo_id as the plan")
        if superseded.get("baseline") != baseline or challenge.get("baseline") != baseline:
            fail("$", "revision references must use the same baseline")
        previous_revision = integer(
            field(superseded, "revision", "$.supersedes_plan"),
            "$.supersedes_plan.revision",
            minimum=1,
        )
        if revision != previous_revision + 1:
            fail("$.revision", "must be exactly one greater than the superseded plan revision")
        challenge_plan = obj(
            field(challenge, "plan", "$.design_challenge"),
            "$.design_challenge.plan",
        )
        expected_superseded_hash = sha256(
            field(data["supersedes_plan"], "sha256", "$.supersedes_plan"),
            "$.supersedes_plan.sha256",
        )
        if challenge_plan.get("sha256") != expected_superseded_hash:
            fail("$.design_challenge", "must challenge the superseded plan")
        challenge_verdict = challenge.get("verdict")
        if challenge_verdict not in {"revise-plan", "revise-contract"}:
            fail("$.design_challenge", "must have a revision verdict")
        if challenge_verdict == "revise-plan" and challenge.get("contract_sha256") != contract_hash:
            fail("$.contract_sha256", "plan-only revisions must retain the challenged contract")
        if (
            challenge_verdict == "revise-contract"
            and challenge.get("contract_sha256") == contract_hash
        ):
            fail(
                "$.contract_sha256",
                "contract-driven revisions require a new contract hash",
            )
        actionable_ids: list[str] = []
        for index, raw in enumerate(
            array(
                field(challenge, "findings", "$.design_challenge"),
                "$.design_challenge.findings",
            )
        ):
            finding = obj(raw, f"$.design_challenge.findings[{index}]")
            if boolean(
                field(finding, "actionable", f"$.design_challenge.findings[{index}]"),
                f"$.design_challenge.findings[{index}].actionable",
            ):
                actionable_ids.append(
                    string(
                        field(finding, "id", f"$.design_challenge.findings[{index}]"),
                        f"$.design_challenge.findings[{index}].id",
                    )
                )
        actionable_ids.sort()
        if status == "complete" and resolution_ids != actionable_ids:
            fail(
                "$.finding_resolutions",
                f"must resolve exactly the actionable challenge findings: {actionable_ids}",
            )
        if status == "blocked" and not set(resolution_ids) <= set(actionable_ids):
            fail(
                "$.finding_resolutions",
                "blocked revisions may resolve only findings from the referenced challenge",
            )
        assignment = load_json_object(data["assignment_path"], "$.assignment_path")
        assignment_inputs = {
            reference["path"]
            for reference in array(
                assignment.get("input_artifacts"),
                "$.assignment.input_artifacts",
            )
        }
        if supersedes_path not in assignment_inputs or challenge_path not in assignment_inputs:
            fail(
                "$.assignment_path",
                "plan revision assignment must pin the prior plan and challenge",
            )

    string_array(field(data, "non_goals", "$"), "$.non_goals", unique=True)
    string_array(field(data, "risks", "$"), "$.risks", unique=True)
    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)
    if status == "complete" and (not tasks or not validations):
        fail("$", "a complete plan must contain tasks and validations")


def validate_design_challenge(data: dict[str, Any]) -> None:
    validate_common(data, "design-challenge")
    current_repo = repo_id(field(data, "repo_id", "$"), "$.repo_id")
    integer(field(data, "attempt", "$"), "$.attempt", minimum=1)
    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), {"complete", "blocked"}, "$.status")
    baseline = sha(field(data, "baseline", "$"), "$.baseline")
    contract_hash = optional_sha256(
        field(data, "contract_sha256", "$"), "$.contract_sha256"
    )
    plan_path = hashed_file_reference(field(data, "plan", "$"), "$.plan")
    plan = load_json_object(plan_path, "$.plan.path")
    if plan.get("artifact_kind") != "plan":
        fail("$.plan.path", "must reference a plan artifact")
    if plan.get("repo_id") != current_repo:
        fail("$.plan.path", "plan repo_id must match the challenge")
    if plan.get("baseline") != baseline:
        fail("$.baseline", "must match the referenced plan")
    if plan.get("contract_sha256") != contract_hash:
        fail("$.contract_sha256", "must match the referenced plan")

    mode = enum(field(data, "mode", "$"), {"full", "verification"}, "$.mode")
    plan_revision = integer(field(plan, "revision", "$.plan"), "$.plan.revision", minimum=1)
    if mode == "verification" and plan_revision <= 1:
        fail("$.mode", "verification requires a revised plan")
    verdict = enum(
        field(data, "verdict", "$"),
        {"accept", "revise-plan", "revise-contract", "blocked"},
        "$.verdict",
    )
    string(field(data, "summary", "$"), "$.summary", max_length=1200)

    known_mechanisms: set[str] = set()
    for index, raw in enumerate(
        array(
            field(plan, "complexity_mechanisms", "$.plan"),
            "$.plan.complexity_mechanisms",
        )
    ):
        mechanism = obj(raw, f"$.plan.complexity_mechanisms[{index}]")
        known_mechanisms.add(
            string(
                field(mechanism, "id", f"$.plan.complexity_mechanisms[{index}]"),
                f"$.plan.complexity_mechanisms[{index}].id",
            )
        )
    assessments = array(field(data, "mechanism_assessments", "$"), "$.mechanism_assessments")
    assessment_ids: list[str] = []
    assessment_decisions: dict[str, str] = {}
    for index, raw in enumerate(assessments):
        loc = f"$.mechanism_assessments[{index}]"
        assessment = obj(raw, loc)
        mechanism_id = string(field(assessment, "mechanism_id", loc), f"{loc}.mechanism_id")
        assessment_ids.append(mechanism_id)
        assessment_decisions[mechanism_id] = enum(
            field(assessment, "decision", loc),
            {"retain", "replace", "remove"},
            f"{loc}.decision",
        )
        string(
            field(assessment, "necessity_assessment", loc),
            f"{loc}.necessity_assessment",
            max_length=2000,
        )
        string(
            field(assessment, "repository_evidence", loc),
            f"{loc}.repository_evidence",
            max_length=2000,
        )
        string(
            field(assessment, "simpler_alternative", loc),
            f"{loc}.simpler_alternative",
            max_length=2000,
        )
        string(
            field(assessment, "operational_risk", loc),
            f"{loc}.operational_risk",
            max_length=2000,
        )
    if assessment_ids != sorted(assessment_ids) or len(assessment_ids) != len(set(assessment_ids)):
        fail("$.mechanism_assessments", "mechanism IDs must be unique and sorted")
    if status == "complete" and set(assessment_ids) != known_mechanisms:
        fail(
            "$.mechanism_assessments",
            f"must assess exactly the plan mechanisms: {sorted(known_mechanisms)}",
        )
    if status == "blocked" and not set(assessment_ids) <= known_mechanisms:
        fail(
            "$.mechanism_assessments",
            "blocked challenges may assess only mechanisms from the referenced plan",
        )

    findings = array(field(data, "findings", "$"), "$.findings")
    finding_ids: set[str] = set()
    sort_keys: list[tuple[int, str, str]] = []
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    actionable_plan_findings: list[dict[str, Any]] = []
    actionable_contract_findings: list[dict[str, Any]] = []
    actionable_by_mechanism: set[str] = set()
    known_tasks: set[str] = set()
    known_requirements: set[str] = set()
    for index, raw in enumerate(array(field(plan, "tasks", "$.plan"), "$.plan.tasks")):
        task = obj(raw, f"$.plan.tasks[{index}]")
        known_tasks.add(
            string(
                field(task, "id", f"$.plan.tasks[{index}]"),
                f"$.plan.tasks[{index}].id",
            )
        )
        known_requirements.update(
            string_array(
                field(task, "requirement_ids", f"$.plan.tasks[{index}]"),
                f"$.plan.tasks[{index}].requirement_ids",
                item_validator=requirement_id,
            )
        )
    for index, raw in enumerate(findings):
        loc = f"$.findings[{index}]"
        finding = obj(raw, loc)
        finding_id = string(field(finding, "id", loc), f"{loc}.id")
        if finding_id in finding_ids:
            fail(f"{loc}.id", "must be unique")
        finding_ids.add(finding_id)
        target = enum(field(finding, "target", loc), {"plan", "contract"}, f"{loc}.target")
        enum(field(finding, "category", loc), DESIGN_FINDING_CATEGORIES, f"{loc}.category")
        severity = enum(field(finding, "severity", loc), set(severity_rank), f"{loc}.severity")
        actionable = boolean(field(finding, "actionable", loc), f"{loc}.actionable")
        finding_requirements = set(
            string_array(
                field(finding, "requirement_ids", loc),
                f"{loc}.requirement_ids",
                item_validator=requirement_id,
                nonempty=True,
                sorted_values=True,
            )
        )
        unknown_requirements = finding_requirements - known_requirements
        if unknown_requirements:
            fail(
                f"{loc}.requirement_ids",
                "requirements are not covered by the referenced plan: "
                f"{sorted(unknown_requirements)}",
            )
        task_ids = set(
            string_array(
                field(finding, "task_ids", loc),
                f"{loc}.task_ids",
                nonempty=target == "plan",
                sorted_values=True,
            )
        )
        unknown_tasks = task_ids - known_tasks
        if unknown_tasks:
            fail(f"{loc}.task_ids", f"unknown task IDs: {sorted(unknown_tasks)}")
        mechanism_id = field(finding, "mechanism_id", loc)
        if mechanism_id is not None:
            mechanism_id = string(mechanism_id, f"{loc}.mechanism_id")
            if mechanism_id not in known_mechanisms:
                fail(f"{loc}.mechanism_id", "must identify a mechanism in the referenced plan")
        string(field(finding, "summary", loc), f"{loc}.summary", max_length=1200)
        string(field(finding, "evidence", loc), f"{loc}.evidence", max_length=2000)
        string(
            field(finding, "simpler_alternative", loc),
            f"{loc}.simpler_alternative",
            max_length=2000,
        )
        string(field(finding, "required_change", loc), f"{loc}.required_change", max_length=2000)
        sort_keys.append((severity_rank[severity], target, finding_id))
        if actionable:
            if target == "plan":
                actionable_plan_findings.append(finding)
            else:
                actionable_contract_findings.append(finding)
            if mechanism_id is not None:
                actionable_by_mechanism.add(mechanism_id)
    if sort_keys != sorted(sort_keys):
        fail("$.findings", "must be sorted by severity, target, and ID")

    for mechanism_id, decision in assessment_decisions.items():
        if decision in {"replace", "remove"} and mechanism_id not in actionable_by_mechanism:
            fail(
                "$.mechanism_assessments",
                f"{decision} decision for {mechanism_id} requires an actionable linked finding",
            )

    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)
    if status == "blocked":
        if verdict != "blocked":
            fail("$.verdict", "blocked status requires blocked verdict")
    elif verdict == "blocked":
        fail("$.verdict", "blocked verdict requires blocked status")
    if verdict == "accept" and (actionable_plan_findings or actionable_contract_findings):
        fail("$.verdict", "accept verdict cannot contain actionable findings")
    if verdict == "revise-plan":
        if not actionable_plan_findings:
            fail("$.verdict", "revise-plan requires an actionable plan finding")
        if actionable_contract_findings:
            fail("$.verdict", "contract findings require revise-contract verdict")
    if verdict == "revise-contract" and not actionable_contract_findings:
        fail("$.verdict", "revise-contract requires an actionable contract finding")

    assignment = load_json_object(data["assignment_path"], "$.assignment_path")
    assignment_inputs = {
        reference["path"]
        for reference in array(
            assignment.get("input_artifacts"),
            "$.assignment.input_artifacts",
        )
    }
    if plan_path not in assignment_inputs:
        fail("$.assignment_path", "design-challenge assignment must pin the referenced plan")


def validate_validation_records(
    value: Any,
    location: str,
    *,
    tree_fingerprint: str | None = None,
    require_cache_metadata: bool = False,
) -> None:
    records = array(value, location)
    ids: set[str] = set()
    for index, raw in enumerate(records):
        loc = f"{location}[{index}]"
        record = obj(raw, loc)
        record_id = string(field(record, "id", loc), f"{loc}.id")
        if record_id in ids:
            fail(f"{loc}.id", "must be unique")
        ids.add(record_id)
        command = string(field(record, "command", loc), f"{loc}.command", max_length=2000)
        command_hash_value = record.get("command_sha256")
        if command_hash_value is not None:
            parsed_command_hash = sha256(command_hash_value, f"{loc}.command_sha256")
            expected_command_hash = hashlib.sha256(command.encode("utf-8")).hexdigest()
            if parsed_command_hash != expected_command_hash:
                fail(f"{loc}.command_sha256", f"expected {expected_command_hash} from command")
        elif require_cache_metadata:
            fail(f"{loc}.command_sha256", "is required for profiled validation evidence")
        record_tree = record.get("tree_fingerprint")
        if record_tree is not None:
            parsed_tree = sha256(record_tree, f"{loc}.tree_fingerprint")
            if tree_fingerprint is not None and parsed_tree != tree_fingerprint:
                fail(f"{loc}.tree_fingerprint", "must match the result tree_fingerprint")
        elif require_cache_metadata:
            fail(f"{loc}.tree_fingerprint", "is required for profiled validation evidence")
        cache_status = record.get("cache_status")
        source_artifact = record.get("source_artifact")
        if cache_status is not None:
            parsed_cache_status = enum(
                cache_status, {"fresh", "reused"}, f"{loc}.cache_status"
            )
            if parsed_cache_status == "fresh" and source_artifact is not None:
                fail(f"{loc}.source_artifact", "must be null for fresh evidence")
            if parsed_cache_status == "reused":
                if source_artifact is None:
                    fail(f"{loc}.source_artifact", "is required for reused evidence")
                source_path = hashed_file_reference(
                    source_artifact, f"{loc}.source_artifact"
                )
                if (
                    CURRENT_ARTIFACT_PATH is not None
                    and Path(source_path).resolve() == CURRENT_ARTIFACT_PATH.resolve()
                ):
                    fail(f"{loc}.source_artifact", "cannot reuse evidence from itself")
                source = load_json_object(source_path, f"{loc}.source_artifact.path")
                if source.get("artifact_kind") != "result":
                    fail(f"{loc}.source_artifact", "must reference a result artifact")
                if source.get("tree_fingerprint") != record_tree:
                    fail(
                        f"{loc}.source_artifact",
                        "source result must have the same tree fingerprint",
                    )
                matching_source_records = [
                    candidate
                    for candidate in source.get("validations", [])
                    if isinstance(candidate, dict) and candidate.get("id") == record_id
                ]
                if len(matching_source_records) != 1:
                    fail(
                        f"{loc}.source_artifact",
                        f"must contain exactly one validation record for {record_id}",
                    )
                source_record = matching_source_records[0]
                if (
                    source_record.get("result") != "pass"
                    or source_record.get("command") != command
                    or source_record.get("command_sha256") != command_hash_value
                    or source_record.get("tree_fingerprint") != record_tree
                ):
                    fail(
                        f"{loc}.source_artifact",
                        "reused evidence must match a passing command and tree fingerprint",
                    )
        elif require_cache_metadata:
            fail(f"{loc}.cache_status", "is required for profiled validation evidence")
        absolute_path(field(record, "cwd", loc), f"{loc}.cwd", must_exist=True, directory_only=True)
        exit_code = field(record, "exit_code", loc)
        if exit_code is not None:
            integer(exit_code, f"{loc}.exit_code")
        result = enum(field(record, "result", loc), {"pass", "fail", "not-run"}, f"{loc}.result")
        if result == "pass" and exit_code != 0:
            fail(f"{loc}.exit_code", "must be 0 when result is pass")
        if result == "not-run" and exit_code is not None:
            fail(f"{loc}.exit_code", "must be null when result is not-run")
        string(field(record, "summary", loc), f"{loc}.summary", max_length=1200)
        log_path = field(record, "log_path", loc)
        if log_path is not None:
            absolute_path(log_path, f"{loc}.log_path", must_exist=True, file_only=True)
        elif result != "not-run":
            fail(f"{loc}.log_path", "is required when the command ran")


def validate_result(data: dict[str, Any]) -> None:
    validate_common(data, "result")
    repo_id(field(data, "repo_id", "$"), "$.repo_id")
    enum(field(data, "stage", "$"), RESULT_STAGES, "$.stage")
    integer(field(data, "attempt", "$"), "$.attempt", minimum=1)
    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), ARTIFACT_STATUSES, "$.status")
    string(field(data, "summary", "$"), "$.summary", max_length=1200)
    string_array(
        field(data, "requirement_ids", "$"),
        "$.requirement_ids",
        item_validator=requirement_id,
        sorted_values=True,
    )
    string_array(field(data, "task_ids", "$"), "$.task_ids", sorted_values=True)
    string_array(
        field(data, "changed_files", "$"),
        "$.changed_files",
        item_validator=relative_repo_path,
        sorted_values=True,
    )
    assignment = load_json_object(data["assignment_path"], "$.assignment_path")
    profiled = assignment.get("profile") is not None
    tree_fingerprint_value = data.get("tree_fingerprint")
    parsed_tree_fingerprint: str | None = None
    if tree_fingerprint_value is not None:
        parsed_tree_fingerprint = sha256(tree_fingerprint_value, "$.tree_fingerprint")
    elif profiled:
        fail("$.tree_fingerprint", "is required for profiled result artifacts")
    validation_records = field(data, "validations", "$")
    validate_validation_records(
        validation_records,
        "$.validations",
        tree_fingerprint=parsed_tree_fingerprint,
        require_cache_metadata=profiled,
    )
    if profiled and status == "complete" and data["stage"] == "validate" and not validation_records:
        fail("$.validations", "a complete validation result must contain evidence")
    if profiled and status == "complete" and data["stage"] in {
        "implement",
        "validate",
        "fix-1",
        "fix-2",
        "pipeline-fix",
    }:
        expected_evidence = set(
            zip(
                assignment.get("validation_ids", []),
                assignment.get("validation_commands", []),
                strict=True,
            )
        )
        actual_evidence = {
            (record.get("id"), record.get("command"))
            for record in validation_records
            if isinstance(record, dict)
        }
        missing_evidence = expected_evidence - actual_evidence
        if missing_evidence:
            fail(
                "$.validations",
                "missing assigned validation evidence: "
                f"{sorted(validation_id for validation_id, _ in missing_evidence)}",
            )

    decisions = array(field(data, "decisions", "$"), "$.decisions")
    for index, raw in enumerate(decisions):
        loc = f"$.decisions[{index}]"
        decision = obj(raw, loc)
        string(field(decision, "id", loc), f"{loc}.id")
        if "kind" in decision:
            enum(field(decision, "kind", loc), DECISION_KINDS, f"{loc}.kind")
        elif profiled:
            fail(f"{loc}.kind", "is required for profiled result artifacts")
        string(field(decision, "summary", loc), f"{loc}.summary", max_length=1200)
        string(field(decision, "evidence", loc), f"{loc}.evidence", max_length=2000)

    resolutions = array(field(data, "resolutions", "$"), "$.resolutions")
    finding_ids: set[str] = set()
    for index, raw in enumerate(resolutions):
        loc = f"$.resolutions[{index}]"
        resolution = obj(raw, loc)
        finding_id = string(field(resolution, "finding_id", loc), f"{loc}.finding_id")
        if finding_id in finding_ids:
            fail(f"{loc}.finding_id", "must be unique")
        finding_ids.add(finding_id)
        enum(field(resolution, "outcome", loc), {"fixed", "inapplicable"}, f"{loc}.outcome")
        string(field(resolution, "summary", loc), f"{loc}.summary", max_length=1200)
        absolute_path(
            field(resolution, "evidence_path", loc),
            f"{loc}.evidence_path",
            must_exist=True,
        )

    git = obj(field(data, "git", "$"), "$.git")
    sha(field(git, "head", "$.git"), "$.git.head")
    absolute_path(
        field(git, "status_short_path", "$.git"),
        "$.git.status_short_path",
        must_exist=True,
        file_only=True,
    )
    if profiled:
        assigned_requirements = set(
            string_array(
                assignment.get("requirement_ids", []),
                "$.assignment.requirement_ids",
                item_validator=requirement_id,
                sorted_values=True,
            )
        )
        claimed_requirements = set(data["requirement_ids"])
        if not claimed_requirements <= assigned_requirements:
            fail(
                "$.requirement_ids",
                f"claims requirements outside the assignment: "
                f"{sorted(claimed_requirements - assigned_requirements)}",
            )
    if profiled and data["stage"] == "implement":
        expected_tasks = string_array(
            assignment.get("task_ids", []),
            "$.assignment.task_ids",
            sorted_values=True,
        )
        if data["task_ids"] != expected_tasks:
            fail("$.task_ids", f"must exactly match the implementation packet: {expected_tasks}")
        packet_id_value = field(data, "packet_id", "$")
        if packet_id_value != assignment.get("packet_id"):
            fail("$.packet_id", "must match the assignment packet_id")
    elif "packet_id" in data and data["packet_id"] is not None:
        string(data["packet_id"], "$.packet_id")
    if profiled and data["stage"] in {"fix-1", "fix-2"} and status == "complete":
        expected_findings = string_array(
            assignment.get("finding_ids", []),
            "$.assignment.finding_ids",
            sorted_values=True,
        )
        if sorted(finding_ids) != expected_findings:
            fail("$.resolutions", f"must resolve exactly the assigned findings: {expected_findings}")

    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)
    next_action = field(data, "next_action", "$")
    if next_action is not None:
        string(next_action, "$.next_action", max_length=300)
    if assignment.get("execution_mode") == "artifact-repair":
        validate_repaired_payload(assignment, data)


def validate_review(data: dict[str, Any]) -> None:
    validate_common(data, "review")
    repo_id(field(data, "repo_id", "$"), "$.repo_id")
    round_number = integer(field(data, "round", "$"), "$.round", minimum=1)
    if round_number not in {1, 2}:
        fail("$.round", "must be 1 or 2")
    assignment = load_json_object(data["assignment_path"], "$.assignment_path")
    profiled = assignment.get("profile") is not None
    mode_value = data.get("mode")
    if mode_value is not None:
        mode = enum(mode_value, {"full", "verification"}, "$.mode")
        if round_number == 1 and mode != "full":
            fail("$.mode", "round one must be a full review")
        if round_number == 2 and mode != "verification":
            fail("$.mode", "round two must verify the preceding fix batch")
    elif profiled:
        fail("$.mode", "is required for profiled reviews")
    verified_finding_ids = string_array(
        data.get("verified_finding_ids", []),
        "$.verified_finding_ids",
        sorted_values=True,
    )
    if profiled and round_number == 1 and verified_finding_ids:
        fail("$.verified_finding_ids", "round one does not verify earlier findings")
    if profiled and round_number == 2:
        assigned_findings = string_array(
            assignment.get("finding_ids", []),
            "$.assignment.finding_ids",
            nonempty=True,
            sorted_values=True,
        )
        if verified_finding_ids != assigned_findings:
            fail(
                "$.verified_finding_ids",
                f"must match the assigned verification findings: {assigned_findings}",
            )
    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), {"complete", "blocked"}, "$.status")
    sha(field(data, "baseline", "$"), "$.baseline")
    absolute_path(
        field(data, "reviewed_status_path", "$"),
        "$.reviewed_status_path",
        must_exist=True,
        file_only=True,
    )
    findings = array(field(data, "findings", "$"), "$.findings")
    ids: set[str] = set()
    sort_keys: list[tuple[int, str, int, str]] = []
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for index, raw in enumerate(findings):
        loc = f"$.findings[{index}]"
        finding = obj(raw, loc)
        finding_id = string(field(finding, "id", loc), f"{loc}.id")
        if finding_id in ids:
            fail(f"{loc}.id", "must be unique")
        ids.add(finding_id)
        enum(field(finding, "category", loc), {"standards", "spec"}, f"{loc}.category")
        severity = enum(field(finding, "severity", loc), set(severity_rank), f"{loc}.severity")
        actionable = boolean(field(finding, "actionable", loc), f"{loc}.actionable")
        disposition_value = finding.get("disposition")
        if disposition_value is not None:
            disposition = enum(
                disposition_value,
                REVIEW_DISPOSITIONS,
                f"{loc}.disposition",
            )
            if not actionable and disposition != "advisory":
                fail(f"{loc}.disposition", "non-actionable findings must be advisory")
            if actionable and severity in {"critical", "high", "medium"} and disposition != "must-fix":
                fail(
                    f"{loc}.disposition",
                    "critical, high, and medium findings must block delivery",
                )
        elif profiled:
            fail(f"{loc}.disposition", "is required for profiled reviews")
        req = field(finding, "requirement_id", loc)
        if req is not None:
            requirement_id(req, f"{loc}.requirement_id")
        path = relative_repo_path(field(finding, "path", loc), f"{loc}.path")
        line = field(finding, "line", loc)
        parsed_line = 0 if line is None else integer(line, f"{loc}.line", minimum=1)
        string(field(finding, "summary", loc), f"{loc}.summary", max_length=1200)
        string(field(finding, "evidence", loc), f"{loc}.evidence", max_length=2000)
        sort_keys.append((severity_rank[severity], path, parsed_line, finding_id))
    if sort_keys != sorted(sort_keys):
        fail("$.findings", "must be sorted by severity, path, line, and ID")
    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)


def validate_integration(data: dict[str, Any]) -> None:
    validate_common(data, "integration")
    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), {"complete", "blocked", "failed"}, "$.status")
    matrix = array(field(data, "requirement_matrix", "$"), "$.requirement_matrix")
    if not matrix:
        fail("$.requirement_matrix", "must not be empty")
    requirement_ids: list[str] = []
    matrix_repositories: set[str] = set()
    entry_statuses: list[str] = []
    for index, raw in enumerate(matrix):
        loc = f"$.requirement_matrix[{index}]"
        entry = obj(raw, loc)
        requirement_ids.append(requirement_id(field(entry, "requirement_id", loc), f"{loc}.requirement_id"))
        matrix_repositories.update(
            string_array(
                field(entry, "repository_ids", loc),
                f"{loc}.repository_ids",
                item_validator=repo_id,
                nonempty=True,
                sorted_values=True,
            )
        )
        string_array(
            field(entry, "validation_evidence", loc),
            f"{loc}.validation_evidence",
            item_validator=lambda value, item_loc: absolute_path(
                value, item_loc, must_exist=True, file_only=True
            ),
            nonempty=True,
            sorted_values=True,
        )
        entry_statuses.append(
            enum(field(entry, "status", loc), {"pass", "fail", "blocked"}, f"{loc}.status")
        )
    if requirement_ids != sorted(requirement_ids) or len(requirement_ids) != len(set(requirement_ids)):
        fail("$.requirement_matrix", "requirement IDs must be unique and sorted")

    interfaces = array(field(data, "interfaces", "$"), "$.interfaces")
    for index, raw in enumerate(interfaces):
        loc = f"$.interfaces[{index}]"
        interface = obj(raw, loc)
        string(field(interface, "interface_id", loc), f"{loc}.interface_id")
        entry_statuses.append(
            enum(field(interface, "status", loc), {"pass", "fail", "blocked"}, f"{loc}.status")
        )
        string_array(
            field(interface, "evidence_paths", loc),
            f"{loc}.evidence_paths",
            item_validator=lambda value, item_loc: absolute_path(value, item_loc, must_exist=True),
            nonempty=True,
            sorted_values=True,
        )

    conformance = array(field(data, "mechanism_conformance", "$"), "$.mechanism_conformance")
    if not conformance:
        fail("$.mechanism_conformance", "must not be empty")
    conformance_repos: list[str] = []
    for index, raw in enumerate(conformance):
        loc = f"$.mechanism_conformance[{index}]"
        entry = obj(raw, loc)
        current_repo = repo_id(field(entry, "repo_id", loc), f"{loc}.repo_id")
        conformance_repos.append(current_repo)
        plan_path = absolute_path(
            field(entry, "plan_path", loc),
            f"{loc}.plan_path",
            must_exist=True,
            file_only=True,
        )
        challenge_path_value = field(entry, "design_challenge_path", loc)
        challenge_path: str | None = None
        if challenge_path_value is not None:
            challenge_path = absolute_path(
                challenge_path_value,
                f"{loc}.design_challenge_path",
                must_exist=True,
                file_only=True,
            )
        plan = load_json_object(plan_path, f"{loc}.plan_path")
        if plan.get("artifact_kind") != "plan" or plan.get("repo_id") != current_repo:
            fail(f"{loc}.plan_path", "must reference a plan for this repository")
        challenge_required = boolean(
            plan.get("design_challenge_required", True),
            f"{loc}.plan_path.design_challenge_required",
        )
        if challenge_required and challenge_path is None:
            fail(f"{loc}.design_challenge_path", "is required by the canonical plan")
        if not challenge_required and challenge_path is not None:
            fail(f"{loc}.design_challenge_path", "must be null when the plan waives the critic")
        if challenge_path is not None:
            challenge = load_json_object(challenge_path, f"{loc}.design_challenge_path")
            if (
                challenge.get("artifact_kind") != "design-challenge"
                or challenge.get("repo_id") != current_repo
            ):
                fail(
                    f"{loc}.design_challenge_path",
                    "must reference a design challenge for this repository",
                )
            if challenge.get("verdict") != "accept":
                fail(f"{loc}.design_challenge_path", "challenge verdict must be accept")
            referenced_plan = obj(
                field(challenge, "plan", f"{loc}.design_challenge_path"),
                f"{loc}.design_challenge_path.plan",
            )
            actual_plan_hash = hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()
            if referenced_plan.get("sha256") != actual_plan_hash:
                fail(f"{loc}.design_challenge_path", "challenge must reference the recorded plan")
        entry_statuses.append(
            enum(field(entry, "status", loc), {"pass", "fail", "blocked"}, f"{loc}.status")
        )
        string_array(
            field(entry, "evidence_paths", loc),
            f"{loc}.evidence_paths",
            item_validator=lambda value, item_loc: absolute_path(
                value, item_loc, must_exist=True, file_only=True
            ),
            nonempty=True,
            sorted_values=True,
        )
    if conformance_repos != sorted(conformance_repos) or len(conformance_repos) != len(
        set(conformance_repos)
    ):
        fail("$.mechanism_conformance", "repository IDs must be unique and sorted")
    if set(conformance_repos) != matrix_repositories:
        fail(
            "$.mechanism_conformance",
            "must cover exactly the requirement-matrix repositories: "
            f"{sorted(matrix_repositories)}",
        )

    changed_files = obj(field(data, "changed_files_by_repo", "$"), "$.changed_files_by_repo")
    if list(changed_files) != sorted(changed_files):
        fail("$.changed_files_by_repo", "keys must be sorted lexicographically")
    for key, paths in changed_files.items():
        repo_id(key, f"$.changed_files_by_repo.{key}")
        string_array(
            paths,
            f"$.changed_files_by_repo.{key}",
            item_validator=relative_repo_path,
            sorted_values=True,
        )
    string_array(field(data, "rollout", "$"), "$.rollout", unique=True)
    string_array(field(data, "risks", "$"), "$.risks", unique=True)
    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)
    if status == "complete" and any(value != "pass" for value in entry_statuses):
        fail("$", "complete integration artifacts may contain only passing entries")


def validate_delivery(data: dict[str, Any]) -> None:
    validate_common(data, "delivery")
    repo_id(field(data, "repo_id", "$"), "$.repo_id")
    integer(field(data, "attempt", "$"), "$.attempt", minimum=1)
    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), ARTIFACT_STATUSES, "$.status")
    string(field(data, "branch", "$"), "$.branch")
    string(field(data, "base_branch", "$"), "$.base_branch")
    commits = string_array(field(data, "commits", "$"), "$.commits", item_validator=sha, unique=True)
    pr_url = field(data, "pr_url", "$")
    if pr_url is not None:
        parsed_url = string(pr_url, "$.pr_url")
        if not parsed_url.startswith(("https://", "http://")):
            fail("$.pr_url", "must be an HTTP(S) URL")
    checks = array(field(data, "checks", "$"), "$.checks")
    required_states: list[str] = []
    for index, raw in enumerate(checks):
        loc = f"$.checks[{index}]"
        check = obj(raw, loc)
        string(field(check, "name", loc), f"{loc}.name")
        url = string(field(check, "url", loc), f"{loc}.url")
        if not url.startswith(("https://", "http://")):
            fail(f"{loc}.url", "must be an HTTP(S) URL")
        required = boolean(field(check, "required", loc), f"{loc}.required")
        state = enum(
            field(check, "state", loc),
            {"passed", "failed", "cancelled", "skipped", "pending"},
            f"{loc}.state",
        )
        if required:
            required_states.append(state)
        absolute_path(
            field(check, "evidence_path", loc),
            f"{loc}.evidence_path",
            must_exist=True,
            file_only=True,
        )
    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)
    if status == "complete":
        if not commits:
            fail("$.commits", "must not be empty for complete delivery")
        if pr_url is None:
            fail("$.pr_url", "is required for complete delivery")
        if any(state != "passed" for state in required_states):
            fail("$.checks", "all required checks must pass for complete delivery")
    assignment = load_json_object(data["assignment_path"], "$.assignment_path")
    if assignment.get("delivery_evidence_version", 1) == 2:
        policy = obj(field(data, "check_policy", "$"), "$.check_policy")
        policy_status = enum(field(policy, "status", "$.check_policy"), {"required", "not-configured", "unknown"}, "$.check_policy.status")
        required_checks = array(field(policy, "required_checks", "$.check_policy"), "$.check_policy.required_checks")
        evidence = array(field(policy, "evidence", "$.check_policy"), "$.check_policy.evidence")
        for index, reference in enumerate(evidence):
            hashed_file_reference(reference, f"$.check_policy.evidence[{index}]")
        if data.get("command_evidence") is not None:
            hashed_file_reference(data["command_evidence"], "$.command_evidence")
        for key in ("head_sha", "pushed_head_sha", "checked_head_sha"):
            value = field(data, key, "$")
            if value is not None:
                sha(value, f"$.{key}")
        if status == "complete":
            head = sha(data["head_sha"], "$.head_sha")
            if head != data["pushed_head_sha"] or head != data["checked_head_sha"] or head != commits[-1]:
                fail("$.checked_head_sha", "local, pushed, checked, and delivered head must match")
            if policy_status == "unknown" or not evidence:
                fail("$.check_policy", "complete delivery requires positive check-policy evidence")
            if (policy_status == "required") != bool(required_checks):
                fail("$.check_policy", "required-check policy contradicts its identities")
            for required_check in required_checks:
                name = string(field(required_check, "name", "$.check_policy.required_checks"), "$.check_policy.required_checks.name")
                app_id = required_check.get("app_id")
                if app_id is not None:
                    integer(app_id, "$.check_policy.required_checks.app_id", minimum=1)
                matches = [check for check in checks if check["name"] == name and check["required"]
                           and (app_id is None or check.get("app_id") == app_id)]
                if not matches or any(check["state"] != "passed" for check in matches):
                    fail("$.checks", f"required check {name!r} is absent or not passing on this head")


def validate_report(data: dict[str, Any]) -> None:
    validate_common(data, "report")
    timestamp(field(data, "created_at", "$"), "$.created_at")
    status = enum(field(data, "status", "$"), {"complete", "blocked"}, "$.status")
    html_path_value = absolute_path(
        field(data, "html_path", "$"),
        "$.html_path",
        must_exist=status == "complete",
        file_only=True,
    )
    recorded_size = integer(field(data, "html_size_bytes", "$"), "$.html_size_bytes", minimum=0)
    recorded_hash = sha256(field(data, "html_sha256", "$"), "$.html_sha256")
    string_array(
        field(data, "requirement_ids", "$"),
        "$.requirement_ids",
        item_validator=requirement_id,
        nonempty=status == "complete",
        sorted_values=True,
    )
    string_array(field(data, "high_impact_topics", "$"), "$.high_impact_topics", unique=True)
    blockers = validate_blockers(field(data, "blockers", "$"))
    validate_status_blockers(status, blockers)
    if status == "complete":
        html_path = Path(html_path_value)
        actual_size = html_path.stat().st_size
        if actual_size == 0:
            fail("$.html_path", "HTML report must not be empty")
        if actual_size != recorded_size:
            fail("$.html_size_bytes", f"expected {actual_size} from the HTML file")
        digest = hashlib.sha256(html_path.read_bytes()).hexdigest()
        if digest != recorded_hash:
            fail("$.html_sha256", f"expected {digest} from the HTML file")
        prefix = html_path.read_text(encoding="utf-8", errors="replace")[:1024].lower()
        if "<html" not in prefix and "<!doctype html" not in prefix:
            fail("$.html_path", "file does not appear to be HTML")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def artifact_skeleton(assignment_path: Path, assignment: dict[str, Any]) -> dict[str, Any]:
    """Build a stage-specific worker skeleton from one validated assignment."""
    assignment_hash = hashlib.sha256(assignment_path.read_bytes()).hexdigest()
    kind = assignment["output_kind"]
    common: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": kind,
        "run_id": assignment["run_id"],
        "assignment_path": str(assignment_path.resolve()),
        "assignment_sha256": assignment_hash,
    }
    if assignment.get("execution_mode") == "artifact-repair":
        source = load_json_object(assignment["repair_of"]["artifact"]["path"], "$.repair_of.artifact")
        source.update(common)
        return source
    created_at = _utc_now()
    repo = assignment.get("repo_id")
    baseline = assignment.get("baseline")

    def input_by_kind(input_kind: str) -> tuple[str, dict[str, Any]] | None:
        for reference in assignment["input_artifacts"]:
            path = Path(reference["path"])
            if path.suffix != ".json":
                continue
            candidate = load_json_object(str(path), f"$.input_artifacts[{path}]")
            if candidate.get("artifact_kind") == input_kind:
                return str(path), candidate
        return None

    if kind == "contract":
        common.update(
            {
                "revision": assignment.get("contract_revision", assignment["attempt"]),
                "created_at": created_at,
                "status": "complete",
                "requirement_map": {},
                "domain_terms": [],
                "behavior_rules": [],
                "interfaces": [],
                "dependencies": [],
                "compatibility": [],
                "rollout": [],
                "cross_repository_validation": [],
                "risks": [],
                "open_questions": [],
                "blockers": [],
            }
        )
    elif kind == "plan":
        contract_input = input_by_kind("contract")
        requirements_input = input_by_kind("requirements")
        prior_plan_input = input_by_kind("plan")
        prior_challenge_input = input_by_kind("design-challenge")
        revision_match = re.search(r"plan-v([0-9]+)", Path(assignment["output_artifact"]).name)
        plan_revision = assignment.get(
            "plan_revision",
            int(revision_match.group(1)) if revision_match else assignment["attempt"],
        )
        assigned_revision_basis = assignment.get("revision_basis")
        common.update(
            {
                "repo_id": repo,
                "revision": plan_revision,
                "supersedes_plan": (
                    {
                        "path": prior_plan_input[0],
                        "sha256": hashlib.sha256(
                            Path(prior_plan_input[0]).read_bytes()
                        ).hexdigest(),
                    }
                    if plan_revision > 1 and prior_plan_input
                    else None
                ),
                "design_challenge": (
                    {
                        "path": prior_challenge_input[0],
                        "sha256": hashlib.sha256(
                            Path(prior_challenge_input[0]).read_bytes()
                        ).hexdigest(),
                    }
                    if plan_revision > 1
                    and prior_challenge_input
                    and not assigned_revision_basis
                    else None
                ),
                "revision_basis": assigned_revision_basis,
                "created_at": created_at,
                "status": "complete",
                "baseline": baseline,
                "contract_sha256": (
                    hashlib.sha256(Path(contract_input[0]).read_bytes()).hexdigest()
                    if contract_input
                    else None
                ),
                "requirements_sha256": (
                    hashlib.sha256(Path(requirements_input[0]).read_bytes()).hexdigest()
                    if requirements_input
                    else None
                ),
                "risk_flags": [],
                "design_challenge_required": False,
                "tasks": [],
                "work_packets": [],
                "validations": [],
                "complexity_mechanisms": [],
                "finding_resolutions": [],
                "non_goals": [],
                "risks": [],
                "blockers": [],
            }
        )
    elif kind == "design-challenge":
        plan_input = input_by_kind("plan")
        plan_path = Path(plan_input[0]) if plan_input else None
        plan = plan_input[1] if plan_input else {}
        common.update(
            {
                "repo_id": repo,
                "attempt": assignment["attempt"],
                "created_at": created_at,
                "status": "complete",
                "baseline": baseline,
                "contract_sha256": plan.get("contract_sha256"),
                "plan": {
                    "path": str(plan_path) if plan_path else None,
                    "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest()
                    if plan_path
                    else None,
                },
                "mode": "verification" if plan.get("revision", 1) > 1 else "full",
                "verdict": "accept",
                "summary": "TODO",
                "mechanism_assessments": [],
                "findings": [],
                "blockers": [],
            }
        )
    elif kind == "result":
        common.update(
            {
                "repo_id": repo,
                "stage": assignment["stage"],
                "attempt": assignment["attempt"],
                "created_at": created_at,
                "status": "complete",
                "summary": "TODO",
                "requirement_ids": assignment.get("requirement_ids", []),
                "task_ids": assignment.get("task_ids", []),
                "packet_id": assignment.get("packet_id"),
                "changed_files": [],
                "tree_fingerprint": None,
                "validations": [],
                "decisions": [],
                "resolutions": [],
                "git": {"head": baseline, "status_short_path": None},
                "blockers": [],
                "next_action": None,
            }
        )
    elif kind == "review":
        round_number = 1 if assignment["stage"] == "review-1" else 2
        common.update(
            {
                "repo_id": repo,
                "round": round_number,
                "mode": "full" if round_number == 1 else "verification",
                "verified_finding_ids": assignment.get("finding_ids", []),
                "created_at": created_at,
                "status": "complete",
                "baseline": baseline,
                "reviewed_status_path": None,
                "findings": [],
                "blockers": [],
            }
        )
    elif kind == "integration":
        common.update(
            {
                "created_at": created_at,
                "status": "complete",
                "requirement_matrix": [],
                "interfaces": [],
                "mechanism_conformance": [],
                "changed_files_by_repo": {},
                "rollout": [],
                "risks": [],
                "blockers": [],
            }
        )
    elif kind == "delivery":
        common.update(
            {
                "repo_id": repo,
                "attempt": assignment["attempt"],
                "created_at": created_at,
                "status": "complete",
                "branch": "TODO",
                "base_branch": "TODO",
                "commits": [],
                "pr_url": None,
                "checks": [],
                "blockers": [],
            }
        )
        if assignment.get("delivery_evidence_version", 1) == 2:
            common.update(head_sha=None, pushed_head_sha=None, checked_head_sha=None,
                          check_policy={"status": "unknown", "required_checks": [], "evidence": []})
    elif kind == "report":
        common.update(
            {
                "created_at": created_at,
                "status": "complete",
                "html_path": "TODO",
                "html_size_bytes": 0,
                "html_sha256": "0" * 64,
                "requirement_ids": assignment.get("requirement_ids", []),
                "high_impact_topics": [],
                "blockers": [],
            }
        )
    else:  # pragma: no cover - guarded by assignment validation
        fail("$.output_kind", f"cannot initialize unsupported kind {kind}")
    return common


def oversized_next_action(data: dict[str, Any]) -> bool:
    value = data.get("next_action")
    return isinstance(value, str) and len(value) > 300


def repairable_rejection(code: str | None, path: str | None) -> bool:
    """Recognize narrow repair candidates; the entire payload still needs validation."""
    return bool(
        (code == "missing-field" and re.fullmatch(r"\$\.blockers\[[0-9]+\]\.kind", path or ""))
        or (code == "invalid-evidence" and path == "$.next_action")
    )


def repairable_result(data: dict[str, Any], output_path: Path) -> list[int]:
    """Validate intact evidence with only missing kinds or oversized advisory text.

    Temporary values are used only for schema checking, never written or accepted.
    Outcomes and evidence must already be valid without either metadata field.
    """
    if data.get("artifact_kind") != "result":
        fail("$.artifact_kind", "only intact results are eligible for artifact repair")
    missing = [
        index for index, blocker in enumerate(array(field(data, "blockers", "$"), "$.blockers"))
        if isinstance(blocker, dict) and "kind" not in blocker
    ]
    oversized = oversized_next_action(data)
    if not missing and not oversized:
        fail("$", "no missing blocker classification or oversized next_action to repair")
    candidate = copy.deepcopy(data)
    for index in missing:
        candidate["blockers"][index]["kind"] = "decision"
    if oversized:
        candidate["next_action"] = None
    global CURRENT_ARTIFACT_PATH
    previous = CURRENT_ARTIFACT_PATH
    CURRENT_ARTIFACT_PATH = output_path
    try:
        validate_result(candidate)
    finally:
        CURRENT_ARTIFACT_PATH = previous
    return missing


def validate_repair_assignment(data: dict[str, Any]) -> None:
    repair = obj(field(data, "repair_of", "$"), "$.repair_of")
    original_path = hashed_file_reference(field(repair, "assignment", "$.repair_of"), "$.repair_of.assignment")
    original = load_json_object(original_path, "$.repair_of.assignment")
    if original.get("execution_mode") == "artifact-repair":
        fail("$.repair_of", "recursive artifact repair is forbidden")
    validate_assignment(original)
    if original["output_kind"] != "result":
        fail("$.repair_of", "only result artifacts can be repaired")
    if data["action_id"] == original["action_id"]:
        fail("$.action_id", "repair requires a distinct action identity")
    for key in ("stage", "repo_id", "run_id", "attempt", "cwd", "baseline", "requirement_ids",
                "task_ids", "finding_ids", "validation_ids", "validation_commands", "packet_id", "input_artifacts"):
        if data.get(key) != original.get(key):
            fail(f"$.{key}", "repair must preserve the original assignment scope")
    if any(data[key] != "none" for key in ("project_file_access", "git_access", "forge_access")):
        fail("$.execution_mode", "artifact repair may not write project, Git, or forge state")
    if data["thinking"] != "medium" or data["timeout_seconds"] > 300:
        fail("$.execution_mode", "artifact repair requires medium reasoning and at most 300 seconds")
    if data["repositories"] != [{**repo, "access": "read"} for repo in original["repositories"]]:
        fail("$.repositories", "repair must preserve the original repository paths")
    if data["output_artifact"] == original["output_artifact"]:
        fail("$.output_artifact", "repair requires a new immutable output path")
    artifact_path = hashed_file_reference(field(repair, "artifact", "$.repair_of"), "$.repair_of.artifact")
    if Path(artifact_path).resolve() != Path(original["output_artifact"]).resolve():
        fail("$.repair_of.artifact", "must reference the original assignment output")
    for index, reference in enumerate(array(field(repair, "evidence", "$.repair_of"), "$.repair_of.evidence")):
        hashed_file_reference(reference, f"$.repair_of.evidence[{index}]")
    states = obj(field(repair, "repository_states", "$.repair_of"), "$.repair_of.repository_states")
    if set(states) != {repo["repo_id"] for repo in original["repositories"]}:
        fail("$.repair_of.repository_states", "must pin every originally accessible repository")
    for state in states.values():
        for key in ("fingerprint", "index_sha256"):
            sha256(field(state, key, "$.repair_of.repository_states"), f"$.repair_of.repository_states.{key}")
        sha(field(state, "head", "$.repair_of.repository_states"), "$.repair_of.repository_states.head")
        string(field(state, "branch", "$.repair_of.repository_states"), "$.repair_of.repository_states.branch")
    if data.get("input_tree_fingerprint") != states[data["repo_id"]]["fingerprint"]:
        fail("$.input_tree_fingerprint", "must match the pinned post-writer state")
    original_artifact = load_json_object(artifact_path, "$.repair_of.artifact")
    repairable_result(original_artifact, Path(artifact_path))


def validate_repaired_payload(assignment: dict[str, Any], data: dict[str, Any]) -> None:
    """A metadata repair cannot rewrite prior facts or manufacture a pass."""
    original = load_json_object(assignment["repair_of"]["artifact"]["path"], "$.repair_of.artifact")
    candidate = copy.deepcopy(data)
    if len(candidate.get("blockers", [])) != len(original["blockers"]):
        fail("$.repair_of", "artifact-only repair changed existing semantic evidence")
    for index, blocker in enumerate(original["blockers"]):
        if "kind" not in blocker:
            candidate["blockers"][index].pop("kind", None)
    # Handoff text is advisory, not routing or validation evidence. Only an
    # originally oversized value may change; the normal schema enforces its bound.
    if oversized_next_action(original):
        candidate["next_action"] = original["next_action"]
    # These fields are owned by the coordinator, not the semantic worker.
    for payload in (original, candidate):
        for key in ("assignment_path", "assignment_sha256", "git", "tree_fingerprint"):
            payload.pop(key, None)
        for validation in payload.get("validations", []):
            for key in ("command_sha256", "tree_fingerprint"):
                validation.pop(key, None)
    if candidate != original:
        fail("$.repair_of", "artifact-only repair changed existing semantic evidence")


def record_blocker(
    assignment_path: Path, *, kind: str, summary: str, evidence_path: Path,
    required_action: str, blocker_id: str | None = None,
) -> Path:
    """Construct a blocker only in a live assignment's unaccepted output."""
    assignment_path = assignment_path.resolve()
    assignment = load_json_object(str(assignment_path), "$.assignment")
    validate_assignment(assignment)
    if assignment.get("execution_mode") == "artifact-repair":
        fail("$.execution_mode", "repair may classify existing blockers only, not append new ones")
    run_dir = assignment_path.parent.parent
    run = load_json_object(str(run_dir / "run.json"), "$.run")
    output = Path(assignment["output_artifact"])
    if assignment_path.parent.name != "assignments" or not output.resolve().is_relative_to(run_dir):
        fail("$.output_artifact", "output must belong to this run")
    if run.get("run_id") != assignment["run_id"] or not any(
        action.get("assignment_path") == str(assignment_path)
        and action.get("output_artifact") == str(output)
        for action in run.get("next_actions", [])
    ):
        fail("$.output_artifact", "blocker output is not an active assignment")
    references = list(run.get("accepted_artifacts", {}).values())
    for repository in run.get("repositories", {}).values():
        references.extend(repository.get("accepted_artifacts", {}).values())
    if any(Path(ref["path"]).resolve() == output.resolve() for ref in references):
        fail("$.output_artifact", "refusing to change an accepted artifact")
    data = load_json_object(str(output), "$.output")
    if (data.get("assignment_path") != str(assignment_path)
            or data.get("assignment_sha256") != hashlib.sha256(assignment_path.read_bytes()).hexdigest()
            or data.get("artifact_kind") != assignment["output_kind"]):
        fail("$.output_artifact", "output identity does not match the assignment")
    blockers = array(field(data, "blockers", "$"), "$.blockers")
    identifier = blocker_id or f"BLOCK-{len(blockers) + 1:03d}"
    blockers.append({"id": identifier, "kind": kind, "summary": summary,
                     "evidence_path": str(evidence_path.resolve()), "required_action": required_action})
    validate_blockers(blockers)
    data["status"] = "blocked"
    serialized = json.dumps(data, indent=2) + "\n"
    if len(serialized.encode()) > MAX_BYTES[assignment["output_kind"]]:
        fail("$.output_artifact", "blocker output exceeds the artifact size limit")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(output)
    return output


def initialize_artifact(assignment_path: Path) -> Path:
    assignment = load_json_object(str(assignment_path), "$")
    validate_assignment(assignment)
    output_path = Path(assignment["output_artifact"])
    if output_path.exists():
        fail("$.output_artifact", f"refusing to overwrite existing file {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = artifact_skeleton(assignment_path.resolve(), assignment)
    output_path.write_text(json.dumps(skeleton, indent=2) + "\n", encoding="utf-8")
    return output_path


VALIDATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    "run": validate_run,
    "requirements": validate_requirements,
    "agents": validate_agents,
    "assignment": validate_assignment,
    "contract": validate_contract,
    "plan": validate_plan,
    "design-challenge": validate_design_challenge,
    "result": validate_result,
    "review": validate_review,
    "integration": validate_integration,
    "delivery": validate_delivery,
    "report": validate_report,
}


def usage() -> NoReturn:
    kinds = "|".join(VALIDATORS)
    print(
        "usage:\n"
        f"  artifact_guard.py <{kinds}> <artifact-path>\n"
        "  artifact_guard.py init <assignment-path>",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "block":
        parser = argparse.ArgumentParser(description="Record a typed blocker in an active assignment")
        parser.add_argument("assignment", type=Path)
        parser.add_argument("--kind", required=True, choices=sorted(BLOCKER_KINDS))
        parser.add_argument("--summary", required=True)
        parser.add_argument("--evidence-path", required=True, type=Path)
        parser.add_argument("--required-action", required=True)
        parser.add_argument("--id", dest="blocker_id")
        args = parser.parse_args(sys.argv[2:])
        try:
            output = record_blocker(args.assignment, kind=args.kind, summary=args.summary,
                                    evidence_path=args.evidence_path, required_action=args.required_action,
                                    blocker_id=args.blocker_id)
        except (OSError, ValidationError) as error:
            print(f"INVALID {args.assignment}: {error}", file=sys.stderr)
            return 1
        print(f"BLOCKED {output}")
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "init":
        assignment_path = Path(sys.argv[2])
        try:
            output = initialize_artifact(assignment_path)
        except (OSError, ValidationError) as error:
            print(f"INVALID {assignment_path}: {error}", file=sys.stderr)
            return 1
        print(f"INITIALIZED {output}")
        return 0
    if len(sys.argv) != 3 or sys.argv[1] not in VALIDATORS:
        usage()
    kind = sys.argv[1]
    path = Path(sys.argv[2])
    try:
        raw = path.read_bytes()
    except OSError as error:
        print(f"INVALID {path}: cannot read artifact: {error}", file=sys.stderr)
        return 1
    if len(raw) > MAX_BYTES[kind]:
        print(
            f"INVALID {path}: {len(raw)} bytes exceeds the {MAX_BYTES[kind]}-byte limit for {kind}",
            file=sys.stderr,
        )
        return 1
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"INVALID {path}: invalid UTF-8 JSON: {error}", file=sys.stderr)
        return 1
    global CURRENT_ARTIFACT_PATH
    CURRENT_ARTIFACT_PATH = path
    try:
        VALIDATORS[kind](obj(data, "$"))
    except ValidationError as error:
        print(f"INVALID {path}: {error}", file=sys.stderr)
        return 1
    print(f"VALID {kind} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
