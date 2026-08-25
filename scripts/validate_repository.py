#!/usr/bin/env python3
"""Validate the installable Agent Skills catalog without third-party packages."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
EXPECTED_SKILLS = {
    "end-to-end-development",
    "fast-end-to-end-development",
}
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FORBIDDEN_PARTS = {".pytest_cache", ".venv", "__pycache__"}


def scalar(frontmatter: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    if not match:
        return None
    raw = match.group(1)
    if raw.startswith('"') and raw.endswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, str) else None
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw


def frontmatter(skill_md: Path) -> str | None:
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", text, re.DOTALL)
    return match.group(1) if match else None


def tracked_and_unignored_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def validate_skill(skill_dir: Path, errors: list[str]) -> None:
    skill_md = skill_dir / "SKILL.md"
    data = frontmatter(skill_md)
    if data is None:
        errors.append(f"{skill_md.relative_to(ROOT)}: missing YAML frontmatter")
        return

    name = scalar(data, "name")
    description = scalar(data, "description")
    compatibility = scalar(data, "compatibility")

    if name != skill_dir.name:
        errors.append(
            f"{skill_md.relative_to(ROOT)}: name {name!r} must match parent directory {skill_dir.name!r}"
        )
    if not name or len(name) > 64 or not NAME_PATTERN.fullmatch(name):
        errors.append(f"{skill_md.relative_to(ROOT)}: invalid Agent Skills name {name!r}")
    if not description or len(description) > 1024:
        errors.append(
            f"{skill_md.relative_to(ROOT)}: description must contain 1-1024 characters"
        )
    if compatibility is not None and not 1 <= len(compatibility) <= 500:
        errors.append(
            f"{skill_md.relative_to(ROOT)}: compatibility must contain 1-500 characters"
        )

    text = skill_md.read_text(encoding="utf-8")
    if len(text.splitlines()) > 500:
        errors.append(f"{skill_md.relative_to(ROOT)}: keep SKILL.md under 500 lines")

    for target in LINK_PATTERN.findall(text):
        target = target.strip().split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (skill_dir / target).resolve()
        try:
            resolved.relative_to(skill_dir.resolve())
        except ValueError:
            errors.append(
                f"{skill_md.relative_to(ROOT)}: relative link escapes the skill directory: {target}"
            )
            continue
        if not resolved.exists():
            errors.append(
                f"{skill_md.relative_to(ROOT)}: relative link does not exist: {target}"
            )

    openai_yaml = skill_dir / "agents" / "openai.yaml"
    if not openai_yaml.is_file():
        errors.append(f"{openai_yaml.relative_to(ROOT)}: missing product metadata")
    elif f"${skill_dir.name}" not in openai_yaml.read_text(encoding="utf-8"):
        errors.append(
            f"{openai_yaml.relative_to(ROOT)}: default_prompt must mention ${skill_dir.name}"
        )


def main() -> int:
    errors: list[str] = []
    if (ROOT / "SKILL.md").exists():
        errors.append("Do not add a root SKILL.md; it shadows catalog discovery")

    discovered = {
        path.parent.name
        for path in SKILLS_ROOT.glob("*/SKILL.md")
        if path.is_file()
    }
    if discovered != EXPECTED_SKILLS:
        errors.append(
            f"Expected skills {sorted(EXPECTED_SKILLS)}, found {sorted(discovered)}"
        )

    all_skill_files = {
        path.relative_to(SKILLS_ROOT).as_posix()
        for path in SKILLS_ROOT.rglob("SKILL.md")
    }
    expected_skill_files = {f"{name}/SKILL.md" for name in EXPECTED_SKILLS}
    if all_skill_files != expected_skill_files:
        errors.append(
            "Unexpected nested or missing SKILL.md files: "
            f"{sorted(all_skill_files ^ expected_skill_files)}"
        )

    for name in sorted(EXPECTED_SKILLS):
        skill_dir = SKILLS_ROOT / name
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            validate_skill(skill_dir, errors)

    for path in tracked_and_unignored_files():
        if any(part in FORBIDDEN_PARTS for part in path.parts) or path.suffix in {
            ".pyc",
            ".pyo",
        }:
            errors.append(f"Generated Python file is not ignored: {path}")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(EXPECTED_SKILLS)} installable skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
