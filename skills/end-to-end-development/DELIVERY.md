# GitHub delivery

Read this when the requested outcome includes a PR. The standard-library helper requires Python 3.11+, Git, and authenticated `gh`. Finish applicable local verification and review before pushing. Keep unrelated user changes intact.

## Prepare the input

Discover the intended GitHub repository, configured remote, task branch and base. The helper supports a same-repository PR where the selected remote's fetch and push URLs resolve to that repository. For forks or another forge, use its established CLI with equivalent checks; do not rewrite remotes to fit the helper.

Capture verified content with:

```bash
python3 "$SKILL_DIR/scripts/delivery_tools.py" fingerprint "$WORKTREE"
```

Write an input next to the task record, outside source:

```json
{
  "repository": "github.com/owner/repository",
  "remote": "upstream",
  "worktree": "/absolute/task/checkout",
  "baseline": "<recorded baseline commit>",
  "base_branch": "main",
  "branch": "feat/request-slug",
  "task_files": ["src/changed.py", "tests/test_changed.py"],
  "expected_fingerprint": "<fingerprint captured after verification>",
  "commit_message": "Fix the requested behavior",
  "pr_title": "Fix the requested behavior",
  "pr_body": "Describe the problem, change and actual verification.",
  "log_dir": "/absolute/task-record/logs/delivery-1",
  "git_write_timeout_seconds": 300,
  "check_timeout_seconds": 1800
}
```

Use actual values. `task_files` includes every task change, including deleted/renamed paths. The helper refuses unrelated index/worktree changes, credential files, mismatched destinations, or changed verification fingerprints. Use an isolated checkout when necessary; never discard or stage unrelated work to satisfy this check. If the request is already satisfied, report the evidence without calling delivery on an empty diff.

`remote` is a configured remote name, not a URL. `git_write_timeout_seconds` bounds add/commit/push, including hooks (integer 1–1800). Read requests remain bounded at 30 seconds. Omitted fields preserve older inputs: `origin` and a 30-second Git write timeout. `check_timeout_seconds` is 0–1800; zero observes CI once and does not waive it. Keep the same remote and verified identity on retries.

## Choose the PR lifecycle

For normal authorized publication, omit `pr_lifecycle`: the helper creates a ready PR and verifies CI. A ready PR is not a passing-check claim. This supports repositories whose required workflows run only on ready PRs.

If the requested outcome is a draft that becomes ready after verified CI, add `pr_lifecycle: "draft-until-verified"`, `run_id`, and a stable absolute `pr_intent_path` outside source. Confirm required workflows run on drafts first. This optional lifecycle preserves nonce-bound ownership, human edits, and later human redrafting. Do not choose it for a draft-only deliverable: it publishes the owned draft after green CI. For a draft-only request, use the forge CLI and verify the requested draft state without promoting it.

The optional managed validation section is engine-owned. A human edit inside it blocks that lifecycle; preserve the edit and resolve the conflict explicitly. Existing unowned PR bodies and readiness are preserved. Default delivery does not add a managed section.

## Execute and reconcile

```bash
python3 "$SKILL_DIR/scripts/delivery_tools.py" deliver \
  --input "$TASK_DIR/delivery-input-1.json" \
  --output "$TASK_DIR/delivery-output-1.json"
```

Use a new input/output and log directory for each attempt. Keep a draft lifecycle's `pr_intent_path` stable across retries. The helper audits effective remote destinations, stages exact task paths, preserves unrelated history, and reconciles existing commits/PRs. Hook-induced content changes require revalidation. It never force-pushes.

After an interrupted attempt, inspect its evidence and current Git/forge state before retrying. Ordinary delivery reconciles incomplete side effects. To refresh a previously delivered unchanged revision, add `--verify-only`; it never commits, pushes, creates/edits a PR, or changes readiness. A green owned draft returns `publication-required` until a normal authorized delivery publishes it.

## Interpret the result

- Exit **0 / complete**: local, pushed and checked heads match; required CI passed or positive policy discovery found none configured.
- Exit **8 / pending**: keep the PR URL visible and inspect `reason_code`. Continue monitoring against the same verified content. A polling timeout is not a code failure.
- Exit **1 / blocked**: inspect the actual failure and logs. Fix related code within scope, revalidate, capture the new fingerprint, and reconcile the same PR. Preserve unrelated failures and genuine access/scope blockers. There is no one-fix cap in coordinator-led development.

Required-check discovery includes branch protection and applicable rulesets. Empty check output or permission errors do not establish that no checks are configured. Pending, missing, failed, skipped, cancelled, unknown, or changed-head/policy evidence cannot complete verified delivery. Report positive absence as “not configured.”

Record the PR URL, commit, checked head, actual draft state, verification outcome and any warning in the task record. The machine output and logs are evidence; no separate delivery prose file is required.

Existing LangGraph runs retain their recorded draft, retry, approval and validation policy. Their engine constructs helper inputs and owns recovery; the coordinator-led choices above do not amend an active run.
