from __future__ import annotations

import copy
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import delivery_tools  # noqa: E402
from effect_guard import EffectGuard  # noqa: E402
from test_delivery_tools import FakeGitHub  # noqa: E402


class FakeDelivery:
    def __init__(self, result):
        self.result = result

    def run(self):
        if isinstance(self.result, BaseException):
            raise self.result
        return copy.deepcopy(self.result)


class DeliveryFactory:
    def __init__(self, results):
        self.results = list(results)
        self.specs = []

    def __call__(self, spec):
        self.specs.append(spec)
        if not self.results:
            raise AssertionError("delivery adapter was invoked unexpectedly")
        return FakeDelivery(self.results.pop(0))


def delivery_result(status="complete", *, reason_code=None, summary=None, pr_url=None, effect_state=None):
    return {
        "status": status,
        "effect_state": effect_state or ("settled" if status in {"complete", "pending"} else "not-applied"),
        "reason_code": reason_code,
        "summary": summary or f"delivery {status}",
        "pr_url": pr_url,
        "head_sha": "a" * 40,
        "checked_head_sha": "a" * 40 if status == "complete" else None,
    }


class EffectGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.journal = self.root / "state" / "effects.sqlite"
        self.registry = self.root / "shared" / "targets.sqlite"

    def tearDown(self):
        self.temporary.cleanup()

    def effect(self, repository="github.com/example/api", branch="feat/task", fingerprint="1" * 64):
        slug = repository.rsplit("/", 1)[-1]
        return {
            "kind": "github-pull-request",
            "change_set": "archive-filter",
            "delivery": {
                "repository": repository,
                "remote": "origin",
                "worktree": str(self.root / slug),
                "baseline": "b" * 40,
                "base_branch": "main",
                "branch": branch,
                "task_files": ["src/change.py", "tests/test_change.py"],
                "expected_fingerprint": fingerprint,
                "commit_message": "Implement change",
                "pr_title": "Implement change",
                "pr_body": "Implements and verifies the requested behavior.",
                "git_write_timeout_seconds": 60,
                "check_timeout_seconds": 0,
            },
        }

    def test_completed_effect_is_returned_without_repeating_the_adapter(self):
        factory = DeliveryFactory([delivery_result(pr_url="https://github.com/example/api/pull/1")])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)

        first = guard.ensure(self.effect())
        second = guard.ensure(self.effect())

        self.assertEqual("complete", first["status"])
        self.assertEqual(first, second)
        self.assertEqual(1, len(factory.specs))
        self.assertEqual(first, guard.inspect(first["effect_id"]))

    def test_runtime_fields_do_not_change_effect_identity(self):
        factory = DeliveryFactory([delivery_result()])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        first_effect = self.effect()
        second_effect = copy.deepcopy(first_effect)
        second_effect["delivery"]["check_timeout_seconds"] = 120
        second_effect["delivery"]["git_write_timeout_seconds"] = 300

        first = guard.ensure(first_effect)
        second = guard.ensure(second_effect)

        self.assertEqual(first["effect_id"], second["effect_id"])
        self.assertEqual(1, len(factory.specs))

    def test_task_file_order_does_not_change_effect_identity(self):
        factory = DeliveryFactory([delivery_result()])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        reordered = self.effect()
        reordered["delivery"]["task_files"].reverse()

        first = guard.ensure(self.effect())
        second = guard.ensure(reordered)

        self.assertEqual(first["effect_id"], second["effect_id"])
        self.assertEqual(1, len(factory.specs))

    def test_exact_approval_is_required_before_intent_or_adapter_execution(self):
        effect = self.effect()
        effect["approval_required"] = True
        factory = DeliveryFactory([delivery_result()])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)

        decision = guard.ensure(effect)
        unknown = guard.inspect(decision["effect_id"])
        rejected = guard.ensure(
            effect,
            approval={"proposal_digest": "0" * 64, "actor": "user", "text": "approve"},
        )
        completed = guard.ensure(
            effect,
            approval={
                "proposal_digest": decision["proposal_digest"],
                "actor": "user",
                "text": "Approve publication of this exact change.",
            },
        )

        self.assertEqual("decision-required", decision["status"])
        self.assertEqual("unknown-effect", unknown["reason_code"])
        self.assertEqual("invalid-effect", rejected["reason_code"])
        self.assertEqual("complete", completed["status"])
        self.assertEqual(1, len(factory.specs))

    def test_a_recorded_approval_cannot_be_replaced_on_a_later_attempt(self):
        effect = self.effect()
        effect["approval_required"] = True
        factory = DeliveryFactory([
            delivery_result("pending", reason_code="required-ci-pending"),
            delivery_result(),
        ])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        decision = guard.ensure(effect)
        first_approval = {
            "proposal_digest": decision["proposal_digest"],
            "actor": "user-a",
            "text": "Approve this proposal.",
        }
        different_approval = {
            "proposal_digest": decision["proposal_digest"],
            "actor": "user-b",
            "text": "I also approve it.",
        }

        pending = guard.ensure(effect, approval=first_approval)
        mismatch = guard.ensure(effect, approval=different_approval)
        replacement = self.effect(fingerprint="2" * 64)
        replacement["approval_required"] = True
        replacement_decision = guard.ensure(replacement)
        replacement_result = guard.ensure(
            replacement,
            approval={
                "proposal_digest": replacement_decision["proposal_digest"],
                "actor": "user-a",
                "text": "Approve the revised proposal.",
            },
        )

        self.assertEqual("pending", pending["status"])
        self.assertEqual("authorization-mismatch", mismatch["reason_code"])
        self.assertEqual("complete", replacement_result["status"])
        self.assertEqual(2, len(factory.specs))

    def test_recorded_approval_authorizes_retry_and_completed_receipt_replay(self):
        effect = self.effect()
        effect["approval_required"] = True
        factory = DeliveryFactory([
            delivery_result("pending", reason_code="required-ci-pending"),
            delivery_result("complete", pr_url="https://github.com/example/api/pull/1"),
        ])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        decision = guard.ensure(effect)

        pending = guard.ensure(
            effect,
            approval={
                "proposal_digest": decision["proposal_digest"],
                "actor": "user",
                "text": "Approve publication of this exact change.",
            },
        )
        completed = guard.ensure(effect)
        replayed = guard.ensure(effect)

        self.assertEqual("pending", pending["status"])
        self.assertEqual("complete", completed["status"])
        self.assertEqual(completed, replayed)
        self.assertEqual(2, len(factory.specs))

    def test_pending_effect_is_reobserved_until_complete(self):
        factory = DeliveryFactory([
            delivery_result("pending", reason_code="required-ci-pending"),
            delivery_result("complete", pr_url="https://github.com/example/api/pull/1"),
        ])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)

        pending = guard.ensure(self.effect())
        completed = guard.ensure(self.effect())

        self.assertEqual("pending", pending["status"])
        self.assertEqual("complete", completed["status"])
        self.assertEqual(2, len(factory.specs))

    def test_crash_leaves_indeterminate_intent_and_identical_retry_reconciles(self):
        factory = DeliveryFactory([KeyboardInterrupt(), delivery_result()])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)

        with self.assertRaises(KeyboardInterrupt):
            guard.ensure(self.effect())
        effect_id = EffectGuard._normalise(self.effect())[1]
        observed = guard.inspect(effect_id)
        completed = guard.ensure(self.effect())

        self.assertEqual("pending", observed["status"])
        self.assertEqual("effect-outcome-indeterminate", observed["reason_code"])
        self.assertEqual(EffectGuard._normalise(self.effect())[0], observed["proposal"])
        self.assertEqual("complete", completed["status"])

    def test_real_delivery_adapter_adopts_pr_created_before_a_crash(self):
        repository = self.root / "real-repository"
        repository.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", *args],
                cwd=repository,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()

        git("init", "-q", "-b", "main")
        git("config", "user.name", "Tests")
        git("config", "user.email", "tests@example.test")
        (repository / "README.md").write_text("baseline\n")
        git("add", "README.md")
        git("commit", "-qm", "initial")
        baseline = git("rev-parse", "HEAD")
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git("remote", "add", "origin", "git@github.com:example/task.git")
        git("push", "-q", str(remote), "main")
        git("switch", "-qc", "feat/test")
        (repository / "feature.txt").write_text("implemented\n")

        forge = FakeGitHub(repository)
        forge.crash_after = "pr-create"
        guard = EffectGuard(
            self.journal,
            registry=self.registry,
            delivery_factory=lambda spec: delivery_tools.Delivery(spec, run_process=forge),
        )
        effect = {
            "kind": "github-pull-request",
            "delivery": {
                "repository": "github.com/example/task",
                "remote": "origin",
                "worktree": str(repository),
                "baseline": baseline,
                "base_branch": "main",
                "branch": "feat/test",
                "task_files": ["feature.txt"],
                "expected_fingerprint": delivery_tools.content_fingerprint(repository),
                "commit_message": "feat: implement task",
                "pr_title": "Implement task",
                "pr_body": "Tested change.",
                "check_timeout_seconds": 0,
            },
        }

        with self.assertRaises(KeyboardInterrupt):
            guard.ensure(effect)
        effect_id = EffectGuard._normalise(effect)[1]
        self.assertEqual("pending", guard.inspect(effect_id)["status"])

        recovered = guard.ensure(effect)

        self.assertEqual("complete", recovered["status"], recovered)
        self.assertEqual(1, forge.create_count)

    def test_real_delivery_keeps_target_claim_when_pr_observation_is_malformed(self):
        repository = self.root / "malformed-observation-repository"
        repository.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", *args],
                cwd=repository,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()

        git("init", "-q", "-b", "main")
        git("config", "user.name", "Tests")
        git("config", "user.email", "tests@example.test")
        (repository / "README.md").write_text("baseline\n")
        git("add", "README.md")
        git("commit", "-qm", "initial")
        baseline = git("rev-parse", "HEAD")
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git("remote", "add", "origin", "git@github.com:example/task.git")
        git("push", "-q", str(remote), "main")
        git("switch", "-qc", "feat/test")
        (repository / "feature.txt").write_text("implemented\n")

        forge = FakeGitHub(repository)
        malformed = True

        def run_process(command, cwd, timeout):
            result = forge(command, cwd, timeout)
            if malformed and command[:3] == ["gh", "pr", "view"] and forge.create_count:
                return subprocess.CompletedProcess(command, 0, "not-json", "")
            return result

        guard = EffectGuard(
            self.journal,
            registry=self.registry,
            delivery_factory=lambda spec: delivery_tools.Delivery(spec, run_process=run_process),
        )
        effect = {
            "kind": "github-pull-request",
            "delivery": {
                "repository": "github.com/example/task",
                "remote": "origin",
                "worktree": str(repository),
                "baseline": baseline,
                "base_branch": "main",
                "branch": "feat/test",
                "task_files": ["feature.txt"],
                "expected_fingerprint": delivery_tools.content_fingerprint(repository),
                "commit_message": "feat: implement task",
                "pr_title": "Implement task",
                "pr_body": "Tested change.",
                "check_timeout_seconds": 0,
            },
        }

        uncertain = guard.ensure(effect)
        revised = copy.deepcopy(effect)
        revised["delivery"]["pr_title"] = "Revised task"
        conflict = guard.ensure(revised)
        with sqlite3.connect(self.registry) as connection:
            claims = connection.execute("SELECT COUNT(*) FROM target_claims").fetchone()[0]

        self.assertEqual("pending", uncertain["status"])
        self.assertEqual("effect-outcome-indeterminate", uncertain["reason_code"])
        self.assertEqual("target-conflict", conflict["reason_code"])
        self.assertEqual(1, claims)
        self.assertEqual(1, forge.create_count)

        malformed = False
        recovered = guard.ensure(effect)

        self.assertEqual("complete", recovered["status"], recovered)
        self.assertEqual(1, forge.create_count)

    def test_indeterminate_effect_blocks_a_different_effect_on_the_same_target(self):
        factory = DeliveryFactory([KeyboardInterrupt(), delivery_result(), delivery_result()])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        original = self.effect(fingerprint="1" * 64)
        replacement = self.effect(fingerprint="2" * 64)

        with self.assertRaises(KeyboardInterrupt):
            guard.ensure(original)
        conflict = guard.ensure(replacement)
        recovered = guard.ensure(original)
        replacement_after_recovery = guard.ensure(replacement)

        self.assertEqual("target-conflict", conflict["reason_code"])
        self.assertEqual("complete", recovered["status"])
        self.assertEqual("complete", replacement_after_recovery["status"])

    def test_settled_indeterminate_observation_still_blocks_a_revised_effect(self):
        factory = DeliveryFactory([
            delivery_result(
                "blocked",
                reason_code="indeterminate-delivery-evidence",
                effect_state="indeterminate",
            ),
            delivery_result(),
            delivery_result(),
        ])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        original = self.effect(fingerprint="1" * 64)
        replacement = self.effect(fingerprint="2" * 64)

        uncertain = guard.ensure(original)
        conflict = guard.ensure(replacement)
        recovered = guard.ensure(original)
        replacement_after_recovery = guard.ensure(replacement)

        self.assertEqual("pending", uncertain["status"])
        self.assertEqual("effect-outcome-indeterminate", uncertain["reason_code"])
        self.assertEqual("target-conflict", conflict["reason_code"])
        self.assertEqual("complete", recovered["status"])
        self.assertEqual("complete", replacement_after_recovery["status"])

    def test_unexpected_adapter_error_is_a_durable_indeterminate_outcome(self):
        factory = DeliveryFactory([RuntimeError("adapter failed"), delivery_result(), delivery_result()])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        original = self.effect(fingerprint="1" * 64)
        replacement = self.effect(fingerprint="2" * 64)

        uncertain = guard.ensure(original)
        conflict = guard.ensure(replacement)
        recovered = guard.ensure(original)

        self.assertEqual("pending", uncertain["status"])
        self.assertEqual("effect-outcome-indeterminate", uncertain["reason_code"])
        self.assertEqual("target-conflict", conflict["reason_code"])
        self.assertEqual("complete", recovered["status"])

    def test_shared_registry_blocks_the_same_target_across_task_journals(self):
        first_factory = DeliveryFactory([KeyboardInterrupt(), delivery_result()])
        second_factory = DeliveryFactory([delivery_result()])
        first = EffectGuard(
            self.root / "task-a" / "effects.sqlite",
            registry=self.registry,
            delivery_factory=first_factory,
        )
        second = EffectGuard(
            self.root / "task-b" / "effects.sqlite",
            registry=self.registry,
            delivery_factory=second_factory,
        )
        original = self.effect(fingerprint="1" * 64)
        replacement = self.effect(fingerprint="2" * 64)

        with self.assertRaises(KeyboardInterrupt):
            first.ensure(original)
        conflict = second.ensure(replacement)
        recovered = first.ensure(original)
        completed = second.ensure(replacement)

        self.assertEqual("target-conflict", conflict["reason_code"])
        self.assertEqual(EffectGuard._normalise(original)[1], conflict["blocking_effect_id"])
        self.assertEqual(str(first.journal), conflict["blocking_journal"])
        self.assertEqual("complete", recovered["status"])
        self.assertEqual("complete", completed["status"])

    def test_concurrent_identical_call_is_stopped_before_adapter_execution(self):
        started = threading.Event()
        release = threading.Event()
        results = []
        test_case = self

        class BlockingFactory:
            calls = 0

            def __call__(self, spec):
                del spec
                self.calls += 1

                class Delivery:
                    @staticmethod
                    def run():
                        started.set()
                        test_case.assertTrue(release.wait(5))
                        return delivery_result()

                return Delivery()

        factory = BlockingFactory()
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        thread = threading.Thread(target=lambda: results.append(guard.ensure(self.effect())))
        thread.start()
        self.assertTrue(started.wait(5))

        concurrent = guard.ensure(self.effect())
        release.set()
        thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertEqual("target-busy", concurrent["reason_code"])
        self.assertEqual("complete", results[0]["status"])
        self.assertEqual(1, factory.calls)

    def test_settled_failure_releases_target_for_a_revised_effect(self):
        factory = DeliveryFactory([
            delivery_result("blocked", reason_code="validated-content-changed"),
            delivery_result(),
        ])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)

        stopped = guard.ensure(self.effect(fingerprint="1" * 64))
        revised = guard.ensure(self.effect(fingerprint="2" * 64))

        self.assertEqual("stopped", stopped["status"])
        self.assertEqual("complete", revised["status"])

    def test_multi_repository_change_set_settles_each_repository_independently(self):
        factory = DeliveryFactory([
            delivery_result("complete", pr_url="https://github.com/example/api/pull/1"),
            delivery_result("blocked", reason_code="permission-denied"),
        ])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)

        api = guard.ensure(self.effect(repository="github.com/example/api", branch="feat/api"))
        web = guard.ensure(self.effect(repository="github.com/example/web", branch="feat/web"))

        self.assertEqual("complete", api["status"])
        self.assertEqual("stopped", web["status"])
        self.assertNotEqual(api["effect_id"], web["effect_id"])
        self.assertEqual("complete", guard.inspect(api["effect_id"])["status"])
        self.assertEqual("stopped", guard.inspect(web["effect_id"])["status"])

    def test_guard_owns_runtime_evidence_locations(self):
        factory = DeliveryFactory([delivery_result()])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)
        effect = self.effect()
        effect["delivery"].update(
            log_dir="/untrusted/logs",
            run_id="caller-controlled",
            pr_intent_path="/untrusted/intent.json",
        )

        result = guard.ensure(effect)

        spec = factory.specs[0]
        self.assertEqual(result["effect_id"], spec["run_id"])
        self.assertTrue(Path(spec["log_dir"]).is_relative_to(self.journal.parent))
        self.assertTrue(Path(spec["pr_intent_path"]).is_relative_to(self.journal.parent))

    def test_unknown_kind_stops_without_creating_a_journal(self):
        factory = DeliveryFactory([])
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=factory)

        result = guard.ensure({"kind": "shell-command", "delivery": {}})

        self.assertEqual("stopped", result["status"])
        self.assertEqual("invalid-effect", result["reason_code"])
        self.assertFalse(self.journal.exists())

    def test_unrecognised_delivery_field_is_not_journaled(self):
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=DeliveryFactory([]))
        effect = self.effect()
        effect["delivery"]["access_token"] = "must-not-be-stored"

        result = guard.ensure(effect)

        self.assertEqual("invalid-effect", result["reason_code"])
        self.assertFalse(self.journal.exists())

    def test_inspect_rejects_a_tampered_persisted_proposal(self):
        guard = EffectGuard(
            self.journal,
            registry=self.registry,
            delivery_factory=DeliveryFactory([delivery_result("pending")]),
        )
        pending = guard.ensure(self.effect())
        with sqlite3.connect(self.journal) as connection:
            connection.execute(
                "UPDATE effects SET proposal = ? WHERE effect_id = ?",
                ('{"kind":"github-pull-request","delivery":{}}', pending["effect_id"]),
            )

        inspected = guard.inspect(pending["effect_id"])

        self.assertEqual("journal-integrity-violation", inspected["reason_code"])

    def test_inspect_of_unknown_effect_is_read_only(self):
        guard = EffectGuard(self.journal, registry=self.registry, delivery_factory=DeliveryFactory([]))

        result = guard.inspect("1" * 64)

        self.assertEqual("unknown-effect", result["reason_code"])
        self.assertFalse(self.journal.exists())
        self.assertFalse(self.journal.parent.exists())


if __name__ == "__main__":
    unittest.main()
