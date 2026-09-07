from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import artifact_guard


def intake_fixture() -> dict:
    return {
        "sources": [{"reference": "Jira APP-123, supplied snapshot", "text": "AC-001: Hide archived items."}],
        "codebase_evidence": ["src/items.py:list_items at baseline abc123 includes archived rows."],
        "recommendations": ["Extend the existing filter and tests rather than add a service."],
        "question_limit": 10,
        "questions": [],
    }


class SourceIntakeTests(unittest.TestCase):
    def test_zero_questions_and_lower_user_limits_are_valid(self) -> None:
        for limit in (0, 1, 3, 10):
            with self.subTest(limit=limit):
                intake = intake_fixture()
                intake["question_limit"] = limit
                artifact_guard.validate_intake(intake)
                intake["questions"] = [{"question": "One choice?", "resolution": "User: keep existing behavior."}] * limit
                original = copy.deepcopy(intake)
                artifact_guard.validate_intake(intake)
                self.assertEqual(original, intake)
                intake["questions"].append({"question": "A follow-up?", "resolution": "User answer."})
                with self.assertRaisesRegex(artifact_guard.ValidationError, "question limit"):
                    artifact_guard.validate_intake(intake)

    def test_historical_answers_survive_no_interview_or_lowered_cap(self) -> None:
        for limit, prior in ((0, 2), (1, 2), (10, 9), (10, 12)):
            with self.subTest(limit=limit, prior=prior):
                intake = intake_fixture()
                intake["question_limit"] = limit
                intake["prior_question_count"] = prior
                intake["questions"] = [{"question": f"Upstream question {i}?", "resolution": "User answer."} for i in range(prior)]
                original = copy.deepcopy(intake)
                artifact_guard.validate_intake(intake)
                self.assertEqual(original, intake)
                remaining = max(0, limit - prior)
                intake["questions"].extend([{"question": "New material choice?", "resolution": "User answer."}] * remaining)
                artifact_guard.validate_intake(intake)
                intake["questions"].append({"question": "Over-budget follow-up?", "resolution": "User answer."})
                with self.assertRaisesRegex(artifact_guard.ValidationError, "question limit"):
                    artifact_guard.validate_intake(intake)

    def test_prior_count_cannot_invent_history_or_use_non_integer_values(self) -> None:
        for prior in (-1, True, False, "0", 1.5, 1):
            with self.subTest(prior=prior):
                intake = intake_fixture()
                intake["prior_question_count"] = prior
                with self.assertRaisesRegex(artifact_guard.ValidationError, "prior_question_count"):
                    artifact_guard.validate_intake(intake)

    def test_invalid_caps_cannot_bypass_the_budget(self) -> None:
        for limit in (-1, 11, True, False, 1.5, "10", None):
            with self.subTest(limit=limit):
                intake = intake_fixture()
                intake["question_limit"] = limit
                with self.assertRaisesRegex(artifact_guard.ValidationError, "question_limit"):
                    artifact_guard.validate_intake(intake)

    def test_intake_must_preserve_source_and_resolved_question_evidence(self) -> None:
        invalid_changes = [
            ("sources", []),
            ("sources", [{"reference": "APP-123", "text": ""}]),
            ("sources", [{"reference": "", "text": "Missing source identity"}]),
            ("sources", [{"reference": "APP-123", "text": "x" * 12001}]),
            ("questions", [{"question": "Important choice?", "resolution": ""}]),
            ("questions", [{"question": "Important choice?", "resolution": None}]),
            ("questions", [{"question": "", "resolution": "User answer"}]),
            ("questions", [{"question": "Important choice?"}]),
            ("questions", {"count": 0}),
            ("codebase_evidence", [False]),
            ("recommendations", ["same", "same"]),
        ]
        for field, value in invalid_changes:
            with self.subTest(field=field, value=value):
                intake = intake_fixture()
                intake[field] = value
                with self.assertRaises(artifact_guard.ValidationError):
                    artifact_guard.validate_intake(intake)
        for field in intake_fixture():
            with self.subTest(missing=field):
                intake = intake_fixture()
                del intake[field]
                with self.assertRaises(artifact_guard.ValidationError):
                    artifact_guard.validate_intake(intake)

    def test_requirements_validate_optional_intake_on_artifact_read(self) -> None:
        requirements = {
            "schema_version": 1, "artifact_kind": "requirements", "run_id": "intake-test",
            "created_at": "2026-09-07T10:00:00Z",
            "requirements": [{"id": "REQ-001", "source_text": "Hide archived items.",
                              "acceptance_criteria": ["AC-001: Archived items are absent."],
                              "repository_ids": ["api"]}],
            "constraints": [],
        }
        artifact_guard.validate_requirements(requirements)
        requirements["intake"] = intake_fixture()
        artifact_guard.validate_requirements(requirements)
        requirements["intake"]["question_limit"] = 11
        with self.assertRaises(artifact_guard.ValidationError):
            artifact_guard.validate_requirements(requirements)
        requirements["intake"] = intake_fixture()
        requirements["intake"]["codebase_evidence"] = ["x" * (64 * 1024)]
        with self.assertRaisesRegex(artifact_guard.ValidationError, "64 KiB"):
            artifact_guard.validate_requirements(requirements)


if __name__ == "__main__":
    unittest.main()
