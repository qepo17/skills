#!/usr/bin/env python3
"""CLI for the LangGraph end-to-end development control plane."""

from __future__ import annotations

import argparse
import fcntl
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

sys.dont_write_bytecode = True

import artifact_guard  # noqa: E402
from workflow_engine import WorkflowEngine, WorkflowError, build_graph  # noqa: E402


def _json_default(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


@contextmanager
def _execution_lock(run_dir: Path) -> Iterator[None]:
    path = run_dir / ".orchestrator-execution.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _open_graph(
    run_dir: Path,
    *,
    worker_runtime: str,
    report_root: Path | None,
) -> Iterator[tuple[WorkflowEngine, Any, dict[str, Any]]]:
    engine = WorkflowEngine(
        run_dir,
        worker_runtime=worker_runtime,
        report_root=report_root,
    )
    run = engine.load_run()
    connection = sqlite3.connect(
        run_dir / "langgraph.sqlite",
        check_same_thread=False,
    )
    try:
        checkpointer = SqliteSaver(connection)
        graph = build_graph(engine, checkpointer)
        config = {
            "configurable": {"thread_id": run["run_id"]},
            "recursion_limit": 250,
        }
        yield engine, graph, config
    finally:
        connection.close()


def _result(engine: WorkflowEngine, graph_output: Any | None = None) -> dict[str, Any]:
    run = engine.load_run()
    result: dict[str, Any] = {
        "run_id": run["run_id"],
        "run_dir": str(engine.run_dir),
        "status": run["status"],
        "phase": run["phase"],
        "next_actions": [action["action_id"] for action in run["next_actions"]],
        "blockers": run["blockers"],
        "worker_execution": run.get("worker_execution"),
    }
    if isinstance(graph_output, dict) and graph_output.get("outcome"):
        result["outcome"] = graph_output["outcome"]
    if isinstance(graph_output, dict) and graph_output.get("__interrupt__"):
        interrupts = []
        for item in graph_output["__interrupt__"]:
            value = getattr(item, "value", item)
            interrupts.append(value)
        result["interrupts"] = interrupts
    if run.get("plan_review"):
        result["plan_review"] = {
            "status": run["plan_review"]["status"],
            "path": run["plan_review"]["review_path"],
            "sha256": run["plan_review"]["review_sha256"],
        }
    deliveries = []
    for repository in run["repositories"].values():
        for reference in repository.get("accepted_artifacts", {}).values():
            path = Path(reference["path"])
            if not path.exists() or path.suffix != ".json":
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                value.get("artifact_kind") == "delivery"
                and value.get("status") == "complete"
            ):
                deliveries.append(value.get("pr_url"))
    result["pr_urls"] = sorted(url for url in deliveries if url)
    reports = []
    for reference in run.get("accepted_artifacts", {}).values():
        path = Path(reference["path"])
        if not path.exists() or path.suffix != ".json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("artifact_kind") == "report" and value.get("status") == "complete":
            reports.append(value.get("html_path"))
    result["report_paths"] = sorted(path for path in reports if path)
    return result


def _invoke(args: argparse.Namespace, graph_input: Any) -> dict[str, Any]:
    with _execution_lock(args.run_dir.resolve()):
        return _invoke_locked(args, graph_input)


