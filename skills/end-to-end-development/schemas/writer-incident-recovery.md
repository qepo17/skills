# Overlapping-writer incident recovery

`recover-writer-incident` is an explicitly authorized, one-shot compatibility command, not an ordinary retry or validation exception. It applies only to a single-repository, approved implementation run with validation/delivery policy version 1 and pinned Herdr execution.

The recognized incident is exact: packet attempt 1 timed out with a retained, unsettled handle; attempt 2 produced an accepted infrastructure-blocked result with every check `not-run`; an unsafe external resume subsequently overwrote that accepted output. The original writer later produced a complete candidate. All other accepted references must still validate. Legacy runs, different stages/packets/attempts, missing timeout proof, failed/partial candidates, unrelated corruption, or unresolved recorded handles are refused.

## Request and authorization

Capture the following JSON read-only. Do not refresh hashes to bypass a stale request:

```json
{
  "run_id": "the-existing-run-id",
  "repo_id": "api",
  "source_action_id": "implement:api:API-PACKET-001:attempt-1",
  "damaged_action_id": "implement:api:API-PACKET-001:attempt-2",
  "run_sha256": "sha256-of-current-raw-run-json",
  "source_sha256": "sha256-of-the-unaccepted-late-result",
  "damaged_sha256": "sha256-of-the-overwritten-blocked-result",
  "plan_review_sha256": "the-still-approved-whole-bundle-sha256",
  "repository_state": {
    "fingerprint": "current-worktree-content-sha256",
    "head": "current-git-head",
    "branch": "the-existing-task-branch",
    "index_sha256": "sha256-of-git-ls-files--stage--z"
  }
}
```

`repository_state` uses `workflow_tools.repository_state`; Git's volatile index stat cache is not identity. The canonical request digest is SHA-256 of UTF-8 `json.dumps(request, sort_keys=True, separators=(",", ":"))`. Pass that digest with `--request-sha256` and the explicit user authorization with `--text` (`yes`, `approved`, or `authorized`). Optional `--context` is separately labelled coordinator interpretation. The command must not be invoked without user authorization of both engine repair and this guarded recovery.

```bash
"$ORCHESTRATOR" recover-writer-incident "$RUN_DIR" \
  --input "$REVIEWED_REQUEST" --request-sha256 "$REVIEWED_REQUEST_SHA256" \
  --text "$EXACT_USER_AUTHORIZATION" --context "$SEPARATE_INTERPRETATION" \
  --no-drive
```

`--no-drive` applies the guarded transition without opening or editing the SQLite checkpoint or launching a worker. Inspect validated status, then use ordinary `run`/`resume`. Without it, the CLI continues through the existing graph. An identical applied request returns `already-applied` without advancing.

## Preservation and handle proof

The command snapshots raw run/agent records, both output files, and the misleading historical supervisor records under `logs/incidents/writer-recovery-<request-hash>/`. It pins relevant manifests and existing evidence. These are historical preservation snapshots, **not retroactive passing checks**.

Cleanup queries the live Herdr registry rather than trusting a reused name/record. Only known task workers whose cwd, name, workspace, pane, session identity, and `done` state match may close. Unknown, working, mismatched or remaining handles fail closed. Git/source/run/output identity is rechecked after cleanup. Old worker history and source remain untouched.

The immutable `recovery.json` (maximum 128 KiB) preserves the original unavailable accepted reference as `invalidated_reference`; the current overwritten bytes are pinned separately. The command removes only that unavailable pointer from `accepted_artifacts`. It never replaces its hash with the new bytes or accepts the late source candidate. All unaffected accepted evidence, assignments, approvals, baselines, policies and retry/review/fix allowances remain unchanged. The current source-writer intent is cleared only after positive cleanup, in the existing implement phase. A failure before projection commit leaves the run unrecovered; preserved snapshots remain available.

`run.writer_incident_recoveries` pins this record. `run.writer_incident_attempts` pins the single derived verification assignment before launch. Later loads validate preserved hashes; a quarantined action cannot reappear in accepted artifacts.

## Required fresh verification

The graph's existing implement node creates one read-only `packet-verification` action with a `writer_incident` reference instead of `external_repair` (never both). It retains the original packet/tasks and exact check IDs/commands, has its own output/log paths, and grants no project/Git/forge writes.

The verifier independently inspects the **combined current source**, not just the late writer's narrative, against the approved packet and requirements. It runs every assigned check freshly. Compatible inspected work plus passing new checks can complete the packet. Material scope changes, unfinished source, actual check failures, verifier writes or rejected verification evidence remain blocked; no source replay or new fix allowance is granted.

Remaining packets, complete effective validation, independent review and all delivery/CI gates remain mandatory. No new LangGraph phase, replacement run, policy upgrade, waiver or budget reset is introduced.
