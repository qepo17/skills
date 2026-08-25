# Delivery artifact (`delivery`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Audit the baseline diff and untracked files, preserve pre-existing changes, commit only task files, push the assigned branch, create/update the PR against the recorded base, and monitor required checks.

Record branch/base, commit SHAs, PR URL, and every observed check with name, URL, required flag, terminal state, and evidence log. A complete delivery has at least one commit, a PR URL, no blockers, and all required checks passed. Authentication, permission, and infrastructure failures block rather than retry indefinitely.

Validate before returning:

```bash
python3 <validator_path> delivery <output_artifact>
```
