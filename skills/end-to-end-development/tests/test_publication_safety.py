from __future__ import annotations

import copy
import subprocess
import unittest
from pathlib import Path

import test_effect_guard
from test_delivery_tools import record_publication
import delivery_tools


class PublicationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_effect_guard.EffectGuardTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.repo, self.git, self.forge, self.guard, self.effect = self.fixture.real_delivery("publication")

    @property
    def spec(self):
        return self.effect["delivery"]

    def review(self):
        record_publication(self.spec, self.git, self.forge.remote)

    def assert_no_publication(self):
        self.assertFalse(any(command[:2] == ["git", "push"] or command[:3] in (
            ["gh", "pr", "create"], ["gh", "pr", "edit"], ["gh", "pr", "ready"])
            for command in self.forge.commands))

    def test_deleted_credential_history_cannot_hide_in_the_final_diff(self):
        (self.repo / ".env").write_text("EXAMPLE_SECRET=FAKE_AUDIT_VALUE\n")
        self.git("add", ".env")
        self.git("commit", "-qm", "Temporary local credential")
        self.git("rm", "-q", ".env")
        self.git("commit", "-qm", "Remove local credential")
        self.spec["reviewed_head"] = self.git("rev-parse", "HEAD")
        self.assertEqual(self.spec["expected_fingerprint"], delivery_tools.content_fingerprint(self.repo))
        omitted = self.guard.ensure(self.effect)
        self.assertEqual("unreviewed-outgoing-commits", omitted["reason_code"], omitted)
        self.review()
        included = self.guard.ensure(self.effect)
        self.assertEqual("credential-file-in-history", included["reason_code"], included)
        self.assert_no_publication()

    def test_unpublished_commits_before_the_task_baseline_need_explicit_review(self):
        (self.repo / "private-notes.txt").write_text("Pre-existing local work\n")
        self.git("add", "private-notes.txt")
        self.git("commit", "-qm", "Unpublished work")
        self.spec["baseline"] = self.git("rev-parse", "HEAD")
        (self.repo / "feature.txt").write_text("Requested fix\n")
        self.git("commit", "-qam", "Requested fix")
        self.review()
        self.spec["reviewed_commits"] = [self.spec["reviewed_head"]]
        result = self.guard.ensure(self.effect)
        self.assertEqual("unreviewed-outgoing-commits", result["reason_code"], result)
        self.assert_no_publication()

    def test_reviewed_commit_identity_cannot_be_replaced_by_an_identical_tree(self):
        self.git("commit", "--allow-empty", "-qm", "Unreviewed metadata")
        self.assertEqual(self.spec["expected_fingerprint"], delivery_tools.content_fingerprint(self.repo))
        result = self.guard.ensure(self.effect)
        self.assertEqual("reviewed-head-changed", result["reason_code"], result)
        self.assert_no_publication()

    def test_replacement_refs_cannot_hide_unpublished_history(self):
        (self.repo / ".env").write_text("SECRET=FAKE_AUDIT_VALUE\n")
        self.git("add", ".env")
        self.git("commit", "-qm", "Local credential")
        self.git("rm", "-q", ".env")
        self.git("commit", "-qm", "Remove credential")
        head = self.git("rev-parse", "HEAD")
        replacement = self.git("commit-tree", "HEAD^{tree}", "-p", self.spec["baseline"], "-m", "Synthetic ancestry")
        self.git("replace", head, replacement)
        self.review()
        self.assertEqual([head], self.spec["reviewed_commits"])
        result = self.guard.ensure(self.effect)
        self.assertEqual("incomplete-publication-history", result["reason_code"], result)
        self.assert_no_publication()

    def test_shallow_boundaries_and_grafts_cannot_hide_history(self):
        for path, content in (("shallow", self.spec["reviewed_head"] + "\n"),
                              ("info/grafts", self.spec["reviewed_head"] + "\n")):
            with self.subTest(path=path):
                metadata = self.repo / ".git" / path
                metadata.parent.mkdir(parents=True, exist_ok=True)
                metadata.write_text(content)
                try:
                    result = self.guard.ensure(self.effect)
                    self.assertEqual("incomplete-publication-history", result["reason_code"], result)
                    self.assert_no_publication()
                finally:
                    metadata.unlink()

    def test_publication_does_not_stage_uncommitted_changes_in_an_allowed_file(self):
        (self.repo / "feature.txt").write_text("Task change mixed with unfinished user work\n")
        self.spec["expected_fingerprint"] = delivery_tools.content_fingerprint(self.repo)
        result = self.guard.ensure(self.effect)
        self.assertEqual("uncommitted-content", result["reason_code"], result)
        self.assertEqual("", self.git("diff", "--cached"))
        self.assertEqual(self.spec["reviewed_head"], self.git("rev-parse", "HEAD"))
        self.assert_no_publication()

    def test_push_follow_tags_cannot_expand_publication(self):
        self.git("config", "push.followTags", "true")
        self.git("tag", "-a", "private-release", "-m", "Private release note", self.spec["baseline"])
        result = self.guard.ensure(self.effect)
        self.assertEqual("complete", result["status"], result)
        tags = subprocess.check_output(["git", "--git-dir", str(self.forge.remote), "tag"], text=True)
        self.assertEqual("", tags)

    def test_push_cannot_publish_to_an_unaudited_submodule_remote(self):
        nested_remote = self.fixture.root / "nested.git"
        subprocess.run(["git", "init", "--bare", "-q", str(nested_remote)], check=True)
        source = self.fixture.root / "nested-source"
        subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)

        def nested_git(root, *args):
            return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()

        nested_git(source, "config", "user.name", "Tests")
        nested_git(source, "config", "user.email", "tests@example.test")
        (source / "file.txt").write_text("Nested baseline\n")
        nested_git(source, "add", "file.txt")
        nested_git(source, "commit", "-qm", "Initial nested content")
        nested_git(source, "push", "-q", str(nested_remote), "main")
        subprocess.run(["git", "--git-dir", str(nested_remote), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", str(nested_remote), "nested")
        nested = self.repo / "nested"
        nested_git(nested, "config", "user.name", "Tests")
        nested_git(nested, "config", "user.email", "tests@example.test")
        nested_git(nested, "switch", "-qc", "feat/test")
        (nested / "file.txt").write_text("Unpublished nested work\n")
        nested_git(nested, "commit", "-qam", "Nested work")
        nested_head = nested_git(nested, "rev-parse", "HEAD")
        self.git("add", ".gitmodules", "nested")
        self.git("commit", "-qm", "Task gitlink")
        self.git("config", "push.recurseSubmodules", "on-demand")
        self.spec["task_files"] += [".gitmodules", "nested"]
        self.review()
        result = self.guard.ensure(self.effect)
        self.assertEqual("complete", result["status"], result)
        remote_heads = subprocess.check_output(["git", "ls-remote", str(nested_remote)], text=True)
        self.assertNotIn(nested_head, remote_heads)

    def test_index_flags_do_not_hide_changed_files_or_mutate_the_index(self):
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                (self.repo / "README.md").write_text("baseline\n")
                self.git("update-index", "--no-assume-unchanged", "--no-skip-worktree", "README.md")
                self.git("update-index", flag, "README.md")
                before_index = (self.repo / ".git/index").read_bytes()
                before = delivery_tools.content_fingerprint(self.repo)
                (self.repo / "README.md").write_text("Unverified local content\n")
                after = delivery_tools.content_fingerprint(self.repo)
                self.assertNotEqual(before, after)
                self.assertEqual(before_index, (self.repo / ".git/index").read_bytes())
                self.spec["expected_fingerprint"] = after
                result = self.guard.ensure(self.effect)
                self.assertEqual("uncommitted-content", result["reason_code"], result)
                self.assert_no_publication()

    def test_absent_sparse_paths_preserve_the_reviewed_tree(self):
        for directory in ("kept", "excluded"):
            (self.repo / directory).mkdir()
            (self.repo / directory / "file.txt").write_text(directory)
        self.git("add", "kept", "excluded")
        self.git("commit", "-qm", "Add directories")
        self.spec["task_files"] += ["kept/file.txt", "excluded/file.txt"]
        self.review()
        full = self.spec["expected_fingerprint"]
        self.git("sparse-checkout", "init", "--cone")
        self.git("sparse-checkout", "set", "kept")
        self.assertFalse((self.repo / "excluded/file.txt").exists())
        self.assertEqual(full, delivery_tools.content_fingerprint(self.repo))
        result = self.guard.ensure(self.effect)
        self.assertEqual("complete", result["status"], result)

    def test_closed_or_retargeted_pr_blocks_before_a_revised_push(self):
        first = self.guard.ensure(self.effect)
        self.assertEqual("complete", first["status"], first)
        old_head = self.spec["reviewed_head"]
        (self.repo / "feature.txt").write_text("Verified revision\n")
        self.git("commit", "-qam", "Verified revision")
        self.review()
        original_pr = copy.deepcopy(self.forge.pr)
        for change in ({"state": "CLOSED"}, {"baseRefName": "different-base"}):
            with self.subTest(change=change):
                self.forge.pr = {**original_pr, **change}
                self.forge.commands.clear()
                result = self.guard.ensure(self.effect)
                self.assertEqual("unexpected-pr-identity", result["reason_code"], result)
                self.assert_no_publication()
                remote_head = subprocess.check_output(["git", "--git-dir", str(self.forge.remote), "rev-parse",
                                                       "refs/heads/feat/test"], text=True).strip()
                self.assertEqual(old_head, remote_head)

    def test_remote_drift_requires_a_new_reviewed_proposal(self):
        self.git("push", "-q", str(self.forge.remote), f"{self.spec['baseline']}:refs/heads/feat/test")
        result = self.guard.ensure(self.effect)
        self.assertEqual("remote-head-changed", result["reason_code"], result)
        self.assert_no_publication()


class MergeabilityObservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_effect_guard.EffectGuardTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.repo, self.git, self.forge, guard, effect = self.fixture.real_delivery("observation")
        published = guard.ensure(effect)
        self.assertEqual("complete", published["status"], published)
        self.spec = {**effect["delivery"], "log_dir": str(self.fixture.root / "observations")}
        self.forge.commands.clear()

    def observe(self, **kwargs):
        return delivery_tools.Delivery(self.spec, run_process=self.forge).observe_mergeability(**kwargs)

    def test_green_observation_does_not_mutate_git_or_the_pr(self):
        index_before = (self.repo / ".git/index").read_bytes()
        pr_before = copy.deepcopy(self.forge.pr)
        result = self.observe()
        self.assertEqual("mergeable", result["status"], result)
        self.assertEqual(index_before, (self.repo / ".git/index").read_bytes())
        self.assertEqual(pr_before, self.forge.pr)
        self.assertFalse(any(command[:2] in (["git", "add"], ["git", "commit"], ["git", "push"])
                             or command[:3] in (["gh", "pr", "create"], ["gh", "pr", "edit"], ["gh", "pr", "ready"])
                             for command in self.forge.commands))

    def test_required_skips_block_but_optional_skips_are_acceptable(self):
        self.forge.check_state = "skipped"
        required = self.observe()
        self.assertEqual("blocked", required["status"], required)
        self.assertEqual("required-ci-failed", required["reason_code"])
        self.forge.required = []
        optional = self.observe()
        self.assertEqual("mergeable", optional["status"], optional)

    def test_missing_required_checks_never_pass_even_with_no_checks_assertion(self):
        self.forge.check_state = "missing"
        result = self.observe(no_checks_expected=True)
        self.assertEqual("pending", result["status"], result)
        self.assertEqual("checks-pending", result["reason_code"])

    def test_absent_optional_checks_need_an_explicit_workflow_expectation(self):
        self.forge.required = []
        self.forge.check_state = "missing"
        self.assertEqual("checks-not-observed", self.observe()["reason_code"])
        self.assertEqual("mergeable", self.observe(no_checks_expected=True)["status"])

    def test_pending_and_failed_optional_checks_block_completion(self):
        self.forge.required = []
        for state, expected in (("pending", "checks-pending"), ("failure", "ci-failed"), ("cancelled", "ci-failed")):
            with self.subTest(state=state):
                self.forge.check_state = state
                self.assertEqual(expected, self.observe()["reason_code"])

    def test_drafts_and_unmet_merge_or_review_requirements_are_not_mergeable(self):
        self.forge.pr["isDraft"] = True
        self.assertEqual("pr-draft", self.observe()["reason_code"])
        self.forge.pr["isDraft"] = False
        for state in ("BLOCKED", "BEHIND", "DIRTY", "UNSTABLE"):
            with self.subTest(state=state):
                self.forge.merge_state = state
                self.assertEqual("merge-requirements-unmet", self.observe()["reason_code"])
        self.forge.merge_state = "UNKNOWN"
        self.assertEqual("merge-state-pending", self.observe()["reason_code"])
        self.forge.merge_state = "CLEAN"
        for decision in ("REVIEW_REQUIRED", "CHANGES_REQUESTED"):
            with self.subTest(decision=decision):
                self.forge.review_decision = decision
                self.assertEqual("review-required", self.observe()["reason_code"])

    def test_head_and_required_policy_drift_invalidate_observation(self):
        self.forge.drift_on_final_read = True
        self.assertEqual("pr-head-changed", self.observe()["reason_code"])
        self.forge.drift_on_final_read = False
        self.forge.policy_drift = True
        self.forge.policy_reads = 0
        self.assertEqual("required-policy-changed", self.observe()["reason_code"])


if __name__ == "__main__":
    unittest.main()
