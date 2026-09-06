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

New durable workflows may opt into draft publication by adding both fields below. Omitting them preserves the legacy behavior above, including creation of a ready PR.

```json
{
  "pr_lifecycle": "draft-until-verified",
  "run_id": "<stable durable-run identity>"
}
```

`run_id` is required. Before creating a PR, the helper atomically records local creation intent with repository/branch/base/run identity and a random nonce. Ownership requires both this intent and its nonce-bound hashed PR marker; a public run-ID marker alone never authorizes adoption. Optional absolute `pr_intent_path` selects a stable file outside the project (default: `log_dir/pr-creation-intent.json`). Keep that path across retries with new log directories. A sibling `.ready.json` records observed readiness; later human redrafting is preserved, not silently undone.

The marked validation section includes optional `local_validation_summary` supplied by the coordinator. Its content hash detects human edits: conflicts block before publication or body writes, and text outside the section is preserved. A PR without proven ownership keeps its body and draft/readiness state. `verify_only` may write local observation logs/journals, never Git or forge state.

## Execute

```bash
python3 "$SKILL_DIR/scripts/delivery_tools.py" deliver \
  --input "$RUN_DIR/delivery-input-1.json" \
  --output "$RUN_DIR/delivery-output-1.json"
```

The output path must not already exist. On retry, use a new input/output filename and keep earlier evidence. Existing Git/PR side effects are discovered rather than blindly repeated. The helper never force-pushes, amends unrelated history, or stages an unlisted path. It audits the real index separately from working files and resolves effective fetch/push URLs, including rewrites and multiple push destinations, before side effects. Unrelated changes or hook-induced worktree/index/commit changes stop delivery without inheriting prior validation.

After interruption, refresh previously complete evidence rather than trusting the old JSON. Use the same validated input and a new output path with `deliver --verify-only`; this mode cannot commit, push, or create a PR. A missing/moved PR or pushed head blocks instead of being overwritten. If delivery was interrupted before it completed, ordinary `deliver` reconciles existing side effects.

With `draft-until-verified`, `--verify-only` also cannot edit the PR body or change readiness. Green required CI on an owned draft returns `pending` with `reason_code: publication-required`; the coordinator must authorize an ordinary delivery run. Only an ordinary run may publish an owned draft, and only after current required checks pass or the forge positively reports that none are configured. The helper then re-observes the PR head, required-check policy, and checks after publication before reporting completion.

## Outcomes

| Exit | JSON status | Coordinator action |
| --- | --- | --- |
| 0 | `complete` | Record the PR, commit, final checked head, and required-check policy. Finish only if the other workflow gates also passed. |
| 8 | `pending` | Inspect `reason_code`. `required-ci-pending` means required checks are missing/running or exceeded the polling budget; `publication-required` means read-only verification proved an owned draft is green but did not publish it. Preserve evidence and rerun against unchanged validated content. No code-fix allowance is consumed. |
| 1 | `blocked` | Inspect `kind`, `reason_code`, `summary`, and command evidence. `required-ci-failed` is a factual delivery gate, not proof that this task caused the failure or permission to waive it. Authentication/permission/infrastructure/decision failures are not permission to rewrite source. |

Invocation/configuration errors also exit nonzero; absence of a result file never implies success.

The result includes `head_sha`, `pushed_head_sha`, `checked_head_sha`, `check_policy`, individual `checks`, command exit codes/log paths, elapsed seconds, the PR URL, `pr_draft`, `pr_owned`, and `reason_code`. `pr_draft` is the last observed boolean state, or `null` before a PR was observed. `pr_owned` is true only with matching local creation intent and its nonce-bound marker on the expected open PR. `creation_intent` exposes the local hashed evidence reference when ownership is established; `ownership_observation` references a hash-pinned snapshot of the actual PR identity, body, and readiness. These permit the durable coordinator to validate fallback and command ownership identically. Failure outputs retain the latest factual head, policy, checks, and PR state that were actually observed.

An owned draft with red, cancelled, skipped, unknown, pending, or missing required CI remains unverified and is not published. If required workflows appear not to run on drafts, the bounded pending result calls out that obstacle; the helper does not make the PR ready merely to trigger CI. A person may change readiness externally, after which either mode can re-observe it. A pre-existing/user-owned draft may be reported `complete` when every verification obligation passes, but `pr_draft` remains true so the output does not claim it is ready for review.

Complete required-check evidence is bound to the final head and rediscovered policy. Required checks that failed, were cancelled, skipped, or had an unknown conclusion do not pass. A changed head or policy invalidates the previous observation, including changes detected after publication.

Policy discovery combines branch protection and applicable branch rulesets. `check_policy.status: not-configured` means a positive query found no required checks; report that fact explicitly, not "CI passed." An empty check rollup or a permission error is not equivalent. Repositories with no required checks still need all planned local validation and review.

This helper supports GitHub.com only. For other forges, retain the established CLI path with equivalent evidence and explicitly report which executor was used; unknown policy or unsupported final-head verification blocks completion.
