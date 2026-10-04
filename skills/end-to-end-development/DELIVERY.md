# GitHub delivery effects

Read this whenever using normal GitHub PR completion. Requesting the skill for a repository change includes ordinary task-scoped commit, push, and PR creation/update without a second invitation or approval, subject to explicit opt-outs, repository policy, exact-approval requirements, and tool/sandbox permissions. `EffectGuard` protects publication from duplicate or conflicting retries; it does not grant authorization, choose what to build, repair source, or orchestrate development.

Establish the appropriate task branch, remote, repository, and base before mutation. Reuse and update an existing open task PR rather than duplicate it. No-change requests need evidence, not empty PRs; explicit local-only/no-push/no-PR instructions limit delivery to the actual permitted result. Missing authentication or remote, ambiguous destination, denied permission, or failed required verification/review must be reported as blocked or partial with the next needed action, not silently treated as local-only completion. Continue useful local work while remote delivery is blocked.

The standard-library helper requires Python 3.11+, Git, and authenticated `gh`. Finish applicable local verification and review before publication. Keep unrelated user changes intact.

## Review the exact publication set

The agent decides which changes belong to the request. A path allowlist cannot distinguish task edits from pre-existing work in the same file. Isolate the task in a suitable checkout or stage only its intended changes; preserve everything else. Commit locally with the repository's normal tools, inspect the resulting commits (including hook changes), and finish the relevant checks and independent review against that exact head. The guard publishes reviewed commits; it never stages files or creates commits.

Observe the selected remote's base and task branch heads. Use a full checkout without replacement refs or grafts: those can hide ancestry that would still be sent by a push. Fetch missing history through the established repository workflow; preserve the user's original checkout when isolation is needed. Record `expected_base_head` and `expected_remote_head` (null only when the task branch is absent). Enumerate the candidate commits with:

```bash
git -C "$WORKTREE" rev-list "$REVIEWED_HEAD" --not "$EXPECTED_BASE_HEAD" "$EXPECTED_REMOTE_HEAD" --
```

Omit the `"$EXPECTED_REMOTE_HEAD"` argument for a new branch. Inspect the full changes and metadata of every candidate commit, including unpublished commits before the task baseline and changes later reverted. Only then record their exact hashes in `reviewed_commits`. Copying a candidate list is not a scope review. An unexpected commit needs investigation or isolation of the task; never silently include it, discard user work, or rewrite history to make the guard pass.

