# Delivery artifact (`delivery`)

The graph executes new GitHub `execution_mode: command` assignments through `scripts/delivery_tools.py`; no delivery worker is launched. Worker assignments remain supported for other forges and legacy runs.

For a worker assignment, initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Audit the baseline diff and untracked files, preserve pre-existing changes, commit only task files, push the assigned branch, create/update the PR against the recorded base, and monitor required checks. Delivery-policy version 1 uses `pr_lifecycle: draft-until-verified`: after local/review/integration gates, create a run-owned draft and retain its URL while CI is pending or failed. Publish it only during a normal engine-authorized action after current required CI is green (or positively not configured), then re-observe PR head, required-check policy, checks, and actual readiness.

Record branch/base, commit SHAs, PR URL, and every observed check with name, optional `app_id`, URL, required flag, terminal state, and evidence log. Policy-version-1 output also records actual nullable `pr_draft`, boolean `pr_owned`, and typed nullable `reason_code`; do not infer ownership or readiness. A complete delivery has at least one commit, a PR URL, no blockers, and all required checks passed. A preserved user-owned draft may be complete while `pr_draft: true`; report that fact without claiming it is ready. Authentication, permission, and infrastructure failures block rather than retry indefinitely.

```json
{
  "pr_url": "https://github.com/example/project/pull/42",
  "pr_draft": true,
  "pr_owned": true,
  "delivery_outcome": "blocked",
  "reason_code": "required-ci-failed"
}
```

Owned GitHub PRs require immutable local creation intent plus a nonce-bound marker, not a predictable public marker alone. The engine keeps `pr_intent_path` stable across delivery actions. Managed content hashes preserve human edits; body conflicts block before publication, and a PR redrafted after a ready observation is not silently republished. Fallback workers use the same mechanically validated evidence, not a boolean assertion. For `pr_owned: true`, require hashed `creation_intent` at the assignment's `pr_ownership.intent_path` and hashed `ownership_observation` JSON inside its log directory. The observation contains actual `url`, `state: OPEN`, `headRefName`, `baseRefName`, boolean `isDraft`, and `body`; identity/readiness must match the artifact and pinned repository/branches, and the body must contain the intent's nonce-bound marker. Use the standard-library `delivery_tools.Delivery` intent/marker helpers before creating a draft, never to adopt an existing unowned PR. Record a sibling immutable `.ready.json` fact (`creation_intent` reference and `pr_url`) when readiness is observed. Missing/conflicting proof or later redrafting cannot authorize publication. Check logs stay under the current assignment log directory; the coordinator pins `evidence_sha256`.

These fields report the latest actual observation. Do not retain an older complete state after a newer pending/blocked observation.

For version-2 assignments, also provide `head_sha`, `pushed_head_sha`, `checked_head_sha`, and `check_policy`. A complete result must bind all three heads to the final delivered commit and actual worktree HEAD/base. `check_policy` contains `status` (`required`, `not-configured`, or blocked-only `unknown`), `required_checks` (`name`, nullable `app_id`), and non-empty hashed-file `evidence` for a complete result. Every required identity must appear as a passing required check. Scripted results also hash-pin `command_evidence` and retain their `delivery_outcome`.

An empty check rollup does not establish absence of required checks. Positively discovered absence is `not-configured`, not "CI passed." Use `reason_code: required-ci-pending` for missing/running/timed-out required checks and `required-ci-failed` for failed/skipped/cancelled/unknown required conclusions. These are factual delivery outcomes, not automatic permission to fix code; only a separate coordinator `check-remediation/fix-related` decision may spend the existing pipeline-fix cycle. Changed head or required-check policy invalidates earlier observations. Unsupported policy or draft behavior blocks explicitly.

`verify_only` is strictly read-only: never commit, push, create/edit a PR, or change readiness. Green required CI on a still-owned draft returns pending with `reason_code: publication-required`; the engine must schedule a normal delivery action for publication. Preserve a ready PR's actual state if later CI regresses. If workflows do not run on drafts, report the draft-only CI obstacle and URL without polling forever or silently publishing.

Version-1 `resume` can also read-only re-observe the exact recorded body/readiness conflict after it is resolved externally. This does not clear arbitrary decision blockers or grant source-write permission.

Use the [blocker contract](blockers.md) for a stage that cannot finish. Change-related failures may route to one compatible pipeline fix; delivery itself must never edit project files.

Validate before returning:

```bash
python3 <validator_path> delivery <output_artifact>
```
