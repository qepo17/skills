"""Read-only source-transition proof for explicit rejected-packet recovery.

Only a conflict-free, forward base update plus explicitly listed test repairs is
supported. No Git ref, index, worktree, or workflow evidence is rewritten here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                            capture_output=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        raise ValueError(f"source transition Git inspection failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def tree_fingerprint(tree: str) -> str:
    return hashlib.sha256(b"end-to-end-development-content-v3\0" + tree.encode()).hexdigest()


def tree_entries(root: Path, tree: str) -> dict[str, tuple[str, str]]:
    entries = {}
    for row in git(root, "ls-tree", "-rz", tree).split(b"\0"):
        if not row:
            continue
        metadata, path = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        if kind != "blob":
            raise ValueError("external repair does not support submodules")
        entries[path.decode()] = (mode, oid)
    return entries


def validate_transition(root: Path, transition: dict[str, Any], original: dict[str, Any],
                        repository: dict[str, Any], state: dict[str, str]) -> list[str]:
    for marker in ("index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        path = Path(git(root, "rev-parse", "--git-path", marker).decode().strip())
        if (path if path.is_absolute() else root / path).exists():
            raise ValueError("source transition requires settled Git operations and no index lock")
    required = {"before_head", "before_tree", "after_head", "after_tree", "target_ref", "repair_paths"}
    if not isinstance(transition, dict) or set(transition) != required:
        raise ValueError("source transition requires exact before/after HEAD/tree, target_ref and repair_paths")
    for name in ("before_head", "before_tree", "after_head", "after_tree"):
        oid = transition[name]
        if not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
            raise ValueError(f"invalid source transition {name}")
        kind = "commit" if name.endswith("head") else "tree"
        if git(root, "cat-file", "-t", oid).decode().strip() != kind:
            raise ValueError(f"source transition {name} must identify a {kind}")
    if (transition["before_head"] != original["git"]["head"]
            or transition["before_head"] != repository["baseline"]
            or tree_fingerprint(transition["before_tree"]) != original["tree_fingerprint"]):
        raise ValueError("before tree/HEAD must prove the rejected evidence, not refreshed hashes")
    if (transition["after_head"] != state["head"] or state["branch"] != repository["branch"]
            or tree_fingerprint(transition["after_tree"]) != state["fingerprint"]
            or git(root, "diff", "--cached", "--name-only").strip()):
        raise ValueError("current source/HEAD/branch/index differs from the reviewed transition")
    target = transition["target_ref"]
    if not isinstance(target, str) or not re.fullmatch(r"refs/remotes/[A-Za-z0-9._/-]+", target):
        raise ValueError("target_ref must be an explicit remote-tracking ref")
    if git(root, "rev-parse", "--verify", target).decode().strip() != transition["after_head"]:
        raise ValueError("reviewed rebase target moved")
    git(root, "merge-base", "--is-ancestor", transition["before_head"], transition["after_head"])
    repairs = transition["repair_paths"]
    if (not isinstance(repairs, list) or not repairs or any(not isinstance(p, str) for p in repairs)
            or repairs != sorted(set(repairs))):
        raise ValueError("repair_paths must be a nonempty sorted unique test-file allowlist")
    for name in repairs:
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts or ".git" in path.parts
                or not (name.endswith("_test.go") or path.name.startswith("test_") and name.endswith(".py")
                        or re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", name))):
            raise ValueError("external repairs are limited to explicitly authorized test files")
    before, after, old_base, new_base = [tree_entries(root, transition[name])
                                        for name in ("before_tree", "after_tree", "before_head", "after_head")]
    changed_repairs = set()
    for name in sorted(before.keys() | after.keys() | old_base.keys() | new_base.keys()):
        local, old, new, actual = before.get(name), old_base.get(name), new_base.get(name), after.get(name)
        expected = local if old == new else new if local == old else None
        if old != new and local != old:
            # Overlapping base updates must reproduce a clean three-way merge;
            # authorization of a rebase is not permission for arbitrary resolution.
            if not all(item and item[0] == "100644" for item in (local, old, new)):
                raise ValueError(f"unsupported rebase overlap at {name}; normal replanning required")
            with tempfile.TemporaryDirectory(prefix="e2e-merge-proof-") as directory:
                paths = [Path(directory) / part for part in ("local", "base", "upstream")]
                for path, item in zip(paths, (local, old, new), strict=True):
                    path.write_bytes(git(root, "cat-file", "blob", item[1]))
                merge = subprocess.run(["git", "merge-file", "-p", *map(str, paths)], capture_output=True)
                if merge.returncode:
                    raise ValueError(f"nontrivial rebase resolution at {name}; normal replanning required")
                # Compare bytes directly, avoiding writes to the repository object store.
                if name in repairs:
                    raise ValueError(f"repair overlaps a rebase merge at {name}; separate review required")
                if not actual or actual[0] != "100644" or git(root, "cat-file", "blob", actual[1]) != merge.stdout:
                    raise ValueError(f"unauthorized rebase resolution at {name}")
                continue
        if name in repairs:
            if not actual or actual[0] not in {"100644", "100755"}:
                raise ValueError(f"test repair must remain a regular file: {name}")
            if actual != expected:
                changed_repairs.add(name)
        elif actual != expected:
            raise ValueError(f"unauthorized source change at {name}")
    if changed_repairs != set(repairs) or transition["before_tree"] == transition["after_tree"]:
        raise ValueError("repair allowlist must exactly identify actual repairs")
    return sorted(set(original["changed_files"]) | changed_repairs)