Resolve `SKILL_DIR` to this skill directory and capture the verified content fingerprint after committing:

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
    "reviewed_head": "<exact locally reviewed commit>",
    "expected_base_head": "<observed remote base commit>",
    "expected_remote_head": null,
    "reviewed_commits": ["<each reviewed outgoing commit>"],
    "task_files": ["src/changed.py", "tests/test_changed.py"],
    "expected_fingerprint": "<fingerprint captured after verification>",
    "pr_title": "Implement the requested behavior",
    "pr_body": "Describe the problem, change, and actual verification.",
    "git_write_timeout_seconds": 300,
    "check_timeout_seconds": 1800
  }
}
```

`task_files` inventories the final task diff, including deleted and renamed paths; it is not an authorization mechanism. The reviewed head and outgoing commit set bind publication to the agent's scope review. The helper requires committed content and refuses changed fingerprints, unexpected outgoing commits or remote heads, and environment credential paths anywhere in outgoing history. Those path checks are limited safeguards, not a general secret scanner; the agent must still inspect content and run repository-required secret checks.

Fingerprinting reads current files without trusting cached index stats, `assume-unchanged`, or `skip-worktree`. Intentionally absent sparse-checkout paths retain their indexed content; this does not claim that omitted files were exercised locally. The real index is preserved. Local or initialized submodule changes must be committed and reviewed before publication.

An existing PR is checked before pushing and again afterward. Publication pushes the reviewed commit hash with automatic tag and submodule pushes disabled. Submodule publication is a separate effect requiring its own authorized destination and review. Retrying after an interrupted push may find the exact reviewed head already remote; it observes that state without pushing again.

Older proposals without the reviewed head, commit set, and remote anchors are refused before publication. Do not silently populate these fields from current state: recover and review the intended scope first. Reconcile any indeterminate effects with the original helper before upgrading an in-flight task; completed receipts remain historical observations.

The selected remote's fetch and push destinations must resolve to the declared GitHub repository. For forks, GitLab, or another forge, use its established tooling with equivalent safety checks; do not rewrite remotes to fit this helper.

`pr_title` and `pr_body` supply a new PR's initial prose. Reusing a PR preserves its existing title and body; changing these proposal fields does not rewrite them. The optional owned-draft lifecycle updates only its managed validation section. Any separately authorized prose update must inspect and preserve human edits.

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

Ordinary PR-default task authorization covers scoped commit/push/PR delivery to an established, unambiguous destination; it does not require separate user confirmation. Set `approval_required` when repository instructions require an exact publication decision or a proposed external effect exceeds the authorized task scope. Obtain that approval before mutation; an explicit opt-out is not permission to publish. Tool/sandbox permissions remain enforced. Never infer authorization for merge, deployment, migrations, permissions changes, tracker writes, creating a remote repository, or destructive work.

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

- Exit **0 / `complete`**: local, pushed, pull-request, and checked revisions agree; required checks passed or positive policy evidence established that none are configured. This proves publication, not mergeability; the watch below still applies.
- Exit **8 / `pending`**: the effect awaits external state or its prior outcome is indeterminate. Keep any PR URL visible. For an indeterminate outcome, recover the proposal through `inspect` if necessary and call `ensure` again with that exact proposal before attempting a revision.
- Exit **9 / `decision-required`**: exact approval is needed before intent is recorded.
- Exit **1 / `stopped`**: the attempt reached a known non-success state and released target ownership. Inspect `reason_code` and the receipt. Fix related source only after understanding the evidence, then revalidate and create a revised effect proposal if content changed.

A created PR alone does not prove verified success. Required checks must pass; pending, missing, failed, skipped, neutral, cancelled, unknown, or changed-head required-check evidence cannot complete verified delivery. Optional checks may finish skipped or neutral, but failures, cancellations, and pending checks still block watcher completion. Empty check output or permission errors do not prove that checks are absent. Human changes to pull-request ownership, content, destination, or readiness are preserved and surfaced as conflicts rather than overwritten.

## Watch until mergeable

`ensure` gates only on required checks, and with none configured it completes as soon as the PR exists. It does not wait for other checks or observe conflicts and merge requirements, so the PR watcher from [DEVELOPMENT.md](DEVELOPMENT.md) takes over once the PR exists. A short `check_timeout_seconds` keeps publication from delaying that handoff.

Use the read-only observer for the acceptance decision. It reuses the proposal's verified head and observes fresh required-check policy, all checks, remote/PR heads, readiness, conflicts and review requirements; it never pushes, edits, or marks a PR ready:

```bash
python3 "$SKILL_DIR/scripts/effect_guard.py" observe-pr \
  --input "$TASK_DIR/api-pr-effect.json" \
  --output "$TASK_DIR/api-pr-readiness.json"
```

Exit 0 / `mergeable` is the watcher's acceptance result. Exit 8 / `pending` requires another observation; exit 1 / `blocked` reports a reason to investigate. Required checks must pass; optional skipped/neutral checks are acceptable. A missing required check never passes. No observed checks defaults to pending because checks may not have registered; add `--no-checks-expected` only after inspecting repository workflows and establishing that none apply to this PR. This assertion cannot waive required checks. `UNKNOWN` merge state is pending. The observer does not use stored completion receipts as current evidence.

- A check with `state: failed` or `cancelled`, or `merge_state: UNSTABLE`: read the failed steps with `gh run view "$RUN_ID" --log-failed`, taking the run ID from the check's `url` when it identifies a GitHub Actions run, and fix the cause. For external checks, inspect their linked provider evidence. Use `gh run rerun "$RUN_ID" --failed` only for an infrastructure flake unrelated to the change. A required `skipped` check (including a neutral conclusion) also blocks completion; determine why it did not run rather than treating it as a pass.
- `merge_state: DIRTY` or `BEHIND`: fetch the base, merge it into the task branch, resolve conflicts, commit the merge, and verify again.
- `merge_state: BLOCKED` or `reason_code: review-required`: identify the unmet requirement. Address `review_decision: CHANGES_REQUESTED` feedback within scope; report `REVIEW_REQUIRED` and any other requirement only a human can satisfy as the remaining gate.
- `reason_code: pr-draft`: `ensure` publishes an owned draft once its required checks pass; report a human-drafted PR rather than marking it ready.

Publish each fix as a revised effect proposal: commit locally, verify and review the resulting head, capture a new fingerprint, add newly touched paths to `task_files`, and refresh the reviewed commit set and remote anchors. After merging the base, use the merged base commit as `baseline`. The previous effect must be settled first: one that published and then saw red CI in the same run stays indeterminate, so re-run its identical proposal until it settles before changing source. `ensure` then reuses the open PR and fast-forwards the branch to the reviewed head. Task authorization covers these scoped fixes and flake reruns; never merge, enable auto-merge, approve, dismiss reviews, rebase, or force-push.

Return each PR URL with its final head, check results and merge state, the fixes made, and any blocker with the next needed action. A pending, red, conflicting or blocked PR is reported as such, never as complete.
