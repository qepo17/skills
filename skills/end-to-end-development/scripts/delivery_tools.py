#!/usr/bin/env python3
"""Deterministic GitHub delivery. Canonical copy; mirrored into the fast skill.

Standard library only. This module executes mechanical Git/forge operations;
it does not decide workflow phases, approve changes, or repair source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, urlsplit


class DeliveryError(Exception):
    def __init__(self, summary: str, *, kind: str = "infrastructure", evidence_path: str | None = None) -> None:
        super().__init__(summary)
        self.kind = kind
        self.evidence_path = evidence_path


def run_process(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"})


def _git(worktree: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, env=env)
    if result.returncode:
        raise DeliveryError(f"Git content inspection failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def content_fingerprint(worktree: Path) -> str:
    """The existing v3 content identity, independent of commit and index stat cache."""
    root = Path(_git(worktree, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    source_index = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    if not source_index.is_absolute():
        source_index = root / source_index
    descriptor, name = tempfile.mkstemp(prefix="e2e-content-index-")
    os.close(descriptor)
    temporary = Path(name)
    try:
        if source_index.is_file():
            temporary.write_bytes(source_index.read_bytes())
        else:
            temporary.unlink()
        env = {**os.environ, "GIT_INDEX_FILE": str(temporary), "GIT_OPTIONAL_LOCKS": "0"}
        _git(root, "add", "--all", "--", env=env)
        tree = _git(root, "write-tree", env=env).strip()
        digest = hashlib.sha256(b"end-to-end-development-content-v3\0" + tree)
        for record in sorted(_git(root, "ls-files", "--stage", "-z", env=env).split(b"\0")):
            metadata, separator, relative = record.partition(b"\t")
            if separator and metadata.startswith(b"160000 "):
                submodule = root / relative.decode(errors="surrogateescape")
                if (submodule / ".git").exists():
                    digest.update(b"\0submodule\0" + relative + b"\0" + content_fingerprint(submodule).encode())
        return digest.hexdigest()
    finally:
        temporary.unlink(missing_ok=True)


def github_repository(remote: str) -> str | None:
    """Recognize GitHub remotes without exposing embedded credentials in evidence."""
    match = re.fullmatch(r"git@github\.com:([^/\s]+/[^/\s]+)", remote)
    if match:
        path = match.group(1)
    else:
        parsed = urlsplit(remote)
        if parsed.hostname != "github.com" or parsed.password or parsed.scheme not in {"https", "ssh"}:
            return None
        if parsed.scheme == "https" and parsed.username:
            return None
        path = parsed.path.strip("/")
    path = path.removesuffix(".git")
    return f"github.com/{path}" if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path) else None


def reference(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class Delivery:
    def __init__(self, spec: dict[str, Any], *, run_process: Callable[..., subprocess.CompletedProcess[str]] = run_process,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.spec = spec
        self.runner, self.clock, self.sleep = run_process, clock, sleep
        self.worktree = Path(spec.get("worktree", ".")).resolve()
        self.logs = Path(spec.get("log_dir", str(self.worktree))).resolve()
        self.repository = str(spec.get("repository", ""))
        self.result: dict[str, Any] = {
            "schema_version": 1, "status": "blocked", "kind": None, "summary": "Delivery not started.",
            "branch": spec.get("branch"), "base_branch": spec.get("base_branch"), "commits": [], "pr_url": None,
            "head_sha": None, "pushed_head_sha": None, "checked_head_sha": None,
            "check_policy": {"status": "unknown", "required_checks": [], "evidence": []},
            "checks": [], "commands": [], "evidence_path": None,
        }

    def command(self, args: list[str], *, allow_failure: bool = False, redact_output: bool = False) -> tuple[subprocess.CompletedProcess[str], Path]:
        try:
            process = self.runner(args, self.worktree, 30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DeliveryError(f"{args[0]} operation could not finish: {type(error).__name__}") from error
        with tempfile.NamedTemporaryFile(mode="w", prefix=f"{args[0]}-", suffix=".log", dir=self.logs, delete=False) as log:
            log.write("[redacted remote identity]\n" if redact_output else process.stdout + "\n" + process.stderr)
            path = Path(log.name)
        self.result["commands"].append({"command": args, "exit_code": process.returncode, "log_path": str(path)})
        self.result["evidence_path"] = str(path)
        if process.returncode and not allow_failure:
            error = process.stderr.lower()
            kind = "infrastructure"
            if process.returncode == 4 or any(text in error for text in ("authentication", "not logged", "http 401")):
                kind = "authentication"
            elif any(text in error for text in ("http 403", "permission denied", "forbidden")):
                kind = "infrastructure" if "rate limit" in error else "permission"
            raise DeliveryError(f"{args[0]} operation failed (exit {process.returncode}); see command evidence.", kind=kind, evidence_path=str(path))
        return process, path

    def git(self, *args: str, **kwargs: Any) -> str:
        return self.command(["git", *args], **kwargs)[0].stdout.strip()

    def gh_json(self, args: list[str]) -> tuple[Any, Path]:
        result, path = self.command(["gh", *args])
        try:
            data = json.loads(result.stdout)
            if isinstance(data, dict) and data.get("errors"):
                raise ValueError("GraphQL returned errors")
            return data, path
        except (ValueError, TypeError) as error:
            raise DeliveryError("GitHub returned indeterminate structured evidence.", evidence_path=str(path)) from error

    def api_pages(self, endpoint: str) -> tuple[list[Any], Path]:
        value, path = self.gh_json(["api", "--hostname", "github.com", endpoint, "--paginate", "--slurp"])
        if not isinstance(value, list) or not value:
            raise DeliveryError("GitHub pagination did not return complete evidence.", evidence_path=str(path))
        return value, path

    def names(self, *args: str) -> set[str]:
        output = self.command(["git", *args])[0].stdout
        return {name for name in output.split("\0") if name}

    def validate_spec(self) -> None:
        if not re.fullmatch(r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise DeliveryError("This command executor requires an explicit GitHub repository.", kind="decision")
        for key in ("branch", "base_branch"):
            value = self.spec.get(key)
            if not isinstance(value, str) or not value or value.startswith("-") or any(c.isspace() for c in value):
                raise DeliveryError(f"Unsafe {key}.", kind="decision")
            if self.command(["git", "check-ref-format", "--branch", value], allow_failure=True)[0].returncode:
                raise DeliveryError(f"Invalid {key}.", kind="decision")
        if self.spec["branch"] == self.spec["base_branch"]:
            raise DeliveryError("Delivery must use a dedicated task branch.", kind="decision")
        for key, pattern in (("baseline", r"[0-9a-f]{40}(?:[0-9a-f]{24})?"), ("expected_fingerprint", r"[0-9a-f]{64}")):
            if not isinstance(self.spec.get(key), str) or not re.fullmatch(pattern, self.spec[key]):
                raise DeliveryError(f"Missing or invalid {key}.", kind="decision")
        files = self.spec.get("task_files")
        if not isinstance(files, list) or not files or len(set(files)) != len(files):
            raise DeliveryError("An explicit, unique task-file inventory is required.", kind="decision")
        for name in files:
            if not isinstance(name, str) or not name or "\0" in name:
                raise DeliveryError("Invalid task path.", kind="decision")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts or "\\" in name:
                raise DeliveryError("Task path escapes the repository.", kind="decision")
            if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
                raise DeliveryError("Refusing to stage environment credentials.", kind="decision")
        for key in ("commit_message", "pr_title", "pr_body"):
            if not isinstance(self.spec.get(key), str) or not self.spec[key].strip():
                raise DeliveryError(f"Pre-approved {key} is required.", kind="decision")
        timeout = self.spec.get("check_timeout_seconds", 1800)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 1800:
            raise DeliveryError("Check timeout must be between 0 and 1800 seconds.", kind="decision")

    def audit(self) -> set[str]:
        self.validate_spec()
        if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.worktree:
            raise DeliveryError("Worktree must identify the Git root.", kind="decision")
        # get-url expands insteadOf/pushInsteadOf and explicit pushurl entries.
        # Audit every effective destination before even staging task content.
        for options in (("--all",), ("--push", "--all")):
            remotes = self.git("remote", "get-url", *options, "origin", redact_output=True).splitlines()
            if not remotes or any(github_repository(remote) != self.repository for remote in remotes):
                raise DeliveryError("An effective origin destination does not match the assigned GitHub repository.", kind="decision")
        if self.git("branch", "--show-current") != self.spec["branch"]:
            raise DeliveryError("Task branch changed before delivery.", kind="decision")
        if self.command(["git", "merge-base", "--is-ancestor", self.spec["baseline"], "HEAD"], allow_failure=True)[0].returncode:
            raise DeliveryError("Baseline is not an ancestor of the current head.", kind="decision")
        dirty = self.names("diff", "--name-only", "--no-renames", "-z", "HEAD", "--") | self.names("ls-files", "--others", "--exclude-standard", "-z")
        staged = self.names("diff", "--cached", "--name-only", "--no-renames", "-z", "HEAD", "--")
        changed = self.names("diff", "--name-only", "--no-renames", "-z", self.spec["baseline"], "--") | dirty | staged
        if not changed <= set(self.spec["task_files"]):
            raise DeliveryError("Unrelated changes are present; their index/worktree state was preserved.", kind="decision")
        if content_fingerprint(self.worktree) != self.spec["expected_fingerprint"]:
            raise DeliveryError("Current content no longer matches passing validation evidence.", kind="decision")
        if not changed:
            raise DeliveryError("No task diff exists against the recorded baseline.", kind="decision")
        return dirty | staged

    def verify_committed_content(self) -> None:
        dirty = self.names("diff", "--name-only", "-z", "HEAD", "--")
        staged = self.names("diff", "--cached", "--name-only", "-z", "HEAD", "--")
        untracked = self.names("ls-files", "--others", "--exclude-standard", "-z")
        if dirty or staged or untracked or content_fingerprint(self.worktree) != self.spec["expected_fingerprint"]:
            raise DeliveryError("Committed/index content differs from validated files, possibly due to a Git hook; nothing further was pushed.", kind="decision")

    def remote_head(self) -> str | None:
        output = self.git("ls-remote", "--refs", "origin", f"refs/heads/{self.spec['branch']}")
        rows = output.splitlines()
        if not rows:
            return None
        if len(rows) != 1 or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", rows[0].split()[0]):
            raise DeliveryError("Remote branch identity is indeterminate.")
        return rows[0].split()[0]

    def ensure_pr(self, *, verify_only: bool = False) -> None:
        prs, _ = self.gh_json(["pr", "list", "--repo", self.repository, "--head", self.spec["branch"], "--state", "all",
                              "--json", "number,url,baseRefName,headRefName,state,headRefOid"])
        if not isinstance(prs, list) or len(prs) > 1:
            raise DeliveryError("Task branch PR identity is ambiguous.", kind="decision")
        if prs:
            pr = prs[0]
            if (pr.get("state") != "OPEN" or pr.get("baseRefName") != self.spec["base_branch"]
                    or pr.get("headRefName") != self.spec["branch"]
                    or not re.fullmatch(re.escape(f"https://{self.repository}/pull/") + r"[0-9]+", pr.get("url", ""))):
                raise DeliveryError("Existing PR has an unexpected identity, state, or base; it was not overwritten.", kind="decision")
            self.result["pr_url"] = pr["url"]
            return
        if verify_only:
            raise DeliveryError("The delivered PR no longer exists; verification cannot recreate it.", kind="dependency")
        with tempfile.NamedTemporaryFile(mode="w", prefix="pr-body-", suffix=".md", dir=self.logs, delete=False) as body:
            body.write(self.spec["pr_body"])
        output, _ = self.command(["gh", "pr", "create", "--repo", self.repository, "--base", self.spec["base_branch"],
                                 "--head", self.spec["branch"], "--title", self.spec["pr_title"], "--body-file", body.name])
        url = output.stdout.strip()
        if not url.startswith(f"https://{self.repository}/pull/"):
            raise DeliveryError("PR creation returned an unexpected identity; reconcile before retrying.")
        self.result["pr_url"] = url

    def pr_head(self) -> str:
        value, _ = self.gh_json(["pr", "view", self.result["pr_url"], "--repo", self.repository,
                                "--json", "headRefOid,headRefName,baseRefName,state"])
        if value.get("state") != "OPEN" or value.get("baseRefName") != self.spec["base_branch"] or value.get("headRefName") != self.spec["branch"]:
            raise DeliveryError("PR branch/base/state changed during delivery.", kind="dependency")
        return value["headRefOid"]

    def required_policy(self) -> dict[str, Any]:
        _, owner, name = self.repository.split("/")
        query = "query($owner:String!,$name:String!,$ref:String!){repository(owner:$owner,name:$name){ref(qualifiedName:$ref){branchProtectionRule{requiresStatusChecks requiredStatusChecks{context app{databaseId}}}}}}"
        data, legacy_log = self.gh_json(["api", "--hostname", "github.com", "graphql", "-f", f"query={query}",
                                        "-f", f"owner={owner}", "-f", f"name={name}", "-f", f"ref=refs/heads/{self.spec['base_branch']}"])
        branch = data["data"]["repository"]["ref"]
        if not isinstance(branch, dict) or "branchProtectionRule" not in branch:
            raise DeliveryError("Base branch protection could not be determined.")
        required: set[tuple[str, int | None]] = set()
        legacy = branch["branchProtectionRule"]
        if legacy is not None:
            if not isinstance(legacy.get("requiresStatusChecks"), bool):
                raise DeliveryError("Legacy required-check policy is indeterminate.")
            if legacy["requiresStatusChecks"]:
                for check in legacy["requiredStatusChecks"]:
                    required.add((check["context"], (check.get("app") or {}).get("databaseId")))
                if not required:
                    raise DeliveryError("Status checks are required but their identities are unavailable.")
        pages, rules_log = self.api_pages(f"repos/{owner}/{name}/rules/branches/{quote(self.spec['base_branch'], safe='')}")
        for page in pages:
            if not isinstance(page, list):
                raise DeliveryError("Applicable branch rules are indeterminate.")
            for rule in page:
                if rule["type"] == "required_status_checks":
                    checks = rule["parameters"]["required_status_checks"]
                    if not checks:
                        raise DeliveryError("A required-check rule has no observable check identities.")
                    for check in checks:
                        app = check.get("integration_id")
                        required.add((check["context"], None if app in {None, -1} else app))
        for context, app in required:
            if not isinstance(context, str) or not context or (app is not None and (type(app) is not int or app < 1)):
                raise DeliveryError("Required-check identity is invalid.")
        return {"status": "required" if required else "not-configured",
                "required_checks": [{"name": name, "app_id": app} for name, app in sorted(required, key=lambda item: (item[0], item[1] or 0))],
                "evidence": [reference(legacy_log), reference(rules_log)]}

    def check_records(self, head: str, policy: dict[str, Any]) -> list[dict[str, Any]]:
        path = f"repos/{self.repository.removeprefix('github.com/')}/commits/{head}"
        pages, run_log = self.api_pages(path + "/check-runs?filter=latest&per_page=100")
        observed = []
        for page in pages:
            for check in page["check_runs"]:
                if check["head_sha"] != head:
                    raise DeliveryError("Check evidence belongs to another head.", kind="dependency")
                conclusion = check.get("conclusion")
                state = "pending" if check["status"] != "completed" else {"success": "passed", "cancelled": "cancelled", "skipped": "skipped", "neutral": "skipped"}.get(conclusion, "failed")
                observed.append({"name": check["name"], "app_id": (check.get("app") or {}).get("id"), "state": state,
                                 "url": check["html_url"], "evidence_path": str(run_log), "required": False})
        pages, status_log = self.api_pages(path + "/statuses?per_page=100")
        seen = set()
        for page in pages:
            for status in page:
                if status["context"] in seen:
                    continue  # REST statuses are newest first.
                seen.add(status["context"])
                observed.append({"name": status["context"], "app_id": None,
                                 "state": {"success": "passed", "pending": "pending"}.get(status["state"], "failed"),
                                 "url": status.get("target_url") or self.result["pr_url"],
                                 "evidence_path": str(status_log), "required": False})
        for required in policy["required_checks"]:
            matches = [record for record in observed if record["name"] == required["name"]
                       and (required["app_id"] is None or record["app_id"] == required["app_id"])]
            if not matches:
                observed.append({**required, "state": "pending", "required": True,
                                 "url": self.result["pr_url"], "evidence_path": str(run_log)})
            for record in matches:
                record["required"] = True
        return sorted(observed, key=lambda check: (check["name"], check.get("app_id") or 0, check["url"]))

    def run(self, *, verify_only: bool = False) -> dict[str, Any]:
        self.result["verify_only"] = verify_only
        start = self.clock()
        try:
            if self.logs.is_relative_to(self.worktree):
                raise DeliveryError("Delivery evidence must live outside the project worktree.", kind="decision")
            self.logs.mkdir(parents=True, exist_ok=True)
            dirty = self.audit()
            if dirty:
                if verify_only:
                    raise DeliveryError("Verification found uncommitted content; it cannot write Git state.", kind="decision")
                paths = [f":(literal){name}" for name in sorted(dirty)]
                self.git("add", "--", *paths)
                self.git("commit", "--only", "--message", self.spec["commit_message"], "--", *paths)
            head = self.git("rev-parse", "HEAD")
            self.result.update(head_sha=head, commits=[head])
            self.verify_committed_content()
            if self.remote_head() != head:
                if verify_only:
                    raise DeliveryError("Pushed head changed; verification cannot push over it.", kind="dependency")
                self.git("push", "--set-upstream", "origin", f"refs/heads/{self.spec['branch']}:refs/heads/{self.spec['branch']}")
            self.result["pushed_head_sha"] = self.remote_head()
            if self.result["pushed_head_sha"] != head:
                raise DeliveryError("Pushed head does not match the validated local head.", kind="dependency")
            self.ensure_pr(verify_only=verify_only)
            policy = self.required_policy()
            self.result["check_policy"] = policy
            deadline = start + self.spec.get("check_timeout_seconds", 1800)
            while True:
                if self.pr_head() != head:
                    raise DeliveryError("PR head changed; check evidence was invalidated.", kind="dependency")
                self.result["checks"] = self.check_records(head, policy)
                required = [check for check in self.result["checks"] if check["required"]]
                if any(check["state"] in {"failed", "cancelled", "skipped"} for check in required):
                    raise DeliveryError("A required CI check failed; inspect whether a compatible source fix is needed.", kind="code")
                if all(check["state"] == "passed" for check in required):
                    final_policy = self.required_policy()
                    if final_policy["required_checks"] != policy["required_checks"] or final_policy["status"] != policy["status"]:
                        raise DeliveryError("Required-check policy changed; reconcile fresh check evidence.", kind="dependency")
                    self.result["check_policy"] = final_policy
                    if self.pr_head() != head or self.remote_head() != head or self.git("rev-parse", "HEAD") != head:
                        raise DeliveryError("Final head drift invalidated passing CI evidence.", kind="dependency")
                    self.verify_committed_content()
                    self.result.update(status="complete", kind=None, checked_head_sha=head,
                                       summary="Required checks passed on the final head." if required else "No required checks are configured; local validation remains mandatory.")
                    break
                if self.clock() >= deadline:
                    self.result.update(status="pending", kind="infrastructure", summary="Required CI checks are pending; delivery is not complete.")
                    break
                self.sleep(min(10, max(0, deadline - self.clock())))
        except DeliveryError as error:
            self.result.update(status="blocked", kind=error.kind, summary=str(error))
            if error.evidence_path:
                self.result["evidence_path"] = error.evidence_path
        except (KeyError, TypeError, ValueError, OSError) as error:
            self.result.update(status="blocked", kind="infrastructure", summary=f"Delivery evidence/configuration is indeterminate ({type(error).__name__}); inspect logs.")
        self.result["elapsed_seconds"] = round(self.clock() - start, 3)
        return self.result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fingerprint = sub.add_parser("fingerprint", help="print commit-independent content identity")
    fingerprint.add_argument("worktree", type=Path)
    deliver = sub.add_parser("deliver", help="reconcile a verified change through GitHub delivery")
    deliver.add_argument("--input", type=Path, required=True)
    deliver.add_argument("--output", type=Path, required=True)
    deliver.add_argument("--verify-only", action="store_true", help="refresh delivered evidence without commit/push/PR writes")
    args = parser.parse_args()
    if args.command == "fingerprint":
        print(content_fingerprint(args.worktree))
        return 0
    if args.output.exists():
        parser.error("output exists; use a new evidence path when reconciling delivery")
    spec = json.loads(args.input.read_text())
    output = args.output.resolve()
    if output.is_relative_to(Path(spec["worktree"]).resolve()):
        parser.error("output must live outside the project worktree")
    result = Delivery(spec).run(verify_only=args.verify_only)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(output)
    print(json.dumps({"status": result["status"], "pr_url": result["pr_url"], "output": str(output)}))
    return 0 if result["status"] == "complete" else 8 if result["status"] == "pending" else 1


if __name__ == "__main__":
    raise SystemExit(main())
