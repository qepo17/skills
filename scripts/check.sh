#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

python3 scripts/validate_repository.py

# Both npx skills installations must remain self-contained and ship the same helper.
cmp skills/end-to-end-development/scripts/delivery_tools.py \
  skills/fast-end-to-end-development/scripts/delivery_tools.py
cp -R skills/fast-end-to-end-development "$TMP_DIR/fast-only"
git init -q "$TMP_DIR/standalone-repo"
printf 'standalone fingerprint fixture\n' >"$TMP_DIR/standalone-repo/example.txt"
git -C "$TMP_DIR/standalone-repo" status --porcelain >"$TMP_DIR/before-status.txt"
(
  cd "$TMP_DIR"
  PYTHONDONTWRITEBYTECODE=1 python3 fast-only/scripts/delivery_tools.py --help >helper-help.txt
  PYTHONDONTWRITEBYTECODE=1 python3 fast-only/scripts/delivery_tools.py fingerprint "$TMP_DIR/standalone-repo" >fingerprint.txt
)
grep -Eq '^[0-9a-f]{64}$' "$TMP_DIR/fingerprint.txt"
git -C "$TMP_DIR/standalone-repo" status --porcelain >"$TMP_DIR/after-status.txt"
cmp "$TMP_DIR/before-status.txt" "$TMP_DIR/after-status.txt"
# Exercise default and opt-in lifecycles with no canonical skill/dependencies present.
mkdir -p "$TMP_DIR/fast-only/tests"
cp skills/end-to-end-development/tests/test_delivery_tools.py "$TMP_DIR/fast-only/tests/"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$TMP_DIR/fast-only/tests" -q

PYTHONDONTWRITEBYTECODE=1 UV_PROJECT_ENVIRONMENT="$TMP_DIR/e2e-venv" \
  uv run --project skills/end-to-end-development --locked \
  python -m unittest discover -s skills/end-to-end-development/tests -v

cat >"$TMP_DIR/explainer.json" <<'JSON'
{
  "title": "Renderer smoke test",
  "summary": "<script>alert(1)</script>",
  "repository": "qepo17/skills",
  "pr_url": "https://github.com/qepo17/skills/pull/1",
  "branch": "test",
  "base": "main",
  "acceptance_criteria": ["Render a self-contained explainer"],
  "plan": ["Render sanitized artifacts"],
  "implementation": {"changed_files": ["skills/example/SKILL.md"], "notes": []},
  "validation": [{"command": "./scripts/check.sh", "status": "passed", "exit_code": 0}],
  "review": {"status": "complete", "findings": []},
  "revision": {"status": "complete", "resolved_findings": [], "notes": []},
  "delivery": {"status": "created", "commit": "0123456", "checks": "passed"},
  "risks": [],
  "remaining_notes": []
}
JSON

PYTHONPYCACHEPREFIX="$TMP_DIR/pycache" \
  python3 skills/fast-end-to-end-development/scripts/render_pr_explainer.py \
  --input "$TMP_DIR/explainer.json" \
  --output "$TMP_DIR/explainer.html"
grep -Fq '&lt;script&gt;alert(1)&lt;/script&gt;' "$TMP_DIR/explainer.html"
! grep -Fq '<script>alert(1)</script>' "$TMP_DIR/explainer.html"

npx --yes skills@1.5.23 add . --list >"$TMP_DIR/skills-list.txt"
grep -Fq 'end-to-end-development' "$TMP_DIR/skills-list.txt"
grep -Fq 'fast-end-to-end-development' "$TMP_DIR/skills-list.txt"
grep -Fq 'simple-code' "$TMP_DIR/skills-list.txt"
grep -Fq 'idea-to-ticket' "$TMP_DIR/skills-list.txt"

# Validate the idea skill with no sibling skills available.
cp -R skills/idea-to-ticket "$TMP_DIR/idea-to-ticket"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT/scripts" "$TMP_DIR/idea-to-ticket" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import validate_repository

skill_dir = Path(sys.argv[2])
validate_repository.ROOT = skill_dir.parent
errors = []
validate_repository.validate_skill(skill_dir, errors)
if errors:
    raise SystemExit("\n".join(errors))
print("Validated standalone idea-to-ticket skill.")
PY
npx --yes skills@1.5.23 add "$TMP_DIR/idea-to-ticket" --list >"$TMP_DIR/idea-skills-list.txt"
grep -Fq 'idea-to-ticket' "$TMP_DIR/idea-skills-list.txt"
! grep -Eq 'end-to-end-development|simple-code' "$TMP_DIR/idea-skills-list.txt"

printf 'All repository checks passed.\n'
