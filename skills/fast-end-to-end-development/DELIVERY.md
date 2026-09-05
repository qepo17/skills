# Scripted GitHub delivery

Use Python 3.11+, Git, and an authenticated `gh` CLI. This helper performs mechanical delivery only: the coordinator must first verify acceptance criteria, local tests, the independent review/revision, applicable browser evidence, and the task-only diff. It does not authorize a merge, deployment, migration, or source fix.

## Inputs

After passing validation in the dedicated worktree, capture its content fingerprint:

```bash
python3 "$SKILL_DIR/scripts/delivery_tools.py" fingerprint "$WORKTREE"
```

Record that exact value with the passing checks. Do not calculate a new fingerprint after unvalidated source edits merely to make delivery pass. An identical delivery commit preserves the fingerprint; changed content invalidates it.

Write `$RUN_DIR/delivery-input-1.json` from the accepted artifacts:

```json
{
  "repository": "github.com/owner/repository",
  "worktree": "/absolute/dedicated/worktree",
  "baseline": "<recorded 40- or 64-character baseline SHA>",
  "base_branch": "main",
  "branch": "feat/request-slug",
  "task_files": ["src/changed-file.py", "tests/test_changed_file.py"],
  "expected_fingerprint": "<64-character validated content fingerprint>",
  "commit_message": "feat: implement the requested behavior",
  "pr_title": "Implement the requested behavior",
  "pr_body": "## Problem\n...\n\n## Solution\n...\n\n## Tests\n...\n\n## Review and risks\n...",
  "log_dir": "/absolute/run-directory/logs/delivery-1",
  "check_timeout_seconds": 1800
}
```

Replace placeholders with actual values. `task_files` is the complete explicit inventory relative to the worktree, including renamed/deleted paths where applicable. Evidence and output must remain outside the project. Keep secrets and environment values out of all inputs, PR text, and logs.

`check_timeout_seconds` is 0–1800. Zero observes checks once; it does **not** waive CI. The default is 1800 seconds, with bounded individual Git/forge requests and a ten-second polling interval.

## Execute

```bash
python3 "$SKILL_DIR/scripts/delivery_tools.py" deliver \
  --input "$RUN_DIR/delivery-input-1.json" \
  --output "$RUN_DIR/delivery-output-1.json"
```

The output path must not already exist. On retry, use a new input/output filename and keep earlier evidence. Existing Git/PR side effects are discovered rather than blindly repeated. The helper never force-pushes, amends unrelated history, or stages an unlisted path. It audits the real index separately from working files and resolves effective fetch/push URLs, including rewrites and multiple push destinations, before side effects. Unrelated changes or hook-induced worktree/index/commit changes stop delivery without inheriting prior validation.

After interruption, refresh previously complete evidence rather than trusting the old JSON. Use the same validated input and a new output path with `deliver --verify-only`; this mode cannot commit, push, or create a PR. A missing/moved PR or pushed head blocks instead of being overwritten. If delivery was interrupted before it completed, ordinary `deliver` reconciles existing side effects.

## Outcomes

| Exit | JSON status | Coordinator action |
| --- | --- | --- |
| 0 | `complete` | Record the PR, commit, final checked head, and required-check policy. Finish only if the other workflow gates also passed. |
| 8 | `pending` | Required checks are missing/running or exceeded the polling budget. Preserve evidence; rerun delivery later against unchanged validated content. No code-fix allowance is consumed. |
| 1 | `blocked` | Inspect `kind`, `summary`, and command evidence. One compatible change-related CI fix is allowed; authentication/permission/infrastructure/decision failures are not permission to rewrite source. |

Invocation/configuration errors also exit nonzero; absence of a result file never implies success.

The result includes `head_sha`, `pushed_head_sha`, `checked_head_sha`, `check_policy`, individual `checks`, command exit codes/log paths, elapsed seconds, and the PR URL. Complete required-check evidence is bound to the final head and rediscovered policy. Required checks that failed, were cancelled, or were skipped do not pass. A changed head or policy invalidates the previous observation.

Policy discovery combines branch protection and applicable branch rulesets. `check_policy.status: not-configured` means a positive query found no required checks; report that fact explicitly, not "CI passed." An empty check rollup or a permission error is not equivalent. Repositories with no required checks still need all planned local validation and review.

This helper supports GitHub.com only. For other forges, retain the established CLI path with equivalent evidence and explicitly report which executor was used; unknown policy or unsupported final-head verification blocks completion.
