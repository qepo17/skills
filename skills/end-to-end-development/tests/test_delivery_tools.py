from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import delivery_tools


class FakeGitHub:
    """Real local Git with a fake external GitHub CLI seam."""

    def __init__(self, worktree: Path) -> None:
        self.worktree = worktree
        self.remote = worktree.parent / "remote.git"
        self.pr: dict[str, Any] | None = None
        self.required = [{"context": "tests", "app": None}]
        self.rules: list[dict[str, Any]] = []
        self.check_state = "success"
        self.drift_on_final_read = False
        self.view_count = 0
        self.create_count = 0
        self.api_failure = False
        self.failures_remaining = 0
        self.policy_reads = 0
        self.policy_drift = False
        self.crash_after: str | None = None
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[0] == "git":
            local = [str(self.remote) if item == "origin" and command[1] in {"push", "ls-remote"} else item for item in command]
            result = subprocess.run(local, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            if command[1] in {"commit", "push"} and self.crash_after == command[1] and result.returncode == 0:
                self.crash_after = None
                raise KeyboardInterrupt("simulated interruption after " + command[1])
            return result
        assert command[0] == "gh", command
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip()
        if command[1:3] == ["pr", "list"]:
            value = [self.pr] if self.pr else []
        elif command[1:3] == ["pr", "create"]:
            self.create_count += 1
            self.pr = {"number": 1, "url": "https://github.com/example/task/pull/1",
                       "baseRefName": command[command.index("--base") + 1],
                       "headRefName": command[command.index("--head") + 1], "state": "OPEN", "headRefOid": head}
            if self.crash_after == "pr-create":
                self.crash_after = None
                raise KeyboardInterrupt("simulated interruption after PR creation")
            return subprocess.CompletedProcess(command, 0, self.pr["url"] + "\n", "")
        elif command[1:3] == ["pr", "view"]:
            self.view_count += 1
            if self.crash_after == "checks" and self.view_count > 1:
                self.crash_after = None
                raise KeyboardInterrupt("simulated interruption after checks")
            value = {**(self.pr or {}), "headRefOid": "b" * 40 if self.drift_on_final_read and self.view_count > 1 else head}
        elif command[1] == "api":
            if self.api_failure:
                error = self.api_failure if isinstance(self.api_failure, str) else "HTTP 403: permission denied"
                return subprocess.CompletedProcess(command, 1, "", error)
            if "graphql" in command:
                self.policy_reads += 1
                required = self.required + ([{"context": "new-required", "app": None}] if self.policy_drift and self.policy_reads > 1 else [])
                value = {"data": {"repository": {"ref": {"branchProtectionRule": {
                    "requiresStatusChecks": bool(required), "requiredStatusChecks": required,
                }}}}}
            elif any("/rules/branches/" in arg for arg in command):
                value = [self.rules]
            elif any("/check-runs" in arg for arg in command):
                state = "failure" if self.failures_remaining else self.check_state
                self.failures_remaining = max(0, self.failures_remaining - 1)
                checks = [] if state == "missing" else [{"name": "tests", "head_sha": head,
                    "status": "in_progress" if state == "pending" else "completed",
                    "conclusion": None if state == "pending" else state,
                    "html_url": "https://github.com/example/task/actions/runs/1", "app": {"id": 123}}]
                value = [{"check_runs": checks}]
            elif any("/statuses" in arg for arg in command):
                value = [[]]
            else:
                raise AssertionError(command)
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")


class DeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Tests")
        self.git("config", "user.email", "tests@example.test")
        (self.repo / "README.md").write_text("baseline\n")
        self.git("add", "README.md")
        self.git("commit", "-qm", "initial")
        baseline = self.git("rev-parse", "HEAD")
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.git("remote", "add", "origin", "git@github.com:example/task.git")
        self.git("push", "-q", str(remote), "main")
        self.git("switch", "-qc", "feat/test")
        (self.repo / "feature.txt").write_text("implemented\n")
        self.forge = FakeGitHub(self.repo)
        self.spec = {"repository": "github.com/example/task", "worktree": str(self.repo),
                     "baseline": baseline, "base_branch": "main", "branch": "feat/test",
                     "task_files": ["feature.txt"], "expected_fingerprint": delivery_tools.content_fingerprint(self.repo),
                     "commit_message": "feat: implement task", "pr_title": "Implement task", "pr_body": "Tested change.",
                     "log_dir": str(self.root / "logs"), "check_timeout_seconds": 0}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True, stderr=subprocess.DEVNULL).strip()

    def deliver(self) -> dict[str, Any]:
        return delivery_tools.Delivery(self.spec, run_process=self.forge).run()

    def test_success_is_bound_to_local_pushed_and_checked_head(self) -> None:
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertEqual(self.git("rev-parse", "HEAD"), result["checked_head_sha"])
        self.assertEqual(result["head_sha"], result["pushed_head_sha"])
        self.assertEqual("required", result["check_policy"]["status"])
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_changed_required_policy_cannot_reuse_an_earlier_pass(self) -> None:
        self.forge.policy_drift = True
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertIn("policy", result["summary"].lower())

    def test_ruleset_check_requires_the_configured_app_identity(self) -> None:
        self.forge.required = []
        self.forge.rules = [{"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": "tests", "integration_id": 456}]}}]
        result = self.deliver()
        self.assertEqual("pending", result["status"], result)
        self.forge.rules[0]["parameters"]["required_status_checks"][0]["integration_id"] = 123
        self.assertEqual("complete", self.deliver()["status"])

    def test_argument_like_filename_is_staged_as_a_path_not_an_option(self) -> None:
        (self.repo / "--argument.txt").write_text("safe path\n")
        self.spec["task_files"].append("--argument.txt")
        self.spec["expected_fingerprint"] = delivery_tools.content_fingerprint(self.repo)
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertEqual("safe path", self.git("show", "HEAD:--argument.txt"))

    def test_retry_reuses_the_existing_commit_and_pr(self) -> None:
        first = self.deliver()
        second = self.deliver()
        self.assertEqual("complete", first["status"], first)
        self.assertEqual(first["commits"], second["commits"])
        self.assertEqual(1, self.forge.create_count)

    def test_pending_and_missing_checks_are_not_success(self) -> None:
        for state in ("pending", "missing"):
            self.forge.check_state = state
            result = self.deliver()
            self.assertEqual("pending", result["status"], result)
            self.assertNotEqual("code", result["kind"])

    def test_failed_cancelled_and_skipped_required_checks_block(self) -> None:
        for state in ("failure", "cancelled", "skipped"):
            self.forge.check_state = state
            result = self.deliver()
            self.assertEqual("blocked", result["status"], result)
            self.assertEqual("code", result["kind"])

    def test_a_changed_pr_head_invalidates_the_checks(self) -> None:
        self.forge.drift_on_final_read = True
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertIn("head", result["summary"].lower())

    def test_no_required_checks_needs_positive_policy_evidence(self) -> None:
        self.forge.required = []
        self.forge.check_state = "missing"
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertEqual("not-configured", result["check_policy"]["status"])
        self.assertEqual(2, len(result["check_policy"]["evidence"]))
        self.forge.api_failure = True
        result = self.deliver()
        self.assertEqual("blocked", result["status"])
        self.assertEqual("permission", result["kind"])

    def test_access_and_rate_limit_failures_are_not_code_failures(self) -> None:
        for message, kind in (("HTTP 401: authentication required", "authentication"),
                              ("HTTP 403: permission denied", "permission"),
                              ("HTTP 403: API rate limit exceeded", "infrastructure")):
            with self.subTest(kind=kind):
                self.forge.api_failure = message
                result = self.deliver()
                self.assertEqual("blocked", result["status"], result)
                self.assertEqual(kind, result["kind"])
                self.assertIsNone(result["checked_head_sha"])

    def test_unrelated_staged_work_is_preserved_and_never_committed(self) -> None:
        (self.repo / "unrelated.txt").write_text("user work\n")
        self.git("add", "unrelated.txt")
        before = self.git("diff", "--cached")
        result = self.deliver()
        self.assertEqual("blocked", result["status"])
        self.assertEqual(before, self.git("diff", "--cached"))
        self.assertEqual(self.spec["baseline"], self.git("rev-parse", "HEAD"))

    def test_unrelated_staged_version_hidden_by_worktree_is_rejected(self) -> None:
        (self.repo / "README.md").write_text("unrelated staged version\n")
        self.git("add", "README.md")
        (self.repo / "README.md").write_text("baseline\n")
        before = self.git("diff", "--cached")
        self.spec["expected_fingerprint"] = delivery_tools.content_fingerprint(self.repo)
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual(before, self.git("diff", "--cached"))
        self.assertEqual(self.spec["baseline"], self.git("rev-parse", "HEAD"))

    def test_push_url_and_push_rewrites_are_audited_before_side_effects(self) -> None:
        for key, value in (("remote.origin.pushurl", "git@github.com:other/private.git"),
                           ("url.git@github.com:other/private.git.pushInsteadOf", "git@github.com:example/task.git")):
            with self.subTest(key=key):
                self.git("config", key, value)
                try:
                    result = self.deliver()
                    self.assertEqual("blocked", result["status"], result)
                    self.assertEqual(self.spec["baseline"], self.git("rev-parse", "HEAD"))
                    self.assertFalse(any(c[1] == "push" for c in self.forge.commands))
                finally:
                    self.git("config", "--unset", key)

    def test_index_only_hook_mutation_is_never_pushed(self) -> None:
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nprintf 'unvalidated\\n' > README.md\ngit add -- README.md\nprintf 'baseline\\n' > README.md\n")
        hook.chmod(0o755)
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertFalse(any(c[1] == "push" for c in self.forge.commands))

    def test_verify_only_never_commits_pushes_or_creates_a_pr(self) -> None:
        first = self.deliver()
        self.assertEqual("complete", first["status"], first)
        self.forge.commands.clear()
        checked = delivery_tools.Delivery(self.spec, run_process=self.forge).run(verify_only=True)
        self.assertEqual("complete", checked["status"], checked)
        self.assertFalse(any(c[:2] in (["git", "commit"], ["git", "push"]) or c[:3] == ["gh", "pr", "create"]
                             for c in self.forge.commands))
        self.forge.pr = None
        missing = delivery_tools.Delivery(self.spec, run_process=self.forge).run(verify_only=True)
        self.assertEqual("blocked", missing["status"], missing)
        self.assertEqual(1, self.forge.create_count)

    def test_git_hook_content_mutation_does_not_inherit_passing_validation(self) -> None:
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nprintf 'hook mutation\\n' > feature.txt\ngit add -- feature.txt\n")
        hook.chmod(0o755)
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertIn("content", result["summary"].lower())
        self.assertEqual(0, self.forge.create_count)

    def test_branch_option_injection_and_path_escape_are_rejected(self) -> None:
        for key, value in (("branch", "--upload-pack=bad"), ("task_files", ["../secret"])):
            spec = {**self.spec, key: value}
            result = delivery_tools.Delivery(spec, run_process=self.forge).run()
            self.assertEqual("blocked", result["status"])
        self.assertEqual(self.spec["baseline"], self.git("rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
