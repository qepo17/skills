from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import worker_supervisor  # noqa: E402


class FakeCommandRunner:
    def __init__(self, responses: dict[str, tuple[int, object]]) -> None:
        self.responses = responses
        self.commands: list[list[str]] = []

    def __call__(
        self, command: list[str], timeout: float | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        self.commands.append(command)
        key = " ".join(command)
        for prefix, (returncode, output) in self.responses.items():
            if key.startswith(prefix):
                stdout = output if isinstance(output, str) else json.dumps(output)
                return subprocess.CompletedProcess(command, returncode, stdout.encode(), b"")
        return subprocess.CompletedProcess(command, 1, b"", b"unavailable")


class FlakyHerdrCleanupRunner:
    def __init__(self) -> None:
        self.cleanup_attempts = 0

    def __call__(
        self, command: list[str], timeout: float | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        if command[1:3] == ["workspace", "create"]:
            value: object = {
                "result": {
                    "workspace": "workspace-flaky",
                    "root_pane": {"pane_id": "pane-flaky"},
                }
            }
        elif command[1:3] == ["workspace", "close"]:
            self.cleanup_attempts += 1
            if self.cleanup_attempts == 1:
                raise OSError("temporary cleanup failure")
            value = {"result": {"closed": True}}
        else:
            value = {"result": {"ok": True}}
        return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")


class FakeTmuxRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.processes: list[subprocess.Popen[bytes]] = []

    def __call__(
        self, command: list[str], timeout: float | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        self.commands.append(command)
        if "new-window" in command:
            self.processes.append(
                subprocess.Popen(
                    command[-1],
                    shell=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            return subprocess.CompletedProcess(command, 0, b"@42\n", b"")
        if "kill-window" in command:
            for process in self.processes:
                process.wait(timeout=5)
            return subprocess.CompletedProcess(command, 0, b"", b"")
        return subprocess.CompletedProcess(command, 1, b"", b"unexpected")


class ExecutionContextDetectionTests(unittest.TestCase):
    def test_paseo_parent_agent_is_preferred_and_its_runtime_is_inherited(self) -> None:
        runner = FakeCommandRunner(
            {
                "paseo inspect parent-123 --json": (
                    0,
                    {
                        "id": "parent-123",
                        "provider": "codex/gpt-6-astra",
                        "status": "running",
                    },
                )
            }
        )

        context = worker_supervisor.detect_execution_context(
            environ={
                "PASEO_AGENT_ID": "parent-123",
                "HERDR_ENV": "1",
                "TMUX": "/tmp/tmux,1,0",
            },
            run_process=runner,
        )

        self.assertEqual("paseo", context.backend)
        self.assertEqual("codex", context.runtime)
        self.assertEqual("PASEO_AGENT_ID", context.detected_from)

    def test_stale_paseo_marker_falls_through_to_an_active_herdr_server(self) -> None:
        runner = FakeCommandRunner(
            {
                "paseo inspect stale --json": (
                    0,
                    {"id": "stale", "provider": "pi/model", "status": "archived"},
                ),
                "herdr status server --json": (
                    0,
                    {"running": True, "compatible": True, "protocol": 20},
                ),
            }
        )

        context = worker_supervisor.detect_execution_context(
            environ={
                "PASEO_AGENT_ID": "stale",
                "HERDR_ENV": "1",
                "TMUX": "/tmp/tmux,1,0",
            },
            run_process=runner,
        )

        self.assertEqual("herdr", context.backend)
        self.assertEqual("HERDR_ENV", context.detected_from)

    def test_malformed_herdr_and_empty_tmux_evidence_fall_back_to_direct(self) -> None:
        runner = FakeCommandRunner(
            {
                "herdr status server --json": (0, "not-json"),
                "tmux display-message -p #{session_id}": (0, ""),
            }
        )

        context = worker_supervisor.detect_execution_context(
            environ={"HERDR_ENV": "1", "TMUX": "/tmp/tmux,1,0"},
            run_process=runner,
        )

        self.assertEqual("direct", context.backend)

    def test_active_tmux_is_selected_only_when_its_session_probe_succeeds(self) -> None:
        runner = FakeCommandRunner(
            {"tmux display-message -p #{session_id}": (0, "$1")}
        )

        context = worker_supervisor.detect_execution_context(
            environ={"TMUX": "/tmp/tmux,1,0"},
            run_process=runner,
        )

        self.assertEqual("tmux", context.backend)
        self.assertEqual("TMUX", context.detected_from)

    def test_runtime_override_is_honored_without_backend_configuration(self) -> None:
        context = worker_supervisor.detect_execution_context(
            environ={"E2E_COORDINATOR_RUNTIME": "codex"},
            run_process=FakeCommandRunner({}),
        )

        self.assertEqual("direct", context.backend)
        self.assertEqual("codex", context.runtime)

    def test_paseo_host_without_a_parent_agent_does_not_select_remote_execution(self) -> None:
        context = worker_supervisor.detect_execution_context(
            environ={"PASEO_HOST": "remote.example:6767"},
            run_process=FakeCommandRunner({}),
        )

        self.assertEqual("direct", context.backend)
        self.assertEqual("fallback", context.detected_from)
        self.assertEqual("pi", context.runtime)


class WorkerCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def request(
        self, runtime: str = "pi", thinking: str = "xhigh"
    ) -> worker_supervisor.WorkerRequest:
        assignment = self.run_dir / "assignment.json"
        assignment.write_text("{}\n", encoding="utf-8")
        return worker_supervisor.WorkerRequest(
            action_id="validate:api:one",
            agent_name="test-worker",
            assignment_path=assignment,
            cwd=self.root,
            timeout_seconds=60,
            runtime=runtime,
            prompt="Execute the immutable assignment.",
            thinking=thinking,
        )

    def test_direct_preview_uses_a_noninteractive_ephemeral_runtime(self) -> None:
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("direct", "pi", "fallback", {}),
            pi_binary="pi-custom",
        )

        preview = supervisor.preview(self.request())

        self.assertEqual("direct", preview["backend"])
        self.assertEqual("pi-custom", preview["command"][0])
        self.assertIn("--print", preview["command"])
        self.assertIn("--no-session", preview["command"])

    def test_preview_uses_astra_with_default_xhigh_reasoning(self) -> None:
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("direct", "pi", "fallback", {}),
            pi_binary="pi-custom",
        )

        preview = supervisor.preview(self.request())

        model_index = preview["command"].index("--model") + 1
        self.assertEqual("openai-codex/gpt-6-astra", preview["command"][model_index])
        thinking_index = preview["command"].index("--thinking") + 1
        self.assertEqual("xhigh", preview["command"][thinking_index])
        for classification in ("medium", "high", "xhigh", "max"):
            self.assertEqual(
                "xhigh", worker_supervisor.runtime_thinking(classification)
            )

    def test_tmux_preview_creates_a_detached_window_without_focus(self) -> None:
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("tmux", "pi", "TMUX", {}),
            tmux_binary="tmux-custom",
        )

        preview = supervisor.preview(self.request())

        self.assertEqual("tmux", preview["backend"])
        self.assertEqual("tmux-custom", preview["command"][0])
        self.assertIn("new-window", preview["command"])
        self.assertIn("-d", preview["command"])

    def test_tmux_batch_runs_headlessly_and_closes_its_window(self) -> None:
        fake_pi = self.root / "fake-pi-tmux.py"
        fake_pi.write_text(
            "#!/usr/bin/env python3\n"
            "print('tmux worker complete')\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        runner = FakeTmuxRunner()
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("tmux", "pi", "TMUX", {}),
            pi_binary=str(fake_pi),
            run_process=runner,
        )

        outcome = supervisor.run_batch([self.request()])[0]

        self.assertTrue(outcome["settled"])
        self.assertEqual("@42", outcome["handle_id"])
        self.assertEqual("complete", outcome["cleanup_status"])
        self.assertTrue(any("new-window" in command for command in runner.commands))
        self.assertIn(
            ["tmux", "kill-window", "-t", "@42"],
            runner.commands,
        )

    def test_direct_batch_runs_headlessly_and_persists_a_generic_handle(self) -> None:
        fake_pi = self.root / "fake-pi.py"
        fake_pi.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "print('worker complete')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("direct", "pi", "fallback", {}),
            pi_binary=str(fake_pi),
        )

        outcomes = supervisor.run_batch([self.request()])

        self.assertEqual(1, len(outcomes))
        outcome = outcomes[0]
        self.assertEqual("direct", outcome["backend"])
        self.assertTrue(outcome["settled"])
        self.assertFalse(outcome["timed_out"])
        self.assertEqual("complete", outcome["cleanup_status"])
        self.assertTrue(outcome["handle_id"].isdigit())
        record = self.run_dir / "supervisor" / supervisor.record_name(
            "validate:api:one"
        )
        persisted = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual("direct", persisted["backend"])
        self.assertEqual(outcome["handle_id"], persisted["handle_id"])
        self.assertEqual("complete", persisted["cleanup_status"])
        self.assertTrue(Path(outcome["stdout_path"]).is_file())
        self.assertTrue(Path(outcome["stderr_path"]).is_file())

    def test_recovery_adopts_a_persisted_direct_handle_without_relaunching(self) -> None:
        request = self.request()
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("direct", "pi", "fallback", {}),
        )
        status_path = self.run_dir / "supervisor" / "status" / "recovered.json"
        status_path.parent.mkdir(parents=True)
        status_path.write_text(
            json.dumps({"exit_code": 0, "finished_at": "2026-08-26T10:00:00Z"}),
            encoding="utf-8",
        )
        record_path = self.run_dir / "supervisor" / supervisor.record_name(
            request.action_id
        )
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "action_id": request.action_id,
                    "agent_name": request.agent_name,
                    "backend": "direct",
                    "handle_id": "4242",
                    "started_at": "2026-08-26T09:59:00Z",
                    "ended_at": None,
                    "status": "working",
                    "cleanup_status": "pending",
                    "status_path": str(status_path),
                    "stdout_path": str(self.run_dir / "stdout.log"),
                    "stderr_path": str(self.run_dir / "stderr.log"),
                    "details": {"pid": 4242},
                    "record_path": str(record_path),
                }
            ),
            encoding="utf-8",
        )

        outcome = supervisor.recover(request)

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertTrue(outcome["settled"])
        self.assertEqual("4242", outcome["handle_id"])
        self.assertEqual("complete", outcome["cleanup_status"])
        persisted = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual("complete", persisted["cleanup_status"])

    def test_recovery_adopts_a_herdr_workspace_when_crash_preceded_handle_write(self) -> None:
        request = self.request()
        runner = FakeCommandRunner(
            {
                "herdr-custom workspace list": (
                    0,
                    {
                        "result": {
                            "workspaces": [
                                {
                                    "workspace_id": "workspace-adopted",
                                    "label": "test-worker",
                                    "root_pane": {"pane_id": "pane-adopted"},
                                }
                            ]
                        }
                    },
                ),
                "herdr-custom agent wait test-worker": (
                    0,
                    {"result": {"status": "idle"}},
                ),
                "herdr-custom workspace close workspace-adopted": (
                    0,
                    {"result": {"closed": True}},
                ),
            }
        )
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("herdr", "pi", "HERDR_ENV", {}),
            herdr_binary="herdr-custom",
            run_process=runner,
        )
        record_path = self.run_dir / "supervisor" / supervisor.record_name(
            request.action_id
        )
        record_path.parent.mkdir(parents=True)
        record_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "action_id": request.action_id,
                    "agent_name": request.agent_name,
                    "backend": "herdr",
                    "runtime": "pi",
                    "handle_id": None,
                    "started_at": "2026-08-26T09:59:00Z",
                    "ended_at": None,
                    "status": "starting",
                    "cleanup_status": "pending",
                    "status_path": str(self.run_dir / "status.json"),
                    "stdout_path": str(self.run_dir / "stdout.log"),
                    "stderr_path": str(self.run_dir / "stderr.log"),
                    "details": {},
                    "record_path": str(record_path),
                }
            ),
            encoding="utf-8",
        )

        outcome = supervisor.recover(request)

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual("test-worker", outcome["handle_id"])
        self.assertEqual("complete", outcome["cleanup_status"])
        persisted = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual("pane-adopted", persisted["details"]["pane_id"])
        self.assertEqual(
            "workspace-adopted", persisted["details"]["workspace_id"]
        )

    def test_cleanup_exception_remains_settled_and_is_retried(self) -> None:
        runner = FlakyHerdrCleanupRunner()
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("herdr", "pi", "HERDR_ENV", {}),
            herdr_binary="herdr-custom",
            run_process=runner,
        )

        outcome = supervisor.run_batch([self.request()])[0]

        self.assertTrue(outcome["settled"])
        self.assertEqual("failed", outcome["cleanup_status"])
        record_path = self.run_dir / "supervisor" / supervisor.record_name(
            "validate:api:one"
        )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual("settled", record["status"])
        retried = supervisor.retry_cleanups()
        self.assertEqual("complete", retried[0]["cleanup_status"])

    def test_retry_cleanup_reaps_a_timed_out_worker_after_status_appears(self) -> None:
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("direct", "pi", "fallback", {}),
        )
        status_path = self.run_dir / "supervisor" / "status" / "late.json"
        status_path.parent.mkdir(parents=True)
        status_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "finished_at": "2026-08-26T10:05:00Z",
                    "exit_code": 0,
                    "error": None,
                }
            ),
            encoding="utf-8",
        )
        record_path = self.run_dir / "supervisor" / supervisor.record_name(
            "deliver:api:late"
        )
        record_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "action_id": "deliver:api:late",
                    "agent_name": "late-worker",
                    "backend": "direct",
                    "runtime": "pi",
                    "handle_id": "4242",
                    "started_at": "2026-08-26T09:59:00Z",
                    "ended_at": "2026-08-26T10:00:00Z",
                    "status": "timeout",
                    "cleanup_status": "retained",
                    "cleanup_error": None,
                    "status_path": str(status_path),
                    "stdout_path": str(self.run_dir / "stdout.log"),
                    "stderr_path": str(self.run_dir / "stderr.log"),
                    "details": {"pid": 4242},
                    "record_path": str(record_path),
                }
            ),
            encoding="utf-8",
        )

        outcomes = supervisor.retry_cleanups()

        self.assertEqual(1, len(outcomes))
        self.assertEqual("complete", outcomes[0]["cleanup_status"])
        persisted = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual("settled", persisted["status"])
        self.assertEqual("complete", persisted["cleanup_status"])

    def test_herdr_batch_uses_current_workspace_agent_lifecycle(self) -> None:
        runner = FakeCommandRunner(
            {
                "herdr-custom workspace create": (
                    0,
                    {
                        "result": {
                            "workspace": "workspace-1",
                            "root_pane": {"pane_id": "pane-1"},
                        }
                    },
                ),
                "herdr-custom agent start": (0, {"result": {"ready": True}}),
                "herdr-custom agent prompt": (0, {"result": {"sent": True}}),
                "herdr-custom agent wait": (0, {"result": {"status": "idle"}}),
                "herdr-custom workspace close": (0, {"result": {"closed": True}}),
            }
        )
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("herdr", "pi", "HERDR_ENV", {}),
            herdr_binary="herdr-custom",
            run_process=runner,
        )

        outcome = supervisor.run_batch([self.request()])[0]

        self.assertTrue(outcome["settled"])
        self.assertEqual("complete", outcome["cleanup_status"])
        self.assertEqual("test-worker", outcome["handle_id"])
        commands = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("workspace create" in command for command in commands))
        self.assertTrue(
            any("agent start test-worker --kind pi --pane pane-1" in command for command in commands)
        )
        self.assertTrue(any("agent prompt test-worker" in command for command in commands))
        self.assertTrue(any("workspace close workspace-1" in command for command in commands))

    def test_reconcile_retries_a_settled_handle_cleanup(self) -> None:
        runner = FakeCommandRunner(
            {
                "herdr-custom pane close pane-retry": (
                    0,
                    {"result": {"closed": True}},
                )
            }
        )
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext("herdr", "pi", "HERDR_ENV", {}),
            herdr_binary="herdr-custom",
            run_process=runner,
        )
        record_path = self.run_dir / "supervisor" / supervisor.record_name(
            "validate:api:cleanup"
        )
        record_path.parent.mkdir(parents=True)
        record_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "action_id": "validate:api:cleanup",
                    "agent_name": "cleanup-worker",
                    "backend": "herdr",
                    "runtime": "pi",
                    "handle_id": "cleanup-worker",
                    "started_at": "2026-08-26T09:59:00Z",
                    "ended_at": "2026-08-26T10:00:00Z",
                    "status": "settled",
                    "cleanup_status": "failed",
                    "cleanup_error": "temporary server error",
                    "status_path": str(self.run_dir / "status.json"),
                    "stdout_path": str(self.run_dir / "stdout.log"),
                    "stderr_path": str(self.run_dir / "stderr.log"),
                    "details": {"workspace_id": None, "pane_id": "pane-retry"},
                    "record_path": str(record_path),
                }
            ),
            encoding="utf-8",
        )

        outcomes = supervisor.retry_cleanups()

        self.assertEqual(1, len(outcomes))
        self.assertEqual("complete", outcomes[0]["cleanup_status"])
        persisted = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual("complete", persisted["cleanup_status"])
        self.assertIsNone(persisted["cleanup_error"])

    def test_paseo_batch_creates_waits_for_and_archives_a_subagent(self) -> None:
        runner = FakeCommandRunner(
            {
                "paseo-custom run": (0, {"id": "paseo-worker-1"}),
                "paseo-custom wait paseo-worker-1": (
                    0,
                    {"id": "paseo-worker-1", "status": "idle"},
                ),
                "paseo-custom archive paseo-worker-1": (
                    0,
                    {"id": "paseo-worker-1", "archived": True},
                ),
            }
        )
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir,
            worker_supervisor.ExecutionContext(
                "paseo", "pi", "PASEO_AGENT_ID", {"parent_agent_id": "parent"}
            ),
            paseo_binary="paseo-custom",
            run_process=runner,
        )

        outcome = supervisor.run_batch([self.request()])[0]

        self.assertTrue(outcome["settled"])
        self.assertEqual("complete", outcome["cleanup_status"])
        self.assertEqual("paseo-worker-1", outcome["handle_id"])
        commands = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("run --background --json" in command for command in commands))
        self.assertTrue(any("wait paseo-worker-1" in command for command in commands))
        self.assertTrue(any("archive paseo-worker-1" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
