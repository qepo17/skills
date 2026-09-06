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


MANAGED_BODY_LABEL = "end-to-end-development-delivery-v1"


class DeliveryError(Exception):
    def __init__(self, summary: str, *, kind: str = "infrastructure", evidence_path: str | None = None,
                 reason_code: str) -> None:
        super().__init__(summary)
        self.kind = kind
        self.evidence_path = evidence_path
        self.reason_code = reason_code


def run_process(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"})


def _git(worktree: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, env=env)
    if result.returncode:
        raise DeliveryError(f"Git content inspection failed: {result.stderr.decode(errors='replace').strip()}",
                            reason_code="git-content-inspection-failed")
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
        self._pr_body: str | None = None
        self._intent: dict[str, Any] | None = None
        self.intent_path = Path(spec.get('pr_intent_path', str(self.logs / 'pr-creation-intent.json'))).resolve()
        self.ready_path = self.intent_path.with_suffix('.ready.json')
        self._was_ready = False
        self.result: dict[str, Any] = {
            "schema_version": 1, "status": "blocked", "kind": None, "summary": "Delivery not started.",
            "branch": spec.get("branch"), "base_branch": spec.get("base_branch"), "commits": [], "pr_url": None,
            "head_sha": None, "pushed_head_sha": None, "checked_head_sha": None,
            "pr_draft": None, "pr_owned": False, "reason_code": None, "creation_intent": None, "ownership_observation": None,
            "check_policy": {"status": "unknown", "required_checks": [], "evidence": []},
            "checks": [], "commands": [], "evidence_path": None,
        }

    def command(self, args: list[str], *, allow_failure: bool = False, redact_output: bool = False) -> tuple[subprocess.CompletedProcess[str], Path]:
        try:
            process = self.runner(args, self.worktree, 30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DeliveryError(f"{args[0]} operation could not finish: {type(error).__name__}",
                                reason_code=f"{args[0]}-operation-unavailable") from error
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
            raise DeliveryError(f"{args[0]} operation failed (exit {process.returncode}); see command evidence.",
                                kind=kind, evidence_path=str(path), reason_code=f"{args[0]}-operation-failed")
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
            raise DeliveryError("GitHub returned indeterminate structured evidence.", evidence_path=str(path),
                                reason_code="invalid-github-response") from error

    def api_pages(self, endpoint: str) -> tuple[list[Any], Path]:
        value, path = self.gh_json(["api", "--hostname", "github.com", endpoint, "--paginate", "--slurp"])
        if not isinstance(value, list) or not value:
            raise DeliveryError("GitHub pagination did not return complete evidence.", evidence_path=str(path),
                                reason_code="incomplete-github-pagination")
        return value, path

    def names(self, *args: str) -> set[str]:
        output = self.command(["git", *args])[0].stdout
        return {name for name in output.split("\0") if name}

    def validate_spec(self) -> None:
        lifecycle = self.spec.get("pr_lifecycle")
        if lifecycle not in {None, "draft-until-verified"}:
            raise DeliveryError("Unsupported PR lifecycle policy.", kind="decision", reason_code="unsupported-pr-lifecycle")
        if lifecycle == "draft-until-verified":
            run_id = self.spec.get("run_id")
            if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 256 or "\x00" in run_id:
                raise DeliveryError("Draft PR lifecycle requires a valid run_id.", kind="decision", reason_code="invalid-run-id")
        if not re.fullmatch(r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise DeliveryError("This command executor requires an explicit GitHub repository.",
                                kind="decision", reason_code="invalid-repository")
        for key in ("branch", "base_branch"):
            value = self.spec.get(key)
            if not isinstance(value, str) or not value or value.startswith("-") or any(c.isspace() for c in value):
                raise DeliveryError(f"Unsafe {key}.", kind="decision", reason_code=f"unsafe-{key.replace('_', '-')}")
            if self.command(["git", "check-ref-format", "--branch", value], allow_failure=True)[0].returncode:
                raise DeliveryError(f"Invalid {key}.", kind="decision", reason_code=f"invalid-{key.replace('_', '-')}")
        if self.spec["branch"] == self.spec["base_branch"]:
            raise DeliveryError("Delivery must use a dedicated task branch.",
                                kind="decision", reason_code="task-branch-required")
        for key, pattern in (("baseline", r"[0-9a-f]{40}(?:[0-9a-f]{24})?"), ("expected_fingerprint", r"[0-9a-f]{64}")):
            if not isinstance(self.spec.get(key), str) or not re.fullmatch(pattern, self.spec[key]):
                raise DeliveryError(f"Missing or invalid {key}.",
                                    kind="decision", reason_code=f"invalid-{key.replace('_', '-')}")
        files = self.spec.get("task_files")
        if not isinstance(files, list) or not files or len(set(files)) != len(files):
            raise DeliveryError("An explicit, unique task-file inventory is required.",
                                kind="decision", reason_code="invalid-task-files")
        for name in files:
            if not isinstance(name, str) or not name or "\0" in name:
                raise DeliveryError("Invalid task path.", kind="decision", reason_code="invalid-task-path")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts or "\\" in name:
                raise DeliveryError("Task path escapes the repository.", kind="decision", reason_code="unsafe-task-path")
            if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
                raise DeliveryError("Refusing to stage environment credentials.",
                                    kind="decision", reason_code="credential-file-refused")
        for key in ("commit_message", "pr_title", "pr_body"):
            if not isinstance(self.spec.get(key), str) or not self.spec[key].strip():
                raise DeliveryError(f"Pre-approved {key} is required.",
                                    kind="decision", reason_code=f"missing-{key.replace('_', '-')}")
        timeout = self.spec.get("check_timeout_seconds", 1800)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 1800:
            raise DeliveryError("Check timeout must be between 0 and 1800 seconds.",
                                kind="decision", reason_code="invalid-check-timeout")

    def audit(self) -> set[str]:
        self.validate_spec()
        if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.worktree:
            raise DeliveryError("Worktree must identify the Git root.",
                                kind="decision", reason_code="invalid-worktree-root")
        # get-url expands insteadOf/pushInsteadOf and explicit pushurl entries.
        # Audit every effective destination before even staging task content.
        for options in (("--all",), ("--push", "--all")):
            remotes = self.git("remote", "get-url", *options, "origin", redact_output=True).splitlines()
            if not remotes or any(github_repository(remote) != self.repository for remote in remotes):
                raise DeliveryError("An effective origin destination does not match the assigned GitHub repository.",
                                    kind="decision", reason_code="remote-identity-mismatch")
        if self.git("branch", "--show-current") != self.spec["branch"]:
            raise DeliveryError("Task branch changed before delivery.",
                                kind="decision", reason_code="task-branch-changed")
        if self.command(["git", "merge-base", "--is-ancestor", self.spec["baseline"], "HEAD"], allow_failure=True)[0].returncode:
            raise DeliveryError("Baseline is not an ancestor of the current head.",
                                kind="decision", reason_code="baseline-not-ancestor")
        dirty = self.names("diff", "--name-only", "--no-renames", "-z", "HEAD", "--") | self.names("ls-files", "--others", "--exclude-standard", "-z")
        staged = self.names("diff", "--cached", "--name-only", "--no-renames", "-z", "HEAD", "--")
        changed = self.names("diff", "--name-only", "--no-renames", "-z", self.spec["baseline"], "--") | dirty | staged
        if not changed <= set(self.spec["task_files"]):
            raise DeliveryError("Unrelated changes are present; their index/worktree state was preserved.",
                                kind="decision", reason_code="unrelated-changes-present")
        if content_fingerprint(self.worktree) != self.spec["expected_fingerprint"]:
            raise DeliveryError("Current content no longer matches passing validation evidence.",
                                kind="decision", reason_code="validated-content-changed")
        if not changed:
            raise DeliveryError("No task diff exists against the recorded baseline.",
                                kind="decision", reason_code="task-diff-missing")
        return dirty | staged

    def verify_committed_content(self) -> None:
        dirty = self.names("diff", "--name-only", "-z", "HEAD", "--")
        staged = self.names("diff", "--cached", "--name-only", "-z", "HEAD", "--")
        untracked = self.names("ls-files", "--others", "--exclude-standard", "-z")
        if dirty or staged or untracked or content_fingerprint(self.worktree) != self.spec["expected_fingerprint"]:
            raise DeliveryError("Committed/index content differs from validated files, possibly due to a Git hook; nothing further was pushed.",
                                kind="decision", reason_code="committed-content-changed")

    def remote_head(self) -> str | None:
        output = self.git("ls-remote", "--refs", "origin", f"refs/heads/{self.spec['branch']}")
        rows = output.splitlines()
        if not rows:
            return None
        if len(rows) != 1 or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", rows[0].split()[0]):
            raise DeliveryError("Remote branch identity is indeterminate.", reason_code="indeterminate-remote-head")
        return rows[0].split()[0]

    def draft_lifecycle(self) -> bool:
        return self.spec.get("pr_lifecycle") == "draft-until-verified"

    def ownership_token(self) -> str:
        identity = json.dumps({
            "base_branch": self.spec["base_branch"],
            "branch": self.spec["branch"],
            "repository": self.repository,
            "run_id": self.spec["run_id"],
            "nonce": self._intent['nonce'] if self._intent else None,
        }, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(b"end-to-end-development-pr-owner-v1\0" + identity).hexdigest()

    def intent_binding(self) -> dict[str, Any]:
        return {'version': 1, 'repository': self.repository, 'branch': self.spec['branch'],
                'base_branch': self.spec['base_branch'], 'run_id': self.spec['run_id']}

    def load_creation_intent(self) -> None:
        intended_parent = Path(self.spec.get('pr_intent_path', str(self.logs / 'pr-creation-intent.json'))).absolute().parent.resolve()
        if (self.intent_path.is_relative_to(self.worktree) or self.ready_path.is_relative_to(self.worktree)
                or self.intent_path.parent != intended_parent or self.ready_path.resolve().parent != intended_parent):
            raise DeliveryError('PR ownership evidence must live outside the project worktree.',
                                kind='decision', reason_code='unsafe-ownership-evidence')
        if not self.intent_path.exists():
            return
        intent = json.loads(self.intent_path.read_text())
        binding = self.intent_binding()
        if (not isinstance(intent, dict) or set(intent) != set(binding) | {'nonce'}
                or any(intent.get(key) != value for key, value in binding.items())
                or not re.fullmatch(r'[0-9a-f]{64}', str(intent.get('nonce', '')))):
            raise DeliveryError('Existing PR creation intent has a conflicting identity.',
                                kind='decision', reason_code='conflicting-creation-intent')
        self._intent = intent

    @staticmethod
    def persist_once(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.pr-intent-', delete=False) as file:
            json.dump(value, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        temporary = Path(file.name)
        try:
            try:
                os.link(temporary, path)  # Exclusive atomic publication, never overwrite prior intent.
            except FileExistsError:
                if json.loads(path.read_text()) != value:
                    raise DeliveryError('Conflicting immutable PR ownership evidence.',
                                        kind='decision', reason_code='conflicting-creation-intent')
        finally:
            temporary.unlink(missing_ok=True)

    def create_intent(self) -> None:
        if self._intent is None:
            self._intent = self.intent_binding() | {'nonce': os.urandom(32).hex()}
            self.persist_once(self.intent_path, self._intent)

    def observe_readiness(self) -> None:
        if not self.result['pr_owned']:
            return
        fact = {'creation_intent': reference(self.intent_path), 'pr_url': self.result['pr_url']}
        if self.ready_path.exists():
            if json.loads(self.ready_path.read_text()) != fact:
                raise DeliveryError('Prior PR readiness observation has a different identity.',
                                    kind='decision', reason_code='conflicting-creation-intent')
            self._was_ready = True
        if not self.result['pr_draft'] and not self._was_ready:
            self.persist_once(self.ready_path, fact)  # Local observed fact; no Git/forge mutation.
            self._was_ready = True

    def managed_markers(self) -> tuple[str, str]:
        token = self.ownership_token()
        return (f"<!-- {MANAGED_BODY_LABEL}:{token}:start -->",
                f"<!-- {MANAGED_BODY_LABEL}:{token}:end -->")

    def managed_section(self, message: str) -> str:
        start, end = self.managed_markers()
        local = self.spec.get("local_validation_summary", "")
        content = f"\n## Automated delivery validation\n\n{local}\n\n{message}\n"
        digest = hashlib.sha256(content.encode()).hexdigest()
        return f"{start}\n<!-- managed-content-sha256:{digest} -->{content}{end}"

    def body_with_managed_section(self, body: str, message: str) -> str:
        return body.rstrip() + "\n\n" + self.managed_section(message) + "\n"

    def owns_pr_body(self, body: str) -> bool:
        start, end = self.managed_markers()
        return self._intent is not None and body.count(start) == 1 and body.count(end) == 1 and body.index(start) < body.index(end)

    def record_pr(self, pr: dict[str, Any]) -> None:
        if (pr.get("state") != "OPEN" or pr.get("baseRefName") != self.spec["base_branch"]
                or pr.get("headRefName") != self.spec["branch"]
                or not re.fullmatch(re.escape(f"https://{self.repository}/pull/") + r"[0-9]+", pr.get("url", ""))):
            raise DeliveryError("Existing PR has an unexpected identity, state, or base; it was not overwritten.",
                                kind="decision", reason_code="unexpected-pr-identity")
        if not isinstance(pr.get("isDraft"), bool) or not isinstance(pr.get("body"), str):
            raise DeliveryError("PR readiness or body ownership evidence is indeterminate.",
                                reason_code="indeterminate-pr-state")
        self.result.update(pr_url=pr["url"], pr_draft=pr["isDraft"])
        self._pr_body = pr["body"]
        if self.draft_lifecycle():
            self.result["pr_owned"] = self.owns_pr_body(pr["body"])
            if self.result['pr_owned']:
                self.result['creation_intent'] = reference(self.intent_path)
                with tempfile.NamedTemporaryFile(mode='w', prefix='pr-observation-', suffix='.json', dir=self.logs, delete=False) as file:
                    json.dump(pr, file)
                    observation_path = Path(file.name)
                self.result['ownership_observation'] = reference(observation_path)
            self.observe_readiness()
            if self.result['pr_owned']:
                self.managed_span()  # Conflicts block before any readiness/body write.

    def observe_pr(self) -> dict[str, Any]:
        value, _ = self.gh_json(["pr", "view", self.result["pr_url"], "--repo", self.repository,
                                "--json", "url,body,isDraft,headRefOid,headRefName,baseRefName,state"])
        if not isinstance(value, dict):
            raise DeliveryError("PR state evidence is indeterminate.", reason_code="indeterminate-pr-state")
        self.record_pr(value)
        return value

    def ensure_pr(self, *, verify_only: bool = False) -> None:
        prs, _ = self.gh_json(["pr", "list", "--repo", self.repository, "--head", self.spec["branch"], "--state", "all",
                              "--json", "number,url,body,isDraft,baseRefName,headRefName,state,headRefOid"])
        if not isinstance(prs, list) or len(prs) > 1:
            raise DeliveryError("Task branch PR identity is ambiguous.", kind="decision", reason_code="ambiguous-pr-identity")
        if prs:
            self.record_pr(prs[0])
            return
        if verify_only:
            raise DeliveryError("The delivered PR no longer exists; verification cannot recreate it.",
                                kind="dependency", reason_code="pr-missing")
        pr_body = self.spec["pr_body"]
        if self.draft_lifecycle():
            self.create_intent()
            pr_body = self.body_with_managed_section(pr_body, "Required CI has not yet been observed.")
        with tempfile.NamedTemporaryFile(mode="w", prefix="pr-body-", suffix=".md", dir=self.logs, delete=False) as body:
            body.write(pr_body)
        create = ["gh", "pr", "create", "--repo", self.repository, "--base", self.spec["base_branch"],
                  "--head", self.spec["branch"], "--title", self.spec["pr_title"], "--body-file", body.name]
        if self.draft_lifecycle():
            create.append("--draft")
        try:
            output, _ = self.command(create)
        except DeliveryError as error:
            if not self.draft_lifecycle():
                raise
            raise DeliveryError("Draft PR creation failed; draft support or forge access could not be confirmed.",
                                kind=error.kind, evidence_path=error.evidence_path,
                                reason_code="draft-pr-creation-failed") from error
        url = output.stdout.strip()
        if not url.startswith(f"https://{self.repository}/pull/"):
            raise DeliveryError("PR creation returned an unexpected identity; reconcile before retrying.",
                                reason_code="unexpected-created-pr-identity")
        self.result["pr_url"] = url
        self.observe_pr()
        if self.draft_lifecycle() and not self.result["pr_owned"]:
            raise DeliveryError("Created PR does not contain the expected run ownership marker.",
                                reason_code="pr-ownership-marker-missing")

    def pr_head(self) -> str:
        value = self.observe_pr()
        return value["headRefOid"]

    def publish_owned_draft(self, head: str) -> None:
        try:
            self.command(["gh", "pr", "ready", self.result["pr_url"], "--repo", self.repository])
        except DeliveryError as error:
            self.result["pr_draft"] = None
            try:
                self.observe_pr()
            except DeliveryError:
                pass
            raise DeliveryError("Owned draft publication failed; its readiness was not assumed to change.",
                                kind=error.kind, evidence_path=error.evidence_path,
                                reason_code="publication-failed") from error
        value = self.observe_pr()
        if self.result["pr_draft"]:
            raise DeliveryError("GitHub did not publish the owned draft PR.", reason_code="publication-failed")
        if value.get("headRefOid") != head:
            raise DeliveryError("PR head changed during publication.",
                                kind="dependency", reason_code="pr-head-changed")

    def managed_span(self) -> tuple[int, int]:
        if self._pr_body is None:
            raise DeliveryError("Owned PR body evidence is unavailable.", reason_code="indeterminate-pr-state")
        start, end = self.managed_markers()
        start_at = self._pr_body.index(start)
        end_at = self._pr_body.index(end, start_at) + len(end)
        existing = self._pr_body[start_at + len(start):end_at - len(end)]
        pinned = re.fullmatch(r"\n<!-- managed-content-sha256:([0-9a-f]{64}) -->(.*)", existing, re.DOTALL)
        if pinned is None or hashlib.sha256(pinned[2].encode()).hexdigest() != pinned[1]:
            raise DeliveryError("Human edits inside the managed validation section were preserved; reconcile the conflict explicitly.",
                                kind="decision", reason_code="managed-body-edited")
        return start_at, end_at

    def reconcile_managed_section(self, message: str, head: str) -> None:
        if not self.draft_lifecycle() or not self.result['pr_owned']:
            return
        start_at, end_at = self.managed_span()
        updated = self._pr_body[:start_at] + self.managed_section(message) + self._pr_body[end_at:]
        if updated == self._pr_body:
            return
        with tempfile.NamedTemporaryFile(mode="w", prefix="pr-body-", suffix=".md", dir=self.logs, delete=False) as body:
            body.write(updated)
        self.command(["gh", "pr", "edit", self.result["pr_url"], "--repo", self.repository,
                      "--body-file", body.name])
        value = self.observe_pr()
        if value.get("headRefOid") != head:
            raise DeliveryError("PR head changed while reconciling delivery validation.",
                                kind="dependency", reason_code="pr-head-changed")
        if not self.result["pr_owned"]:
            raise DeliveryError("The managed delivery section changed unexpectedly.",
                                kind="dependency", reason_code="pr-ownership-changed")

    def required_policy(self) -> dict[str, Any]:
        _, owner, name = self.repository.split("/")
        query = "query($owner:String!,$name:String!,$ref:String!){repository(owner:$owner,name:$name){ref(qualifiedName:$ref){branchProtectionRule{requiresStatusChecks requiredStatusChecks{context app{databaseId}}}}}}"
        data, legacy_log = self.gh_json(["api", "--hostname", "github.com", "graphql", "-f", f"query={query}",
                                        "-f", f"owner={owner}", "-f", f"name={name}", "-f", f"ref=refs/heads/{self.spec['base_branch']}"])
        branch = data["data"]["repository"]["ref"]
        if not isinstance(branch, dict) or "branchProtectionRule" not in branch:
            raise DeliveryError("Base branch protection could not be determined.",
                                reason_code="indeterminate-required-policy")
        required: set[tuple[str, int | None]] = set()
        legacy = branch["branchProtectionRule"]
        if legacy is not None:
            if not isinstance(legacy.get("requiresStatusChecks"), bool):
                raise DeliveryError("Legacy required-check policy is indeterminate.",
                                    reason_code="indeterminate-required-policy")
            if legacy["requiresStatusChecks"]:
                for check in legacy["requiredStatusChecks"]:
                    required.add((check["context"], (check.get("app") or {}).get("databaseId")))
                if not required:
                    raise DeliveryError("Status checks are required but their identities are unavailable.",
                                        reason_code="indeterminate-required-policy")
        pages, rules_log = self.api_pages(f"repos/{owner}/{name}/rules/branches/{quote(self.spec['base_branch'], safe='')}")
        for page in pages:
            if not isinstance(page, list):
                raise DeliveryError("Applicable branch rules are indeterminate.",
                                    reason_code="indeterminate-required-policy")
            for rule in page:
                if rule["type"] == "required_status_checks":
                    checks = rule["parameters"]["required_status_checks"]
                    if not checks:
                        raise DeliveryError("A required-check rule has no observable check identities.",
                                            reason_code="indeterminate-required-policy")
                    for check in checks:
                        app = check.get("integration_id")
                        required.add((check["context"], None if app in {None, -1} else app))
        for context, app in required:
            if not isinstance(context, str) or not context or (app is not None and (type(app) is not int or app < 1)):
                raise DeliveryError("Required-check identity is invalid.",
                                    reason_code="invalid-required-check-identity")
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
                    raise DeliveryError("Check evidence belongs to another head.",
                                        kind="dependency", reason_code="check-head-mismatch")
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
                raise DeliveryError("Delivery evidence must live outside the project worktree.",
                                    kind="decision", reason_code="unsafe-evidence-location")
            self.logs.mkdir(parents=True, exist_ok=True)
            dirty = self.audit()
            if self.draft_lifecycle():
                self.load_creation_intent()
            if dirty:
                if verify_only:
                    raise DeliveryError("Verification found uncommitted content; it cannot write Git state.",
                                        kind="decision", reason_code="verify-only-uncommitted-content")
                paths = [f":(literal){name}" for name in sorted(dirty)]
                self.git("add", "--", *paths)
                self.git("commit", "--only", "--message", self.spec["commit_message"], "--", *paths)
            head = self.git("rev-parse", "HEAD")
            self.result.update(head_sha=head, commits=[head])
            self.verify_committed_content()
            if self.remote_head() != head:
                if verify_only:
                    raise DeliveryError("Pushed head changed; verification cannot push over it.",
                                        kind="dependency", reason_code="pushed-head-mismatch")
                self.git("push", "--set-upstream", "origin", f"refs/heads/{self.spec['branch']}:refs/heads/{self.spec['branch']}")
            self.result["pushed_head_sha"] = self.remote_head()
            if self.result["pushed_head_sha"] != head:
                raise DeliveryError("Pushed head does not match the validated local head.",
                                    kind="dependency", reason_code="pushed-head-mismatch")
            self.ensure_pr(verify_only=verify_only)
            policy = self.required_policy()
            self.result["check_policy"] = policy
            deadline = start + self.spec.get("check_timeout_seconds", 1800)
            published = False
            while True:
                if self.pr_head() != head:
                    raise DeliveryError("PR head changed; check evidence was invalidated.",
                                        kind="dependency", reason_code="pr-head-changed")
                self.result["checks"] = self.check_records(head, policy)
                required = [check for check in self.result["checks"] if check["required"]]
                if any(check["state"] in {"failed", "cancelled", "skipped"} for check in required):
                    if not verify_only:
                        self.reconcile_managed_section(
                            "Required CI failed, was cancelled, or was skipped; delivery remains blocked.", head)
                    raise DeliveryError("A required CI check failed; inspect whether a compatible source fix is needed.",
                                        kind="code", reason_code="required-ci-failed")
                if all(check["state"] == "passed" for check in required):
                    final_policy = self.required_policy()
                    if final_policy["required_checks"] != policy["required_checks"] or final_policy["status"] != policy["status"]:
                        raise DeliveryError("Required-check policy changed; reconcile fresh check evidence.",
                                            kind="dependency", reason_code="required-policy-changed")
                    self.result["check_policy"] = final_policy
                    if self.pr_head() != head or self.remote_head() != head or self.git("rev-parse", "HEAD") != head:
                        raise DeliveryError("Final head drift invalidated passing CI evidence.",
                                            kind="dependency", reason_code="pr-head-changed")
                    self.verify_committed_content()
                    if self.draft_lifecycle() and self.result["pr_owned"] and self.result["pr_draft"]:
                        if published or self._was_ready:
                            raise DeliveryError("PR was redrafted after being ready; preserving that change. Explicitly mark it ready if intended, then resume.",
                                                kind="infrastructure", reason_code="pr-readiness-changed")
                        if verify_only:
                            self.result.update(status="pending", kind="infrastructure", checked_head_sha=head,
                                               reason_code="publication-required",
                                               summary="Required checks passed, but the owned draft requires normal delivery publication.")
                            break
                        self.publish_owned_draft(head)
                        published = True
                        policy = self.required_policy()
                        if (policy["required_checks"] != final_policy["required_checks"]
                                or policy["status"] != final_policy["status"]):
                            raise DeliveryError("Required-check policy changed during publication.",
                                                kind="dependency", reason_code="required-policy-changed")
                        self.result["check_policy"] = policy
                        continue
                    if not verify_only:
                        self.reconcile_managed_section(
                            "Required CI passed on the final head; the PR state was verified."
                            if required else
                            "No required CI checks are configured; the PR state was verified.", head)
                    self.result.update(status="complete", kind=None, checked_head_sha=head,
                                       reason_code=None,
                                       summary="Required checks passed on the final head." if required else "No required checks are configured; local validation remains mandatory.")
                    break
                if self.clock() >= deadline:
                    draft_wait = bool(self.draft_lifecycle() and self.result["pr_owned"] and self.result["pr_draft"])
                    if not verify_only:
                        self.reconcile_managed_section(
                            "Required CI is pending or missing on the draft; workflows may require a ready PR before they run."
                            if draft_wait else "Required CI is pending or missing; delivery is not complete.", head)
                    self.result.update(status="pending", kind="infrastructure", reason_code="required-ci-pending",
                                       summary=("Required CI checks are pending or missing on the draft; workflows may require a ready PR before they run."
                                                if draft_wait else "Required CI checks are pending; delivery is not complete."))
                    break
                self.sleep(min(10, max(0, deadline - self.clock())))
        except DeliveryError as error:
            self.result.update(status="blocked", kind=error.kind, summary=str(error), reason_code=error.reason_code)
            if error.evidence_path:
                self.result["evidence_path"] = error.evidence_path
        except (KeyError, TypeError, ValueError, OSError) as error:
            self.result.update(status="blocked", kind="infrastructure", reason_code="indeterminate-delivery-evidence",
                               summary=f"Delivery evidence/configuration is indeterminate ({type(error).__name__}); inspect logs.")
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