def _invoke_locked(args: argparse.Namespace, graph_input: Any) -> dict[str, Any]:
    with _open_graph(
        args.run_dir.resolve(),
        worker_runtime=args.worker_runtime,
        report_root=args.report_root,
    ) as (engine, graph, config):
        if args.command == "resume":
            engine.resume_external_blockers()
        elif args.command == "retry-validation-evidence":
            if not engine.retry_validation_evidence():
                raise WorkflowError(
                    "run is not blocked by the exact validation-coverage evidence condition"
                )
        elif args.command == "retry-dependent-fixes":
            if not engine.retry_dependent_fixes():
                raise WorkflowError(
                    "run is not blocked by the exact cross-repository fix dependency condition"
                )
        attempt_baseline = len(engine.load_agents()["agents"])
        snapshot = graph.get_state(config)
        if isinstance(graph_input, Command):
            # Approval remains recoverable even if the SQLite cursor was lost:
            # reconcile facts, then rebuild the interrupt from the pending projection.
            engine.reconcile()
            engine.plan_review_payload()
            if "plan_review" not in snapshot.next:
                graph.invoke(
                    {
                        "run_dir": str(engine.run_dir),
                        "last_transition": "rebuild-plan-interrupt",
                        "attempt_baseline": attempt_baseline,
                    },
                    config=config,
                )
                snapshot = graph.get_state(config)
            if "plan_review" not in snapshot.next:
                raise WorkflowError(
                    "could not reconstruct the pending plan-review interrupt"
                )
            updates = dict(graph_input.update or {})
            updates["attempt_baseline"] = attempt_baseline
            graph_input = Command(
                graph=graph_input.graph,
                update=updates,
                resume=graph_input.resume,
                goto=graph_input.goto,
            )
            output = graph.invoke(graph_input, config=config)
        elif snapshot.next:
            # LangGraph resumes the pending node directly, so reconcile external
            # side effects explicitly before allowing that node to replay.
            engine.reconcile()
            graph.update_state(config, {"attempt_baseline": attempt_baseline})
            output = graph.invoke(None, config=config)
        else:
            graph_input = {**graph_input, "attempt_baseline": attempt_baseline}
            output = graph.invoke(graph_input, config=config)
        while (
            isinstance(output, dict)
            and output.get("outcome") == "budget-checkpoint"
            and engine.load_run()["workflow_policy"]["auto_resume"]
        ):
            attempt_baseline = len(engine.load_agents()["agents"])
            output = graph.invoke(
                {
                    "run_dir": str(engine.run_dir),
                    "last_transition": "auto-resume-budget-checkpoint",
                    "attempt_baseline": attempt_baseline,
                },
                config=config,
            )
        return _result(engine, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser(
        "init", help="initialize a run from a reviewed bootstrap spec"
    )
    initialize.add_argument("--spec", type=Path, required=True)
    initialize.add_argument("--run-dir", type=Path, required=True)

    for name in ("run", "resume", "status", "diagram"):
        command = subparsers.add_parser(name)
        command.add_argument("run_dir", type=Path)
        if name in {"run", "resume"}:
            command.add_argument(
                "--worker-runtime",
                choices=["auto", "codex", "pi"],
                default="auto",
            )
            command.add_argument("--report-root", type=Path)

    handoff_repair = subparsers.add_parser(
        "repair-handoff-metadata",
        help="repair only a hash-pinned oversized next_action on completed implementation",
    )
    handoff_repair.add_argument("run_dir", type=Path)
    handoff_repair.add_argument("--artifact-sha256", required=True)

    validation_retry = subparsers.add_parser(
        "retry-validation-evidence",
        help="retry an exact validation-coverage blocker after fixing the engine",
    )
    validation_retry.add_argument("run_dir", type=Path)
    validation_retry.add_argument(
        "--worker-runtime", choices=["auto", "codex", "pi"], default="auto"
    )
    validation_retry.add_argument("--report-root", type=Path)

    dependent_fix_retry = subparsers.add_parser(
        "retry-dependent-fixes",
        help="retry fixes after an accepted upstream contract fix",
    )
    dependent_fix_retry.add_argument("run_dir", type=Path)
    dependent_fix_retry.add_argument(
        "--worker-runtime", choices=["auto", "codex", "pi"], default="auto"
    )
    dependent_fix_retry.add_argument("--report-root", type=Path)

    approve = subparsers.add_parser(
        "approve", help="resume an exact pending plan bundle"
    )
    approve.add_argument("run_dir", type=Path)
    approve.add_argument("--review-sha256", required=True)
    approve.add_argument("--text", required=True)
    approve.add_argument(
        "--worker-runtime", choices=["auto", "codex", "pi"], default="auto"
    )
    approve.add_argument("--report-root", type=Path)

    changes = subparsers.add_parser(
        "request-changes", help="return a pending bundle to planning"
    )
    changes.add_argument("run_dir", type=Path)
    changes.add_argument("--review-sha256", required=True)
    changes.add_argument("--text", required=True)
    changes.add_argument("--repository", action="append", default=[])
    changes.add_argument(
        "--worker-runtime", choices=["auto", "codex", "pi"], default="auto"
    )
    changes.add_argument("--report-root", type=Path)

    database = subparsers.add_parser(
        "database-target",
        help="record non-secret evidence for an isolated migration-capable target",
    )
    database.add_argument("run_dir", type=Path)
    database.add_argument("--repository", required=True)
    database.add_argument(
        "--classification",
        required=True,
        choices=["isolated-local", "isolated-test"],
    )
    database.add_argument("--description", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            engine = WorkflowEngine.initialize(
                spec_path=args.spec.resolve(),
                run_dir=args.run_dir.resolve(),
            )
            output = _result(engine)
        elif args.command == "run":
            output = _invoke(
                args,
                {"run_dir": str(args.run_dir.resolve()), "last_transition": "run"},
            )
        elif args.command == "resume":
            output = _invoke(
                args,
                {"run_dir": str(args.run_dir.resolve()), "last_transition": "resume"},
            )
        elif args.command == "repair-handoff-metadata":
            with _execution_lock(args.run_dir.resolve()):
                engine = WorkflowEngine(args.run_dir.resolve())
                receipt = engine.repair_handoff_metadata(args.artifact_sha256)
                output = {**_result(engine), "handoff_recovery": receipt}
        elif args.command == "retry-validation-evidence":
            output = _invoke(
                args,
                {
                    "run_dir": str(args.run_dir.resolve()),
                    "last_transition": "retry-validation-evidence",
                },
            )
        elif args.command == "retry-dependent-fixes":
            output = _invoke(
                args,
                {
                    "run_dir": str(args.run_dir.resolve()),
                    "last_transition": "retry-dependent-fixes",
                },
            )
        elif args.command == "approve":
            output = _invoke(
                args,
                Command(
                    resume={
                        "decision": "approve",
                        "review_sha256": args.review_sha256,
                        "text": args.text,
                    }
                ),
            )
        elif args.command == "request-changes":
            decision: dict[str, Any] = {
                "decision": "changes",
                "review_sha256": args.review_sha256,
                "text": args.text,
            }
            if args.repository:
                decision["repository_ids"] = args.repository
            output = _invoke(args, Command(resume=decision))
        elif args.command == "database-target":
            with _execution_lock(args.run_dir.resolve()):
                engine = WorkflowEngine(args.run_dir.resolve())
                path = engine.record_database_target(
                    repo_id=args.repository,
                    classification=args.classification,
                    description=args.description,
                )
                output = {**_result(engine), "database_target_evidence": str(path)}
        elif args.command == "status":
            engine = WorkflowEngine(args.run_dir.resolve())
            output = _result(engine)
        elif args.command == "diagram":
            args.worker_runtime = "auto"
            args.report_root = None
            with _open_graph(
                args.run_dir.resolve(), worker_runtime="auto", report_root=None
            ) as (_engine, graph, _config):
                output = {"mermaid": graph.get_graph().draw_mermaid()}
        else:  # pragma: no cover
            return 2
    except (
        OSError,
        ValueError,
        WorkflowError,
        artifact_guard.ValidationError,
        json.JSONDecodeError,
    ) as error:
        print(
            json.dumps({"status": "error", "error": str(error)}, indent=2),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(output, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
