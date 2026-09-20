#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

python3 scripts/validate_repository.py

# The development skill must remain self-contained and standard-library only.
cp -R skills/end-to-end-development "$TMP_DIR/end-to-end-development"
git init -q "$TMP_DIR/standalone-repo"
printf 'standalone fingerprint fixture\n' >"$TMP_DIR/standalone-repo/example.txt"
git -C "$TMP_DIR/standalone-repo" status --porcelain >"$TMP_DIR/before-status.txt"
(
  cd "$TMP_DIR"
  PYTHONDONTWRITEBYTECODE=1 python3 end-to-end-development/scripts/effect_guard.py --help >helper-help.txt
  PYTHONDONTWRITEBYTECODE=1 python3 end-to-end-development/scripts/effect_guard.py \
    fingerprint "$TMP_DIR/standalone-repo" >fingerprint.txt
)
grep -Eq '^[0-9a-f]{64}$' "$TMP_DIR/fingerprint.txt"
git -C "$TMP_DIR/standalone-repo" status --porcelain >"$TMP_DIR/after-status.txt"
cmp "$TMP_DIR/before-status.txt" "$TMP_DIR/after-status.txt"

PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s skills/end-to-end-development/tests -v

# The removed workflow runtime must not return through an import or dependency.
! rg -n 'from langgraph|import langgraph|WorkflowEngine|workflow_engine' \
  skills/end-to-end-development README.md CONTRIBUTING.md

npx --yes skills@1.5.23 add . --list >"$TMP_DIR/skills-list.txt"
grep -Fq 'end-to-end-development' "$TMP_DIR/skills-list.txt"
! grep -Fq 'fast-end-to-end-development' "$TMP_DIR/skills-list.txt"
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
