# GitHub delivery effects

Read this only when the user requested a GitHub pull request. `EffectGuard` protects publication from duplicate or conflicting retries; it does not grant authorization, choose what to build, repair source, or orchestrate development.

The standard-library helper requires Python 3.11+, Git, and authenticated `gh`. Finish applicable local verification and review before publication. Keep unrelated user changes intact.

## Capture verified content

Resolve `SKILL_DIR` to this skill directory and capture the exact content verified:

```bash
python3 "$SKILL_DIR/scripts/effect_guard.py" fingerprint "$WORKTREE"
```

Write an effect proposal next to the task record, outside source:

```json
{
  "kind": "github-pull-request",
  "change_set": "request-slug",
  "approval_required": false,
  "delivery": {
    "repository": "github.com/owner/repository",
    "remote": "origin",
    "worktree": "/absolute/task/checkout",
    "baseline": "<recorded baseline commit>",
    "base_branch": "main",
    "branch": "feat/request-slug",
    "task_files": ["src/changed.py", "tests/test_changed.py"],
    "expected_fingerprint": "<fingerprint captured after verification>",
    "commit_message": "Implement the requested behavior",
    "pr_title": "Implement the requested behavior",
    "pr_body": "Describe the problem, change, and actual verification.",
    "git_write_timeout_seconds": 300,
    "check_timeout_seconds": 1800
  }
}
```

`task_files` includes every task change, including deleted and renamed paths. The helper refuses unrelated index/worktree changes, credential files, mismatched destinations, or changed verification fingerprints. Use an isolated checkout when necessary; never discard or stage unrelated work to satisfy delivery.

The selected remote's fetch and push destinations must resolve to the declared GitHub repository. For forks, GitLab, or another forge, use its established tooling with equivalent safety checks; do not rewrite remotes to fit this helper.

## Ensure and reconcile

Use one journal for the task or change set. The guard also maintains a shared target registry under `${XDG_STATE_HOME:-$HOME/.local/state}/end-to-end-development/` so separate tasks cannot concurrently own the same repository branch:

```bash
python3 "$SKILL_DIR/scripts/effect_guard.py" ensure \
  --journal "$TASK_DIR/effects.sqlite" \
  --input "$TASK_DIR/api-pr-effect.json" \
  --output "$TASK_DIR/api-pr-outcome.json"
```

The effect identity is derived from its kind, target, desired content, and requested pull-request state. Runtime timeouts do not change that identity. Before mutation, the guard records durable intent and locks the target repository branch. The delivery adapter then observes existing commits and pull requests before applying anything.

Calling `ensure` again with the identical proposal is the resume mechanism. A completed effect returns its stored receipt without contacting GitHub. An interrupted effect is reconciled through the same delivery adapter. A different effect—or the same effect from another task journal—targeting a branch with an indeterminate prior effect stops with `target-conflict`; its outcome identifies the blocking effect and original journal to reconcile first.

The journal stores the bounded canonical proposal as well as its digest. `inspect` returns that proposal for incomplete effects, so recovery does not depend on preserving the original input file.

Use read-only inspection when needed:

```bash
python3 "$SKILL_DIR/scripts/effect_guard.py" inspect \
  --journal "$TASK_DIR/effects.sqlite" \
  "$EFFECT_ID" \
  --output "$TASK_DIR/api-pr-inspection.json"
```

## Exact approval when required

Ordinary requested PR publication does not need a second approval. Set `approval_required` only when the user has not authorized the consequential effect or when repository instructions demand an exact publication decision.

The first `ensure` returns `decision-required` with a proposal digest and performs no external work. After the user approves that exact proposal, write:

```json
{
  "proposal_digest": "<digest returned by ensure>",
  "actor": "user",
  "text": "<the user's exact approval wording>"
}
```

Then repeat `ensure` with `--approval "$TASK_DIR/approval.json"`. A stale digest is rejected. The accepted approval is stored with the intent, so identical retries and receipt reads do not require the approval file again.

## Multi-repository delivery

Use one effect per repository and the same `change_set` value. Repository effects settle independently; no tool can make separate Git repositories and pull requests atomic. Publish in dependency order when one pull request depends on another, and cross-link their bodies where helpful.

If one effect completes and another stops, preserve the completed receipt and resolve or report only the remaining repository. Re-running the completed proposal never duplicates its pull request.

## Outcomes

- Exit **0 / `complete`**: local, pushed, pull-request, and checked revisions agree; required checks passed or positive policy evidence established that none are configured.
- Exit **8 / `pending`**: the effect awaits external state or its prior outcome is indeterminate. Keep any PR URL visible. For an indeterminate outcome, recover the proposal through `inspect` if necessary and call `ensure` again with that exact proposal before attempting a revision.
- Exit **9 / `decision-required`**: exact approval is needed before intent is recorded.
- Exit **1 / `stopped`**: the attempt reached a known non-success state and released target ownership. Inspect `reason_code` and the receipt. Fix related source only after understanding the evidence, then revalidate and create a revised effect proposal if content changed.

Pending, missing, failed, skipped, cancelled, unknown, or changed-head check evidence cannot complete verified delivery. Empty check output or permission errors do not prove that checks are absent. Human changes to pull-request ownership, content, destination, or readiness are preserved and surfaced as conflicts rather than overwritten.
