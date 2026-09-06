#!/usr/bin/env python3
"""CLI for the LangGraph end-to-end development control plane."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
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
    if run.get("validation_policy_version") == 1:
        result.update(engine.status_details())
        result["pr_urls"] = sorted({item["pr_url"] for item in result["deliveries"] if item["pr_url"]})
        if run['status'] == 'complete':
            gates = result['local_gates'].values()
            result['summary'] = ('Recorded completion; current local evidence is stale.' if not all(g['satisfied'] for g in gates)
                else 'Completed with local validation warnings/exclusions.' if any(g['warnings'] for g in gates)
                else 'Completed; mandatory local and delivery obligations verified.')
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
    if run.get('validation_policy_version') == 1:
        current = engine._current_report()
        result['report_paths'] = [current[1]['html_path']] if current else []
        result['historical_report_paths'] = sorted(path for path in reports if path and path not in result['report_paths'])
    return result


def _invoke(args: argparse.Namespace, graph_input: Any) -> dict[str, Any]:
    if args.command == "amend":
        # Refuse historical runs before even creating a lock/checkpoint file.
        run = WorkflowEngine(args.run_dir).load_run()
        if run.get("validation_policy_version") != 1:
            raise WorkflowError("amendments are unavailable for legacy runs")
        request = json.loads(args.input.read_text(encoding="utf-8"))
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        for reference in run.get("run_amendments", []):
            if json.loads(Path(reference["path"]).read_text())["request_sha256"] == digest:
                return {"run_id": run["run_id"], "status": run["status"],
                        "amendment": {"status": "already-applied", "path": reference["path"]}}
        if run["status"] == "complete" or (run.get("plan_review") or {}).get("status") != "approved":
            raise WorkflowError("new amendments require an active run with an approved bundle")
    with _execution_lock(args.run_dir.resolve()):
        return _invoke_locked(args, graph_input)


def _invoke_locked(args: argparse.Namespace, graph_input: Any) -> dict[str, Any]:
    with _open_graph(
        args.run_dir.resolve(),
        worker_runtime=args.worker_runtime,
        report_root=args.report_root,
    ) as (engine, graph, config):
        if args.command == "resume":
            if not engine.resume_delivery_checks():
                engine.resume_external_blockers()
        elif args.command == "amend":
            if graph.get_state(config).next:
                raise WorkflowError("amendment requires a settled graph cursor")
            engine.apply_amendment(json.loads(args.input.read_text(encoding="utf-8")))
        elif args.command == "retry-validation-evidence":
            if not engine.retry_validation_evidence():
                raise WorkflowError(
                    "run is not blocked by the exact validation-coverage evidence condition"
                )
        elif args.command == "retry-corrected-handoff":
            if not engine.retry_corrected_handoff(args.original_artifact):
                raise WorkflowError("run is not eligible for corrected next_action recovery")
        elif args.command == "replan-decision":
            if graph.get_state(config).next:
                raise WorkflowError("decision replanning requires a settled graph cursor")
            if not engine.replan_decision(
                review_sha256=args.review_sha256, blocker_id=args.blocker_id,
                blocker_evidence_sha256=args.blocker_evidence_sha256, text=args.text, context=args.context,
            ):
                raise WorkflowError("run is not eligible for implementation-decision replanning")
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

    amend = subparsers.add_parser("amend", help="record a scoped, authorized new-run validation/check decision")
    amend.add_argument("run_dir", type=Path)
    amend.add_argument("--input", type=Path, required=True)
    amend.add_argument("--worker-runtime", choices=["auto", "codex", "pi"], default="auto")
    amend.add_argument("--report-root", type=Path)

    validation_retry = subparsers.add_parser(
        "retry-validation-evidence",
        help="retry an exact validation-coverage blocker after fixing the engine",
    )
    validation_retry.add_argument("run_dir", type=Path)
    validation_retry.add_argument(
        "--worker-runtime", choices=["auto", "codex", "pi"], default="auto"
    )
    validation_retry.add_argument("--report-root", type=Path)

    handoff_retry = subparsers.add_parser(
        "retry-corrected-handoff",
        help="accept an explicitly corrected next_action without replaying source work",
    )
    handoff_retry.add_argument("run_dir", type=Path)
    handoff_retry.add_argument("--original-artifact", type=Path, required=True)
    handoff_retry.add_argument("--worker-runtime", choices=["auto", "codex", "pi"], default="auto")
    handoff_retry.add_argument("--report-root", type=Path)

    replan = subparsers.add_parser(
        "replan-decision", help="return an accepted implementation decision to bounded planning"
    )
    replan.add_argument("run_dir", type=Path)
    replan.add_argument("--review-sha256", required=True)
    replan.add_argument("--blocker-id", required=True)
    replan.add_argument("--blocker-evidence-sha256", required=True)
    replan.add_argument("--text", required=True)
    replan.add_argument("--context", default="")
    replan.add_argument("--worker-runtime", choices=["auto", "codex", "pi"], default="auto")
    replan.add_argument("--report-root", type=Path)

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
        elif args.command == "retry-validation-evidence":
            output = _invoke(
                args,
                {
                    "run_dir": str(args.run_dir.resolve()),
                    "last_transition": "retry-validation-evidence",
                },
            )
        elif args.command in {"retry-corrected-handoff", "replan-decision", "amend"}:
            output = _invoke(
                args,
                {"run_dir": str(args.run_dir.resolve()), "last_transition": args.command},
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
