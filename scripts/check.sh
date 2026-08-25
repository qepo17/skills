#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

python3 scripts/validate_repository.py

UV_PROJECT_ENVIRONMENT="$TMP_DIR/e2e-venv" \
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

printf 'All repository checks passed.\n'
