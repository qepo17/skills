# Delivery artifact (`delivery`)

Before any work, read [SKILL.md — Validation rules](../SKILL.md#validation-rules). It contains the shared limits, required fields, evidence rules, and role boundaries; this file is a stage-specific reminder.

The graph executes new GitHub `execution_mode: command` assignments through `scripts/delivery_tools.py`; no delivery worker is launched. Worker assignments remain supported for other forges and legacy runs.

For a worker assignment, initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Audit the baseline diff and untracked files, preserve pre-existing changes, commit only task files, push the assigned branch, create/update the PR against the recorded base, and monitor required checks.

Record branch/base, commit SHAs, PR URL, and every observed check with name, URL, required flag, terminal state, and evidence log. A complete delivery has at least one commit, a PR URL, no blockers, and all required checks passed. Authentication, permission, and infrastructure failures block rather than retry indefinitely.

For version-2 assignments, also provide `head_sha`, `pushed_head_sha`, `checked_head_sha`, and `check_policy`. A complete result must bind all three heads to the final delivered commit and actual worktree HEAD/base. `check_policy` contains `status` (`required`, `not-configured`, or blocked-only `unknown`), `required_checks` (`name`, nullable `app_id`), and non-empty hashed-file `evidence` for a complete result. Every required identity must appear as a passing required check. Scripted results also hash-pin `command_evidence` and retain their `delivery_outcome`.

An empty check rollup does not establish absence of required checks. Positively discovered absence is `not-configured`, not "CI passed." Pending/missing/timed-out checks are not completion and do not consume a source-fix allowance; represent them as blocked with infrastructure evidence. Changed head or required-check policy invalidates earlier observations. Required skipped/cancelled checks do not pass. Unsupported policy discovery blocks.

Use the [blocker contract](blockers.md) for a stage that cannot finish. Change-related failures may route to one compatible pipeline fix; delivery itself must never edit project files.

Validate before returning:

```bash
python3 <validator_path> delivery <output_artifact>
```
