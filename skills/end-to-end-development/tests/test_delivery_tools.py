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
        self.ready_count = 0
        self.edit_count = 0
        self.api_failure = False
        self.failures_remaining = 0
        self.policy_reads = 0
        self.policy_drift = False
        self.policy_drift_after_ready = False
        self.check_state_after_ready: str | None = None
        self.head_drift_after_ready = False
        self.draft_creation_failure = False
        self.ready_failure = False
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
            if self.draft_creation_failure and "--draft" in command:
                return subprocess.CompletedProcess(command, 1, "", "draft pull requests are unavailable")
            body = Path(command[command.index("--body-file") + 1]).read_text()
            self.pr = {"number": 1, "url": "https://github.com/example/task/pull/1",
                       "baseRefName": command[command.index("--base") + 1],
                       "headRefName": command[command.index("--head") + 1], "state": "OPEN", "headRefOid": head,
                       "isDraft": "--draft" in command, "body": body}
            if self.crash_after == "pr-create":
                self.crash_after = None
                raise KeyboardInterrupt("simulated interruption after PR creation")
            return subprocess.CompletedProcess(command, 0, self.pr["url"] + "\n", "")
        elif command[1:3] == ["pr", "ready"]:
            self.ready_count += 1
            if self.ready_failure:
                return subprocess.CompletedProcess(command, 1, "", "publication rejected")
            assert self.pr is not None
            self.pr["isDraft"] = False
            if self.crash_after == "pr-ready":
                self.crash_after = None
                raise KeyboardInterrupt("simulated interruption after PR publication")
            return subprocess.CompletedProcess(command, 0, "", "")
        elif command[1:3] == ["pr", "edit"]:
            self.edit_count += 1
            assert self.pr is not None
            self.pr["body"] = Path(command[command.index("--body-file") + 1]).read_text()
            if self.crash_after == "pr-edit":
                self.crash_after = None
                raise KeyboardInterrupt("simulated interruption after PR body reconciliation")
            return subprocess.CompletedProcess(command, 0, "", "")
        elif command[1:3] == ["pr", "view"]:
            self.view_count += 1
            if self.crash_after == "checks" and self.view_count > 1:
                self.crash_after = None
                raise KeyboardInterrupt("simulated interruption after checks")
            drift = (self.drift_on_final_read and self.view_count > 1) or (self.head_drift_after_ready and self.ready_count)
            value = {**(self.pr or {}), "headRefOid": "b" * 40 if drift else head}
        elif command[1] == "api":
            if self.api_failure:
                error = self.api_failure if isinstance(self.api_failure, str) else "HTTP 403: permission denied"
                return subprocess.CompletedProcess(command, 1, "", error)
            if "graphql" in command:
                self.policy_reads += 1
                drift = (self.policy_drift and self.policy_reads > 1) or (self.policy_drift_after_ready and self.ready_count)
                required = self.required + ([{"context": "new-required", "app": None}] if drift else [])
                value = {"data": {"repository": {"ref": {"branchProtectionRule": {
                    "requiresStatusChecks": bool(required), "requiredStatusChecks": required,
                }}}}}
            elif any("/rules/branches/" in arg for arg in command):
                value = [self.rules]
            elif any("/check-runs" in arg for arg in command):
                state = "failure" if self.failures_remaining else (
                    self.check_state_after_ready if self.ready_count and self.check_state_after_ready else self.check_state)
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

    def test_draft_lifecycle_requires_a_run_identity_before_delivery(self) -> None:
        self.spec["pr_lifecycle"] = "draft-until-verified"
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("decision", result["kind"])
        self.assertEqual("invalid-run-id", result["reason_code"])
        self.assertFalse(any(command[:3] == ["gh", "pr", "create"] for command in self.forge.commands))

    def test_owned_draft_is_published_after_green_required_ci(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertTrue(result["pr_owned"])
        self.assertFalse(result["pr_draft"])
        self.assertEqual(1, self.forge.create_count)
        self.assertEqual(1, self.forge.ready_count)
        create = next(command for command in self.forge.commands if command[:3] == ["gh", "pr", "create"])
        self.assertIn("--draft", create)

    def test_red_ci_reconciles_only_the_owned_validation_section_after_creation_crash(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.crash_after = "pr-create"
        with self.assertRaises(KeyboardInterrupt):
            self.deliver()
        assert self.forge.pr is not None
        self.forge.pr["body"] += "\nHuman follow-up note.\n"
        self.forge.check_state = "failure"
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("code", result["kind"])
        self.assertEqual("required-ci-failed", result["reason_code"])
        self.assertTrue(result["pr_owned"])
        self.assertTrue(result["pr_draft"])
        self.assertEqual(1, self.forge.create_count)
        self.assertEqual(1, self.forge.edit_count)
        self.assertIn("Human follow-up note.", self.forge.pr["body"])
        self.assertIn("Required CI failed", self.forge.pr["body"])

    def test_verify_only_green_owned_draft_requires_publication_without_any_write(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.crash_after = "pr-create"
        with self.assertRaises(KeyboardInterrupt):
            self.deliver()
        self.forge.commands.clear()
        result = delivery_tools.Delivery(self.spec, run_process=self.forge).run(verify_only=True)
        self.assertEqual("pending", result["status"], result)
        self.assertEqual("infrastructure", result["kind"])
        self.assertEqual("publication-required", result["reason_code"])
        self.assertTrue(result["pr_owned"])
        self.assertTrue(result["pr_draft"])
        writes = (["git", "commit"], ["git", "push"], ["gh", "pr", "create"],
                  ["gh", "pr", "edit"], ["gh", "pr", "ready"])
        self.assertFalse(any(any(command[:len(prefix)] == prefix for prefix in writes)
                             for command in self.forge.commands))

    def test_existing_user_owned_draft_is_verified_without_body_or_readiness_changes(self) -> None:
        self.assertEqual("complete", self.deliver()["status"])
        assert self.forge.pr is not None
        self.forge.pr.update(isDraft=True, body="Human-authored PR body.\n")
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.commands.clear()
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertFalse(result["pr_owned"])
        self.assertTrue(result["pr_draft"])
        self.assertEqual("Human-authored PR body.\n", self.forge.pr["body"])
        self.assertFalse(any(command[:3] in (["gh", "pr", "edit"], ["gh", "pr", "ready"])
                             for command in self.forge.commands))

    def test_human_edits_inside_managed_section_are_preserved_as_a_conflict(self) -> None:
        self.spec.update(pr_lifecycle='draft-until-verified', run_id='run-123')
        self.forge.check_state = 'failure'
        delivery_tools.Delivery(self.spec, run_process=self.forge).run()
        self.forge.pr['body'] = self.forge.pr['body'].replace('delivery remains blocked.', 'a human explanation must remain.')
        edited = self.forge.pr['body']
        result = delivery_tools.Delivery(self.spec, run_process=self.forge).run()
        self.assertEqual('managed-body-edited', result['reason_code'])
        self.assertEqual(edited, self.forge.pr['body'])

    def test_concurrent_redrafting_does_not_create_a_publication_loop(self) -> None:
        self.spec.update(pr_lifecycle='draft-until-verified', run_id='run-123')
        views = 0
        def redraft(command, cwd, timeout):
            nonlocal views
            if command[:3] == ['gh', 'pr', 'view'] and self.forge.ready_count:
                views += 1
                if views >= 2:
                    self.forge.pr['isDraft'] = True
            return self.forge(command, cwd, timeout)
        result = delivery_tools.Delivery(self.spec, run_process=redraft).run()
        self.assertEqual('pr-readiness-changed', result['reason_code'])
        self.assertEqual(1, self.forge.ready_count)

    def test_legacy_delivery_still_creates_a_ready_unmanaged_pr(self) -> None:
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertFalse(result["pr_owned"])
        self.assertFalse(result["pr_draft"])
        self.assertEqual(0, self.forge.ready_count)
        assert self.forge.pr is not None
        self.assertEqual(self.spec["pr_body"], self.forge.pr["body"])
        create = next(command for command in self.forge.commands if command[:3] == ["gh", "pr", "create"])
        self.assertNotIn("--draft", create)

    def test_pending_draft_does_not_publish_to_trigger_ci(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.check_state = "pending"
        result = self.deliver()
        self.assertEqual("pending", result["status"], result)
        self.assertEqual("required-ci-pending", result["reason_code"])
        self.assertIn("draft", result["summary"].lower())
        self.assertTrue(result["pr_owned"])
        self.assertTrue(result["pr_draft"])
        self.assertEqual(0, self.forge.ready_count)

    def test_unavailable_draft_creation_is_reported_without_ready_fallback(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.draft_creation_failure = True
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("draft-pr-creation-failed", result["reason_code"])
        self.assertIsNone(result["pr_draft"])
        self.assertFalse(result["pr_owned"])
        self.assertIsNone(self.forge.pr)
        self.assertEqual(0, self.forge.ready_count)

    def test_failed_publication_keeps_the_last_observed_draft_state(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.ready_failure = True
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("publication-failed", result["reason_code"])
        self.assertTrue(result["pr_owned"])
        self.assertTrue(result["pr_draft"])

    def test_unknown_required_ci_conclusion_is_a_failure_not_a_waiver(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.check_state = "unknown"
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("code", result["kind"])
        self.assertEqual("required-ci-failed", result["reason_code"])
        self.assertEqual(0, self.forge.ready_count)

    def test_positive_not_configured_policy_allows_owned_draft_publication(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.required = []
        self.forge.check_state = "missing"
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertEqual("not-configured", result["check_policy"]["status"])
        self.assertTrue(result["pr_owned"])
        self.assertFalse(result["pr_draft"])
        self.assertEqual(1, self.forge.ready_count)
        self.assertGreaterEqual(self.forge.policy_reads, 3)
        self.assertGreaterEqual(sum(command[1] == "api" and any("/check-runs" in arg for arg in command)
                                    for command in self.forge.commands), 2)

    def test_ci_pending_after_publication_stays_pending_with_actual_ready_state(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.check_state_after_ready = "pending"
        result = self.deliver()
        self.assertEqual("pending", result["status"], result)
        self.assertEqual("required-ci-pending", result["reason_code"])
        self.assertTrue(result["pr_owned"])
        self.assertFalse(result["pr_draft"])
        self.assertEqual(1, self.forge.ready_count)

    def test_externally_published_owned_draft_can_be_verified_without_writes(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.check_state = "pending"
        self.assertEqual("pending", self.deliver()["status"])
        assert self.forge.pr is not None
        self.forge.pr["isDraft"] = False
        self.forge.check_state = "success"
        self.forge.commands.clear()
        result = delivery_tools.Delivery(self.spec, run_process=self.forge).run(verify_only=True)
        self.assertEqual("complete", result["status"], result)
        self.assertTrue(result["pr_owned"])
        self.assertFalse(result["pr_draft"])
        self.assertFalse(any(command[:3] in (["gh", "pr", "edit"], ["gh", "pr", "ready"])
                             for command in self.forge.commands))

    def test_ownership_marker_is_hashed_and_bound_to_the_run_identity(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="private-run-123")
        self.forge.crash_after = "pr-create"
        with self.assertRaises(KeyboardInterrupt):
            self.deliver()
        assert self.forge.pr is not None
        original_body = self.forge.pr["body"]
        self.assertNotIn("private-run-123", original_body)
        self.spec["run_id"] = "different-run-456"
        self.spec['pr_intent_path'] = str(self.root / 'different-run-creation-intent.json')
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertFalse(result["pr_owned"])
        self.assertTrue(result["pr_draft"])
        self.assertEqual(original_body, self.forge.pr["body"])
        self.assertEqual(0, self.forge.ready_count)

    def test_preexisting_public_marker_without_local_creation_intent_is_not_ownership(self) -> None:
        self.spec.update(pr_lifecycle='draft-until-verified', run_id='run-123')
        helper = delivery_tools.Delivery(self.spec, run_process=self.forge)
        body = helper.body_with_managed_section('Human-owned PR', 'Required CI has not yet been observed.')
        self.forge.pr = {'url': 'https://github.com/example/task/pull/1', 'baseRefName': 'main',
                         'headRefName': 'feat/test', 'state': 'OPEN', 'isDraft': True, 'body': body}
        result = self.deliver()
        self.assertEqual('complete', result['status'])
        self.assertFalse(result['pr_owned'])
        self.assertTrue(result['pr_draft'])
        self.assertEqual(body, self.forge.pr['body'])
        self.assertFalse(helper.intent_path.exists())
        self.assertEqual(0, self.forge.ready_count)
        self.assertEqual(0, self.forge.create_count)

    def test_user_redrafting_after_prior_ready_observation_is_preserved(self) -> None:
        self.spec.update(pr_lifecycle='draft-until-verified', run_id='run-123')
        self.assertEqual('complete', self.deliver()['status'])
        self.forge.pr['isDraft'] = True
        result = self.deliver()
        self.assertEqual('pr-readiness-changed', result['reason_code'])
        self.assertTrue(result['pr_draft'])
        self.assertEqual(1, self.forge.ready_count)

    def test_promotion_is_recovered_without_repeating_the_readiness_write(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.crash_after = "pr-ready"
        with self.assertRaises(KeyboardInterrupt):
            self.deliver()
        self.assertEqual(1, self.forge.ready_count)
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertTrue(result["pr_owned"])
        self.assertFalse(result["pr_draft"])
        self.assertEqual(1, self.forge.create_count)
        self.assertEqual(1, self.forge.ready_count)

    def test_commit_crash_recovery_reuses_the_validated_commit(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.crash_after = "commit"
        with self.assertRaises(KeyboardInterrupt):
            self.deliver()
        committed = self.git("rev-parse", "HEAD")
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        self.assertEqual(committed, result["head_sha"])
        pushes = [command for command in self.forge.commands if command[:2] == ["git", "push"]]
        self.assertEqual(1, len(pushes))
        self.assertNotIn("--force", pushes[0])

    def test_push_crash_recovery_does_not_push_the_same_head_twice(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.crash_after = "push"
        with self.assertRaises(KeyboardInterrupt):
            self.deliver()
        result = self.deliver()
        self.assertEqual("complete", result["status"], result)
        pushes = [command for command in self.forge.commands if command[:2] == ["git", "push"]]
        self.assertEqual(1, len(pushes))
        self.assertNotIn("--force", pushes[0])

    def test_body_reconciliation_crash_is_idempotent(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.check_state = "failure"
        self.forge.crash_after = "pr-edit"
        with self.assertRaises(KeyboardInterrupt):
            self.deliver()
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("required-ci-failed", result["reason_code"])
        self.assertEqual(1, self.forge.edit_count)

    def test_required_ci_is_reobserved_after_publication(self) -> None:
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        self.forge.check_state_after_ready = "failure"
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("code", result["kind"])
        self.assertEqual("required-ci-failed", result["reason_code"])
        self.assertFalse(result["pr_draft"])
        self.assertIsNone(result["checked_head_sha"])

    def test_policy_is_reobserved_after_publication(self) -> None:
        self.forge.policy_drift_after_ready = True
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("required-policy-changed", result["reason_code"])
        self.assertFalse(result["pr_draft"])

    def test_head_is_reobserved_after_publication(self) -> None:
        self.forge.head_drift_after_ready = True
        self.spec.update(pr_lifecycle="draft-until-verified", run_id="run-123")
        result = self.deliver()
        self.assertEqual("blocked", result["status"], result)
        self.assertEqual("pr-head-changed", result["reason_code"])
        self.assertFalse(result["pr_draft"])

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
            self.assertEqual("required-ci-pending", result["reason_code"])

    def test_failed_cancelled_and_skipped_required_checks_block(self) -> None:
        for state in ("failure", "cancelled", "skipped"):
            self.forge.check_state = state
            result = self.deliver()
            self.assertEqual("blocked", result["status"], result)
            self.assertEqual("code", result["kind"])
            self.assertEqual("required-ci-failed", result["reason_code"])

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
