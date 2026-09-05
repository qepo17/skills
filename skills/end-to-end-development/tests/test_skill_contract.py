from __future__ import annotations

import ast
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
import artifact_guard  # noqa: E402
import workflow_tools  # noqa: E402


class SkillValidationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (SKILL_DIR / "SKILL.md").read_text()
        self.tree = ast.parse((SKILL_DIR / "scripts" / "artifact_guard.py").read_text())

    def test_every_enforced_text_limit_is_visible_in_skill(self) -> None:
        documented = {}
        for fields, limit in re.findall(r"^\| (.+) \| (\d+) characters \|$", self.skill, re.MULTILINE):
            documented.update({name: int(limit) for name in re.findall(r"`([a-z_]+)`", fields)})
        enforced = set()
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "string":
                continue
            limits = [kw.value for kw in node.keywords if kw.arg == "max_length"]
            if not limits:
                continue
            location = node.args[1]
            suffix = location.value if isinstance(location, ast.Constant) else location.values[-1].value
            enforced.add((suffix.rsplit(".", 1)[-1], ast.literal_eval(limits[0])))
        self.assertTrue(enforced)
        for field, limit in sorted(enforced):
            with self.subTest(field=field):
                self.assertEqual(limit, documented.get(field), "Document the exact field limit in SKILL.md")

    def test_every_artifact_byte_limit_is_visible_in_skill(self) -> None:
        documented = {kind: int(kib) * 1024 for kind, kib in re.findall(
            r"^\| `([a-z-]+)` \| (\d+) KiB \|$", self.skill, re.MULTILINE,
        )}
        self.assertEqual(artifact_guard.MAX_BYTES, documented)

    def test_field_inventories_cover_required_and_conditional_top_level_fields(self) -> None:
        rows = dict(re.findall(r"^\| `([a-z-]+)` \| Required: (.+) \|$", self.skill, re.MULTILINE))
        self.assertEqual(set(artifact_guard.VALIDATORS), set(rows))
        for kind in artifact_guard.VALIDATORS:
            function = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef)
                            and node.name == f"validate_{kind.replace('-', '_')}")
            required = {node.args[1].value for node in ast.walk(function)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "field"
                        and len(node.args) == 3 and isinstance(node.args[0], ast.Name) and node.args[0].id == "data"
                        and isinstance(node.args[1], ast.Constant) and isinstance(node.args[2], ast.Constant)
                        and node.args[2].value == "$"}
            conditional = {node.args[0].value for node in ast.walk(function)
                           if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                           and node.func.value.id == "data" and node.args
                           and isinstance(node.args[0], ast.Constant)}
            with self.subTest(kind=kind):
                documented = set(re.findall(r"`([a-z_][a-z0-9_]*)`", rows.get(kind, "")))
                missing = (required | conditional) - documented
                self.assertFalse(missing, f"Missing {kind} fields in SKILL.md: {missing}")
        for control in ("contract_revision", "plan_revision", "contract_required", "design_challenge_policy",
                        "revision_basis", "verify_only", "check_timeout_seconds"):
            self.assertIn(f"`{control}`", rows["assignment"])

    def test_nested_required_and_conditional_field_names_include_helper_validators(self) -> None:
        # A structural drift guard, not a substitute for reviewing semantic rules.
        contract = self.skill.split("## Validation rules", 1)[1].split("## Non-negotiable invariants", 1)[0]
        documented = set(re.findall(r"`([a-z_][a-z0-9_]*)`", contract))
        for function in self.tree.body:
            if not isinstance(function, ast.FunctionDef) or not function.name.startswith("validate_"):
                continue
            nested = {node.args[1].value for node in ast.walk(function)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "field"
                      and len(node.args) == 3 and isinstance(node.args[1], ast.Constant)}
            conditional = {node.args[0].value for node in ast.walk(function)
                           if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant)
                           and isinstance(node.args[0].value, str)}
            with self.subTest(validator=function.name):
                missing = (nested | conditional) - documented
                self.assertFalse(missing, f"Missing field names: {missing}")

    def test_high_impact_worker_rules_do_not_live_only_in_schema_reminders(self) -> None:
        contract = self.skill.split("## Validation rules", 1)[1].split("## Non-negotiable invariants", 1)[0]
        for rule in ("contract/plan conformance and complexity drift", "audit the baseline diff and untracked files",
                     "preserve pre-existing changes", "commit only task files", "all semantic fields",
                     "normalization pending", "before acceptance"):
            with self.subTest(rule=rule):
                self.assertIn(rule, contract)

    def test_validation_vocabularies_and_all_schema_entrypoints_are_upfront(self) -> None:
        self.assertIn("## Validation rules", self.skill)
        contract = self.skill.split("## Validation rules", 1)[1].split("## Non-negotiable invariants", 1)[0]
        for name in ("BLOCKER_KINDS", "DECISION_KINDS", "RISK_FLAGS", "HIGH_COST_MECHANISM_TYPES", "DESIGN_FINDING_CATEGORIES"):
            for value in getattr(artifact_guard, name):
                with self.subTest(vocabulary=name, value=value):
                    self.assertIn(f"`{value}`", contract)
        for schema in (SKILL_DIR / "schemas").glob("*.md"):
            with self.subTest(schema=schema.name):
                self.assertIn("../SKILL.md#validation-rules", schema.read_text())
        self.assertLessEqual(len(self.skill.splitlines()), 500)

    def test_worker_prompt_loads_installed_skill_before_work_without_new_assignment_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / "installed skill"
            validator = installed / "scripts" / "artifact_guard.py"
            validator.parent.mkdir(parents=True)
            validator.touch()
            (installed / "SKILL.md").write_text(self.skill)
            assignment_path = root / "assignment.json"
            assignment_path.write_text(json.dumps({"validator_path": str(validator)}))
            prompt = workflow_tools._worker_prompt(assignment_path)
            self.assertIn(str(installed / "SKILL.md"), prompt)
            self.assertIn("Validation rules", prompt)
            self.assertIn("before", prompt.lower())
            self.assertIn("coordinator-only", prompt)
            self.assertNotIn("not the full coordinator contract", prompt)
            self.assertLess(prompt.index("SKILL.md"), prompt.index("initialize"))
            self.assertIn("all semantic fields", prompt)
            self.assertIn("normalization-dependent result/review skeletons", prompt)
            self.assertIn("normalization pending instead of validating known placeholders", prompt)
            self.assertIn("Do not spawn nested agents", prompt)


if __name__ == "__main__":
    unittest.main()
