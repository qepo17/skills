#!/usr/bin/env python3
"""Zero-configuration worker execution for the end-to-end workflow."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

DEFAULT_WORKER_MODEL = "gpt-6-astra"
DEFAULT_WORKER_THINKING = "xhigh"
THINKING_BY_CLASSIFICATION = {
    "medium": DEFAULT_WORKER_THINKING,
    "high": DEFAULT_WORKER_THINKING,
    "xhigh": DEFAULT_WORKER_THINKING,
    "max": DEFAULT_WORKER_THINKING,
}
WORKER_BACKENDS = {"direct", "herdr", "paseo", "tmux"}
WORKER_RUNTIMES = {"codex", "pi"}

RunProcess = Callable[[list[str], float | None], subprocess.CompletedProcess[bytes]]


def runtime_thinking(classification: str) -> str:
    try:
        return THINKING_BY_CLASSIFICATION[classification]
    except KeyError as exc:
        raise ValueError(f"unknown thinking classification: {classification}") from exc


@dataclass(frozen=True)
class ExecutionContext:
    backend: str
    runtime: str
    detected_from: str
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "backend": self.backend,
            "runtime": self.runtime,
            "detected_from": self.detected_from,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class WorkerRequest:
    action_id: str
    agent_name: str
    assignment_path: Path
    cwd: Path
    timeout_seconds: int
    runtime: str
    prompt: str
    thinking: str = DEFAULT_WORKER_THINKING


@dataclass(frozen=True)
class WorkerHandle:
    backend: str
    handle_id: str
    details: dict[str, Any]


@dataclass(frozen=True)
class WaitResult:
    settled: bool
    timed_out: bool = False
    reason: str | None = None


def run_process(
    command: list[str], timeout: float | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _json_output(process: subprocess.CompletedProcess[bytes]) -> Any:
    if process.returncode != 0:
        return None
    try:
        return json.loads(process.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _find_string(value: Any, keys: set[str]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for child in value.values():
            found = _find_string(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_string(child, keys)
            if found:
                return found
    return None


def _find_labeled_workspace(
    value: Any, label: str
) -> tuple[str, str | None] | None:
    if isinstance(value, dict):
        if value.get("label") == label or value.get("name") == label:
            workspace_id = next(
                (
                    value.get(key)
                    for key in ("workspace_id", "workspaceId", "id", "workspace")
                    if isinstance(value.get(key), str) and value.get(key)
                ),
                None,
            )
            if workspace_id:
                return workspace_id, _find_string(value, {"pane_id", "root_pane"})
        for child in value.values():
            found = _find_labeled_workspace(child, label)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_labeled_workspace(child, label)
            if found:
                return found
    return None


def _provider_runtime(value: Any) -> str | None:
    provider = _find_string(value, {"provider", "providerId", "provider_id"})
    if provider:
        prefix = provider.lower().split("/", 1)[0]
        if prefix in WORKER_RUNTIMES:
            return prefix
    return None


def _probe_json(
    command: list[str], runner: RunProcess
) -> tuple[bool, Any]:
    try:
        process = runner(command, 30)
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    value = _json_output(process)
    return process.returncode == 0, value


def detect_execution_context(
    *,
    environ: Mapping[str, str] | None = None,
    run_process: RunProcess = run_process,
    requested_runtime: str = "auto",
    requested_backend: str = "auto",
) -> ExecutionContext:
    """Select the active supervisor from positive environment and CLI probes."""
    env = dict(os.environ if environ is None else environ)
    if requested_runtime not in {"auto", *WORKER_RUNTIMES}:
        raise ValueError(f"unknown worker runtime: {requested_runtime}")
    if requested_backend not in {"auto", *WORKER_BACKENDS}:
        raise ValueError(f"unknown worker backend: {requested_backend}")

    runtime = requested_runtime
    if runtime == "auto":
        runtime = env.get("E2E_COORDINATOR_RUNTIME", "auto").strip().lower()
        if runtime not in {"auto", *WORKER_RUNTIMES}:
            raise ValueError(
                "E2E_COORDINATOR_RUNTIME must be one of: auto, codex, pi"
            )
    evidence: dict[str, Any] = {}

    paseo_agent_id = env.get("PASEO_AGENT_ID", "").strip()
    if requested_backend in {"auto", "paseo"} and paseo_agent_id:
        paseo = env.get("E2E_PASEO_BINARY", "paseo")
        ok, value = _probe_json(
            [paseo, "inspect", paseo_agent_id, "--json"], run_process
        )
        inspected_id = _find_string(value, {"agent_id", "agentId", "id"})
        inspected_status = _find_string(value, {"status"})
        if (
            ok
            and inspected_id == paseo_agent_id
            and inspected_status in {"running", "idle", "working", "blocked"}
        ):
            if runtime == "auto":
                runtime = _provider_runtime(value) or "pi"
            evidence = {"parent_agent_id": paseo_agent_id}
            return ExecutionContext("paseo", runtime, "PASEO_AGENT_ID", evidence)
        if requested_backend == "paseo":
            raise RuntimeError("Paseo parent agent is not reachable")

    if requested_backend in {"auto", "herdr"} and env.get("HERDR_ENV") == "1":
        herdr = env.get("E2E_HERDR_BINARY", "herdr")
        ok, value = _probe_json([herdr, "status", "server", "--json"], run_process)
        compatible = (
            isinstance(value, dict)
            and value.get("running") is True
            and value.get("compatible") is True
        )
        if ok and compatible:
            if runtime == "auto":
                runtime = "codex" if env.get("CODEX_THREAD_ID") else "pi"
            if isinstance(value, dict) and isinstance(value.get("protocol"), int):
                evidence["protocol"] = value["protocol"]
            return ExecutionContext("herdr", runtime, "HERDR_ENV", evidence)
        if requested_backend == "herdr":
            raise RuntimeError("Herdr server is not running or compatible")

    if requested_backend in {"auto", "tmux"} and env.get("TMUX"):
        tmux = env.get("E2E_TMUX_BINARY", "tmux")
        try:
            process = run_process(
                [tmux, "display-message", "-p", "#{session_id}"], 30
            )
        except (OSError, subprocess.TimeoutExpired):
            process = None
        session_id = (
            process.stdout.decode("utf-8", errors="replace").strip()
            if process is not None and process.returncode == 0
            else ""
        )
        if session_id:
            if runtime == "auto":
                runtime = "codex" if env.get("CODEX_THREAD_ID") else "pi"
            return ExecutionContext(
                "tmux", runtime, "TMUX", {"session_id": session_id}
            )
        if requested_backend == "tmux":
            raise RuntimeError("tmux session is not reachable")

    if requested_backend not in {"auto", "direct"}:
        raise RuntimeError(f"requested worker backend is unavailable: {requested_backend}")
    if runtime == "auto":
        runtime = "codex" if env.get("CODEX_THREAD_ID") else "pi"
    return ExecutionContext("direct", runtime, "fallback", {})


def _runtime_command(
    request: WorkerRequest, *, pi_binary: str, codex_binary: str
) -> list[str]:
    if request.runtime == "codex":
        return [
            codex_binary,
            "exec",
            "--ephemeral",
            "--model",
            DEFAULT_WORKER_MODEL,
            "--config",
            f'model_reasoning_effort="{request.thinking}"',
            "--cd",
            str(request.cwd),
            "--dangerously-bypass-approvals-and-sandbox",
            request.prompt,
        ]
    if request.runtime != "pi":
        raise ValueError(f"unknown worker runtime: {request.runtime}")
    return [
        pi_binary,
        "--print",
        "--no-session",
        "--model",
        f"openai-codex/{DEFAULT_WORKER_MODEL}",
        "--thinking",
        request.thinking,
        request.prompt,
    ]


class WorkerSupervisor:
    """Deep module that hides backend-specific worker lifecycle mechanics."""

    def __init__(
        self,
        run_dir: Path,
        context: ExecutionContext,
        *,
        pi_binary: str = "pi",
        codex_binary: str = "codex",
        herdr_binary: str = "herdr",
        tmux_binary: str = "tmux",
        paseo_binary: str = "paseo",
        run_process: RunProcess = run_process,
    ) -> None:
        self.run_dir = run_dir.resolve()
        self.context = context
        self.pi_binary = pi_binary
        self.codex_binary = codex_binary
        self.herdr_binary = herdr_binary
        self.tmux_binary = tmux_binary
        self.paseo_binary = paseo_binary
        self.run_process = run_process
        self._direct_processes: dict[str, subprocess.Popen[bytes]] = {}

    def _runtime_command(self, request: WorkerRequest) -> list[str]:
        return _runtime_command(
            request, pi_binary=self.pi_binary, codex_binary=self.codex_binary
        )

    def preview(self, request: WorkerRequest) -> dict[str, Any]:
        command = self._runtime_command(request)
        if self.context.backend == "direct":
            preview = command
        elif self.context.backend == "tmux":
            preview = [
                self.tmux_binary,
                "new-window",
                "-d",
                "-P",
                "-F",
                "#{window_id}",
                "-n",
                request.agent_name,
                "-c",
                str(request.cwd),
                shlex.join(command),
            ]
        elif self.context.backend == "paseo":
            preview = [
                self.paseo_binary,
                "run",
                "--background",
                "--json",
                "--title",
                request.agent_name,
                "--provider",
                request.runtime,
                "--model",
                (
                    DEFAULT_WORKER_MODEL
                    if request.runtime == "codex"
                    else f"openai-codex/{DEFAULT_WORKER_MODEL}"
                ),
                "--thinking",
                request.thinking,
                "--cwd",
                str(request.cwd),
                request.prompt,
            ]
        else:
            preview = [
                self.herdr_binary,
                "workspace",
                "create",
                "--cwd",
                str(request.cwd),
                "--label",
                request.agent_name,
                "--no-focus",
            ]
        return {"backend": self.context.backend, "command": preview}

    @staticmethod
    def record_name(action_id: str) -> str:
        digest = hashlib.sha256(action_id.encode()).hexdigest()[:16]
        return f"worker-{digest}.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _worker_paths(self, request: WorkerRequest) -> dict[str, Path]:
        digest = hashlib.sha256(request.action_id.encode()).hexdigest()[:16]
        root = self.run_dir / "supervisor"
        return {
            "record": root / self.record_name(request.action_id),
            "status": root / "status" / f"{digest}.json",
            "stdout": root / "logs" / f"{digest}.stdout.log",
            "stderr": root / "logs" / f"{digest}.stderr.log",
        }

    def _entrypoint_command(self, request: WorkerRequest) -> tuple[list[str], dict[str, Path]]:
        paths = self._worker_paths(request)
        command = [
            sys.executable,
            str(Path(__file__).with_name("worker_entrypoint.py")),
            "--record",
            str(paths["record"]),
            "--status",
            str(paths["status"]),
            "--stdout",
            str(paths["stdout"]),
            "--stderr",
            str(paths["stderr"]),
            "--cwd",
            str(request.cwd),
            "--",
            *self._runtime_command(request),
        ]
        return command, paths

    def _starting_record(self, request: WorkerRequest, paths: dict[str, Path]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "action_id": request.action_id,
            "agent_name": request.agent_name,
            "backend": self.context.backend,
            "runtime": request.runtime,
            "handle_id": None,
            "started_at": self._now(),
            "ended_at": None,
            "status": "starting",
            "cleanup_status": "pending",
            "status_path": str(paths["status"]),
            "stdout_path": str(paths["stdout"]),
            "stderr_path": str(paths["stderr"]),
            "details": {},
        }

    def _start_direct(
        self, request: WorkerRequest, record: dict[str, Any]
    ) -> WorkerHandle:
        command, _paths = self._entrypoint_command(request)
        process = subprocess.Popen(
            command,
            cwd=request.cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        handle_id = str(process.pid)
        self._direct_processes[handle_id] = process
        return WorkerHandle("direct", handle_id, {"pid": process.pid})

    @staticmethod
    def _error_text(process: subprocess.CompletedProcess[bytes]) -> str:
        return process.stderr.decode("utf-8", errors="replace").strip()

    def _checked_json(self, command: list[str], timeout: float = 30) -> Any:
        process = self.run_process(command, timeout)
        if process.returncode != 0:
            raise RuntimeError(
                self._error_text(process)
                or f"{' '.join(command[:3])} exited {process.returncode}"
            )
        return _json_output(process)

    def _interactive_runtime_args(self, request: WorkerRequest) -> list[str]:
        if request.runtime == "codex":
            return [
                "--model",
                DEFAULT_WORKER_MODEL,
                "--config",
                f'model_reasoning_effort="{request.thinking}"',
                "--dangerously-bypass-approvals-and-sandbox",
            ]
        return [
            "--model",
            f"openai-codex/{DEFAULT_WORKER_MODEL}",
            "--thinking",
            request.thinking,
        ]

    def _start_herdr(
        self, request: WorkerRequest, record: dict[str, Any]
    ) -> WorkerHandle:
        workspace_value = self._checked_json(
            [
                self.herdr_binary,
                "workspace",
                "create",
                "--cwd",
                str(request.cwd),
                "--label",
                request.agent_name,
                "--no-focus",
            ]
        )
        workspace_id = _find_string(workspace_value, {"workspace_id", "workspace"})
        pane_id = _find_string(workspace_value, {"pane_id", "root_pane"})
        if pane_id is None:
            raise RuntimeError("Herdr workspace creation did not report a root pane")
        provisional = self._persist_handle(
            record,
            WorkerHandle(
                "herdr",
                request.agent_name,
                {"workspace_id": workspace_id, "pane_id": pane_id},
            ),
        )
        start_command = [
            self.herdr_binary,
            "agent",
            "start",
            request.agent_name,
            "--kind",
            request.runtime,
            "--pane",
            pane_id,
            "--",
            *self._interactive_runtime_args(request),
        ]
        self._checked_json(start_command)
        self._checked_json(
            [
                self.herdr_binary,
                "agent",
                "prompt",
                request.agent_name,
                request.prompt,
            ]
        )
        return provisional

    def _start_tmux(
        self, request: WorkerRequest, record: dict[str, Any]
    ) -> WorkerHandle:
        entrypoint, _paths = self._entrypoint_command(request)
        process = self.run_process(
            [
                self.tmux_binary,
                "new-window",
                "-d",
                "-P",
                "-F",
                "#{window_id}",
                "-n",
                request.agent_name,
                "-c",
                str(request.cwd),
                shlex.join(entrypoint),
            ],
            30,
        )
        if process.returncode != 0:
            raise RuntimeError(
                self._error_text(process)
                or f"tmux new-window exited {process.returncode}"
            )
        window_id = process.stdout.decode("utf-8", errors="replace").strip()
        if not window_id:
            raise RuntimeError("tmux did not report a window ID")
        return WorkerHandle("tmux", window_id, {"window_id": window_id})

    def _start_paseo(
        self, request: WorkerRequest, record: dict[str, Any]
    ) -> WorkerHandle:
        command = [
            self.paseo_binary,
            "run",
            "--background",
            "--json",
            "--title",
            request.agent_name,
            "--provider",
            request.runtime,
            "--model",
            (
                DEFAULT_WORKER_MODEL
                if request.runtime == "codex"
                else f"openai-codex/{DEFAULT_WORKER_MODEL}"
            ),
            "--thinking",
            request.thinking,
            "--cwd",
            str(request.cwd),
            "--label",
            f"e2e.action_id={request.action_id}",
        ]
        if request.runtime == "codex":
            command.extend(["--mode", "bypass"])
        command.append(request.prompt)
        value = self._checked_json(command)
        agent_id = _find_string(value, {"agent_id", "agentId", "id"})
        if agent_id is None:
            raise RuntimeError("Paseo did not report an agent ID")
        return WorkerHandle("paseo", agent_id, {"agent_id": agent_id})

    def _wait_status_file(
        self, record: dict[str, Any], timeout_seconds: float
    ) -> WaitResult:
        status_path = Path(record["status_path"])
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() <= deadline:
            if status_path.is_file():
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.05)
                    continue
                error = status.get("error")
                return WaitResult(True, reason=str(error) if error else None)
            time.sleep(0.05)
        return WaitResult(False, timed_out=True, reason="worker timed out")

    def _persist_handle(
        self, record: dict[str, Any], handle: WorkerHandle
    ) -> WorkerHandle:
        record.update(
            {
                "handle_id": handle.handle_id,
                "status": "working",
                "details": handle.details,
            }
        )
        self._atomic_write(Path(record["record_path"]), record)
        return handle

    def _start(self, request: WorkerRequest, record: dict[str, Any]) -> WorkerHandle:
        launchers = {
            "direct": self._start_direct,
            "herdr": self._start_herdr,
            "paseo": self._start_paseo,
            "tmux": self._start_tmux,
        }
        handle = launchers[self.context.backend](request, record)
        return self._persist_handle(record, handle)

    def _wait(
        self, request: WorkerRequest, handle: WorkerHandle, record: dict[str, Any]
    ) -> WaitResult:
        if handle.backend in {"direct", "tmux"}:
            result = self._wait_status_file(record, request.timeout_seconds)
            if handle.backend == "direct" and result.settled:
                process = self._direct_processes.pop(handle.handle_id, None)
                if process is not None:
                    process.wait(timeout=5)
            return result
        if handle.backend == "herdr":
            # A plain settled-state wait can match the agent's initial idle
            # state before the submitted prompt begins. Observe the transition
            # to working first; quick tasks may already be settled when this
            # short transition probe returns, so the authoritative artifact is
            # still validated by the caller after the settled wait.
            try:
                self.run_process(
                    [
                        self.herdr_binary,
                        "agent",
                        "wait",
                        handle.handle_id,
                        "--until",
                        "working",
                        "--timeout",
                        "5000",
                    ],
                    10,
                )
                process = self.run_process(
                    [
                        self.herdr_binary,
                        "agent",
                        "wait",
                        handle.handle_id,
                        "--timeout",
                        str(int(request.timeout_seconds * 1000)),
                    ],
                    request.timeout_seconds + 30,
                )
            except subprocess.TimeoutExpired:
                return WaitResult(False, timed_out=True, reason="Herdr worker timed out")
            if process.returncode != 0:
                return WaitResult(
                    False,
                    timed_out=True,
                    reason=self._error_text(process) or "Herdr worker did not settle",
                )
            return WaitResult(True)
        if handle.backend == "paseo":
            try:
                process = self.run_process(
                    [
                        self.paseo_binary,
                        "wait",
                        handle.handle_id,
                        "--timeout",
                        str(int(request.timeout_seconds)),
                        "--json",
                    ],
                    request.timeout_seconds + 30,
                )
            except subprocess.TimeoutExpired:
                return WaitResult(False, timed_out=True, reason="Paseo worker timed out")
            if process.returncode != 0:
                return WaitResult(
                    False,
                    timed_out=True,
                    reason=self._error_text(process) or "Paseo worker did not settle",
                )
            return WaitResult(True)
        raise RuntimeError(f"unknown worker backend: {handle.backend}")

    def _cleanup(self, handle: WorkerHandle, settled: bool) -> tuple[str, str | None]:
        if not settled:
            return "retained", None
        if handle.backend == "direct":
            return "complete", None
        if handle.backend == "tmux":
            command = [self.tmux_binary, "kill-window", "-t", handle.handle_id]
        elif handle.backend == "herdr":
            workspace_id = handle.details.get("workspace_id")
            if workspace_id:
                command = [self.herdr_binary, "workspace", "close", workspace_id]
            else:
                pane_id = handle.details.get("pane_id")
                if not pane_id:
                    return "failed", "Herdr did not report a pane or workspace ID"
                command = [self.herdr_binary, "pane", "close", pane_id]
        elif handle.backend == "paseo":
            command = [self.paseo_binary, "archive", handle.handle_id, "--json"]
        else:
            raise RuntimeError(f"unknown worker backend: {handle.backend}")
        process = self.run_process(command, 30)
        if process.returncode == 0:
            return "complete", None
        if handle.backend == "tmux":
            # A detached window normally disappears when its headless command
            # exits. Missing after a durable exit-status record is equivalent
            # to a successful kill-window cleanup.
            probe = self.run_process(
                [
                    self.tmux_binary,
                    "display-message",
                    "-p",
                    "-t",
                    handle.handle_id,
                    "#{window_id}",
                ],
                30,
            )
            if probe.returncode != 0:
                return "complete", None
        return "failed", self._error_text(process) or (
            f"{handle.backend} cleanup exited {process.returncode}"
        )

    def _run_one(
        self,
        request: WorkerRequest,
        handle: WorkerHandle,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            wait = self._wait(request, handle, record)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            wait = WaitResult(False, reason=str(error))
        if wait.settled:
            try:
                cleanup_status, cleanup_error = self._cleanup(handle, True)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                cleanup_status, cleanup_error = "failed", str(error)
        else:
            cleanup_status, cleanup_error = (
                ("retained", None) if wait.timed_out else ("failed", wait.reason)
            )
        ended_at = self._now()
        record.update(
            {
                "ended_at": ended_at,
                "status": "settled" if wait.settled else "timeout" if wait.timed_out else "failed",
                "cleanup_status": cleanup_status,
                "cleanup_error": cleanup_error,
            }
        )
        self._atomic_write(Path(record["record_path"]), record)
        return {
            "action_id": request.action_id,
            "agent_name": request.agent_name,
            "assignment_path": str(request.assignment_path),
            "started_at": record["started_at"],
            "ended_at": ended_at,
            "backend": handle.backend,
            "handle_id": handle.handle_id,
            "settled": wait.settled,
            "timed_out": wait.timed_out,
            "reason": wait.reason,
            "cleanup_status": cleanup_status,
            "cleanup_error": cleanup_error,
            "stdout_path": record["stdout_path"],
            "stderr_path": record["stderr_path"],
        }

    def retry_cleanups(self) -> list[dict[str, Any]]:
        """Retry transient cleanup failures for already-settled workers."""
        outcomes: list[dict[str, Any]] = []
        supervisor_dir = self.run_dir / "supervisor"
        for record_path in sorted(supervisor_dir.glob("worker-*.json")):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            late_settled = False
            if (
                record.get("status") == "timeout"
                and record.get("cleanup_status") == "retained"
            ):
                try:
                    status = json.loads(
                        Path(record["status_path"]).read_text(encoding="utf-8")
                    )
                except (KeyError, OSError, json.JSONDecodeError):
                    status = {}
                late_settled = bool(status.get("finished_at")) and isinstance(
                    status.get("exit_code"), int
                )
            if (
                record.get("backend") != self.context.backend
                or (
                    record.get("status") not in {"settled", "failed"}
                    and not late_settled
                )
                or (
                    record.get("cleanup_status") not in {"pending", "failed"}
                    and not late_settled
                )
                or not isinstance(record.get("handle_id"), str)
            ):
                continue
            handle = WorkerHandle(
                record["backend"],
                record["handle_id"],
                dict(record.get("details", {})),
            )
            try:
                cleanup_status, cleanup_error = self._cleanup(handle, True)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                cleanup_status, cleanup_error = "failed", str(error)
            if late_settled:
                record["status"] = "settled"
            record["cleanup_status"] = cleanup_status
            record["cleanup_error"] = cleanup_error
            self._atomic_write(record_path, record)
            outcomes.append(
                {
                    "action_id": record.get("action_id"),
                    "agent_name": record.get("agent_name"),
                    "backend": record["backend"],
                    "handle_id": record["handle_id"],
                    "cleanup_status": cleanup_status,
                    "cleanup_error": cleanup_error,
                }
            )
        return outcomes

    def recover_legacy_herdr(self, request: WorkerRequest) -> dict[str, Any] | None:
        """Adopt a schema-v1 Herdr agent that predates generic handle records."""
        if self.context.backend != "herdr":
            return None
        try:
            state = self.run_process(
                [self.herdr_binary, "agent", "get", request.agent_name], 30
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if state.returncode != 0:
            return None
        value = _json_output(state)
        pane_id = _find_string(value, {"pane_id"})
        handle = WorkerHandle(
            "herdr", request.agent_name, {"workspace_id": None, "pane_id": pane_id}
        )
        record = self._starting_record(request, self._worker_paths(request))
        record.update(
            {
                "record_path": str(
                    self.run_dir / "supervisor" / self.record_name(request.action_id)
                ),
                "handle_id": request.agent_name,
                "status": "working",
                "details": handle.details,
            }
        )
        return self._run_one(request, handle, record)

    def _adopt_unrecorded(
        self, request: WorkerRequest, record: dict[str, Any]
    ) -> WorkerHandle | None:
        backend = self.context.backend
        if backend == "direct":
            deadline = time.monotonic() + 5
            record_path = Path(record["record_path"])
            while time.monotonic() <= deadline:
                try:
                    current = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    current = {}
                handle_id = current.get("handle_id")
                if isinstance(handle_id, str):
                    record.update(current)
                    return WorkerHandle("direct", handle_id, dict(current.get("details", {})))
                if Path(record["status_path"]).is_file():
                    return WorkerHandle("direct", "completed-without-pid", {})
                time.sleep(0.05)
            return None
        if backend == "herdr":
            try:
                workspaces = self._checked_json(
                    [self.herdr_binary, "workspace", "list"]
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                workspaces = None
            workspace = _find_labeled_workspace(workspaces, request.agent_name)
            if workspace:
                workspace_id, pane_id = workspace
                return WorkerHandle(
                    "herdr",
                    request.agent_name,
                    {"workspace_id": workspace_id, "pane_id": pane_id},
                )
            try:
                value = self._checked_json(
                    [self.herdr_binary, "agent", "get", request.agent_name]
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                return None
            pane_id = _find_string(value, {"pane_id"})
            if pane_id:
                return WorkerHandle(
                    "herdr",
                    request.agent_name,
                    {"workspace_id": None, "pane_id": pane_id},
                )
            return None
        if backend == "tmux":
            try:
                process = self.run_process(
                    [
                        self.tmux_binary,
                        "list-windows",
                        "-a",
                        "-F",
                        "#{window_id}\t#{window_name}",
                    ],
                    30,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            if process.returncode == 0:
                for line in process.stdout.decode(
                    "utf-8", errors="replace"
                ).splitlines():
                    window_id, separator, name = line.partition("\t")
                    if separator and name == request.agent_name and window_id:
                        return WorkerHandle(
                            "tmux", window_id, {"window_id": window_id}
                        )
            if Path(record["status_path"]).is_file():
                return WorkerHandle("tmux", "already-closed", {})
            return None
        if backend == "paseo":
            try:
                value = self._checked_json(
                    [
                        self.paseo_binary,
                        "ls",
                        "-a",
                        "-g",
                        "--label",
                        f"e2e.action_id={request.action_id}",
                        "--json",
                    ]
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                return None
            agent_id = _find_string(value, {"agent_id", "agentId", "id"})
            if agent_id:
                return WorkerHandle("paseo", agent_id, {"agent_id": agent_id})
        return None

    def recover(self, request: WorkerRequest) -> dict[str, Any] | None:
        """Adopt a durably recorded worker after coordinator restart."""
        record_path = self.run_dir / "supervisor" / self.record_name(request.action_id)
        if not record_path.is_file():
            return None
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["record_path"] = str(record_path)
        backend = str(record.get("backend") or "")
        handle_id = record.get("handle_id")
        if backend != self.context.backend:
            return None
        if not isinstance(handle_id, str):
            adopted = self._adopt_unrecorded(request, record)
            if adopted is None:
                return None
            self._persist_handle(record, adopted)
            handle_id = adopted.handle_id
        if record.get("cleanup_status") == "complete":
            return {
                "action_id": request.action_id,
                "agent_name": request.agent_name,
                "assignment_path": str(request.assignment_path),
                "started_at": record["started_at"],
                "ended_at": record.get("ended_at") or self._now(),
                "backend": backend,
                "handle_id": handle_id,
                "settled": True,
                "timed_out": False,
                "reason": None,
                "cleanup_status": "complete",
                "cleanup_error": record.get("cleanup_error"),
                "stdout_path": record["stdout_path"],
                "stderr_path": record["stderr_path"],
            }
        handle = WorkerHandle(backend, handle_id, dict(record.get("details", {})))
        return self._run_one(request, handle, record)

    def run_batch(self, requests: list[WorkerRequest]) -> list[dict[str, Any]]:
        if not requests:
            return []
        launched: list[tuple[WorkerRequest, WorkerHandle, dict[str, Any]]] = []
        outcomes: list[dict[str, Any]] = []
        for request in requests:
            paths = self._worker_paths(request)
            record = self._starting_record(request, paths)
            record["record_path"] = str(paths["record"])
            self._atomic_write(paths["record"], record)
            try:
                handle = self._start(request, record)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                ended_at = self._now()
                cleanup_status = "failed"
                cleanup_error: str | None = str(error)
                recorded_handle = record.get("handle_id")
                if isinstance(recorded_handle, str):
                    try:
                        cleanup_status, cleanup_error = self._cleanup(
                            WorkerHandle(
                                self.context.backend,
                                recorded_handle,
                                dict(record.get("details", {})),
                            ),
                            True,
                        )
                    except (
                        OSError,
                        RuntimeError,
                        subprocess.TimeoutExpired,
                    ) as cleanup:
                        cleanup_error = str(cleanup)
                record.update(
                    {
                        "ended_at": ended_at,
                        "status": "failed",
                        "cleanup_status": cleanup_status,
                        "cleanup_error": cleanup_error,
                    }
                )
                self._atomic_write(paths["record"], record)
                outcomes.append(
                    {
                        "action_id": request.action_id,
                        "agent_name": request.agent_name,
                        "assignment_path": str(request.assignment_path),
                        "started_at": record["started_at"],
                        "ended_at": ended_at,
                        "backend": self.context.backend,
                        "handle_id": recorded_handle or "unavailable",
                        "settled": False,
                        "timed_out": False,
                        "reason": str(error),
                        "cleanup_status": cleanup_status,
                        "cleanup_error": cleanup_error,
                        "stdout_path": record["stdout_path"],
                        "stderr_path": record["stderr_path"],
                    }
                )
                continue
            launched.append((request, handle, record))

        if launched:
            with ThreadPoolExecutor(max_workers=len(launched)) as executor:
                futures = {
                    executor.submit(self._run_one, request, handle, record): request
                    for request, handle, record in launched
                }
                for future in as_completed(futures):
                    outcomes.append(future.result())
        return sorted(outcomes, key=lambda item: item["action_id"])
