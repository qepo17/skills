# Interrupted later-packet recovery

This opt-in transition repairs one lost implementation intent, not an application
plan or a failed validation. It requires separate explicit user authorization to
repair tooling and resume preserved unfinished work. Ordinary `resume` cannot
clear this decision blocker. Never edit canonical state or initializer output.

```bash
"$ORCHESTRATOR" recover-interrupted-packet "$RUN_DIR" \
  --input "$REVIEWED_REQUEST" --request-sha256 "$CANONICAL_JSON_SHA256" \
  --text "$EXACT_USER_AUTHORIZATION" --context "$SEPARATE_INTERPRETATION" \
  --no-drive
```

`--text` accepts an affirmative response to the specific recovery question (`yes`,
including repeated final s, `approved`, or `authorized`), never generic continuation.
Omit `--no-drive` to return directly to LangGraph. With it, inspect status before
ordinary `resume`; no worker or SQLite cursor is opened during the transition.

## Exact request

```json
{
  "run_id": "existing-run-id",
  "repo_id": "api",
  "run_sha256": "reviewed-run-json-sha256",
  "agents_sha256": "reviewed-agents-json-sha256",
  "assignment": {"path": "/run/assignments/original.json", "sha256": "reviewed-sha256"},
  "worker": {"path": "/run/supervisor/worker-original.json", "sha256": "reviewed-sha256"},
  "output": {"path": "/run/repos/api/unfinished.json", "sha256": "reviewed-sha256"},
  "repository_state": {
    "fingerprint": "current-content-sha256",
    "head": "original-baseline-commit",
    "branch": "existing-task-branch",
    "index_sha256": "staged-entry-sha256"
  },
  "boot_ids": {"worker": "historical-32-hex-boot-id", "current": "current-32-hex-boot-id"},
  "local_host_confirmation": {
    "authority": "user",
    "question": "Can you confirm that the interrupted worker ran only on this machine and was not resumed or moved elsewhere?",
    "text": "yes",
    "machine_id_sha256": "sha256-of-current-etc-machine-id-bytes"
  }
}
```

Hash canonical JSON with sorted keys and compact separators. Capture hashes during
inspection; do not refresh changed evidence just to pass admission. Repository
state uses `workflow_tools.repository_state`, not volatile index stat-cache bytes.
Boot IDs are read from the local kernel and `journalctl --list-boots --output=json`.
Legacy supervisor records did not capture host identity. **Do not infer it from
timestamps or reuse approval of engine repair as host confirmation.** Ask the exact
local-host question above, preserve the later user's affirmative reply (`yes` or
`confirmed`), and bind that operator assertion to the current machine-ID hash.
Without that separate confirmation, stop: journal history alone cannot rule out a
relocated or remote worker. This is explicitly operator-confirmed host origin, not
a claim that the old supervisor cryptographically recorded it.

This narrow recovery is unavailable without that confirmation, Linux/systemd boot
history and local Herdr/Pi identity evidence; absence of processes or a missing pane
alone is unknown. Backend observations honor the configured `E2E_HERDR_BINARY`, not
an implicitly substituted terminal manager.

## Protected or disappearing processes

Permission-denied process metadata means **unknown settlement**, not an unrelated
system helper. The guard reports the numeric PID and refuses recovery before any
snapshot, replacement assignment, state projection or worker launch. It never
reads command lines/environment values, terminates a process, or invokes a
privileged inspector. No PID/name allowlist, `sd-pam` exception, cgroup/parent/time
heuristic, or blanket permission-error suppression is supported. Those observations
do not authenticate a protected process's origin or its unreadable working directory.

Each inspected proc directory is descriptor-bound. A missing working directory
can mean a deleted directory or an exited main thread while other threads survive;
it is not proof of process exit. The kernel's ambiguous ` (deleted)` suffix is
always refused, even if its text happens to resolve to an existing outside alias.
Missing cwd permits continuation only when both
the pinned process's `stat` entry and its numeric proc path are gone. A surviving or
reused numeric PID, changed ownership/cwd, or another inspection error remains
unknown. Readable worktree/descendant cwd still blocks; readable outside cwd remains
only a point-in-time observation, not a durable worker lease.

If inspection is denied, preserve the blocked run and obtain separately authorized
trusted inspection rather than guessing or running the orchestrator as root. This
transition currently has **no privileged-attestation input**: a manual observation,
user-writable JSON file, checksum or a second confirmation cannot unlock it.
Supporting authenticated external inspection would require a separately scoped,
reviewed extension. Do not imply the diagnostic repair itself unblocks such a host.

## Admission and preservation

- Single-repository policy-version-1 run, blocked in implement, approved unchanged
  bundle, no actions/leases, and every recorded handle cleaned.
- The blocker must identify the latest accepted predecessor's now-stale local
  checks. Those checks must genuinely have passed on their original snapshot.
  Real failures, unrelated blockers, changed HEAD/branch/index/content, and expired
  scope are rejected.
- Only attempt 1 of the next dependency-eligible approved packet is eligible, with
  its exact current task/check IDs and commands and one existing replacement left.
  No other unaccepted writer intent may exist.
- Its unaccepted output must still be an initialization placeholder: summary TODO,
  null next action, and empty changed files, checks, decisions, resolutions and
  blockers. The `complete` default is **not** completed work. Real handoffs are not
  replayed, relabeled or accepted by this transition.
- The user must separately confirm local-only worker origin with no relocation or
  remote resumption; the machine-ID hash must match. The original supervisor must
  record settled/cleaned Herdr/Pi identity. A unique
  **historical** journal boot must contain its launch, differ from the current
  kernel boot, and end before the current boot begins. Overlapping/unknown boot
  evidence is rejected. Fresh Herdr inventories must show no restored original
  handle/workspace or task session, and no current owned process may be using the
  task worktree. This proves old local verifier descendants cannot survive; it
  never kills or assumes cleanup of unknown current processes.
- Original run/agent projections are snapshotted. Original output, assignments,
  accepted history and check logs remain byte-for-byte pinned. No credential,
  private session transcript or environment values enter the record.

One immutable `logs/incidents/interrupted-packet-<request-hash>/recovery.json` is
recorded in `run.interrupted_packet_recoveries`, keyed by original action ID.
It preserves the exact request/authorization, separate interpretation, approved
history, raw-state snapshots, shutdown observations and new assignment reference.
Subsequent run loads validate these hashes and forbid accepting the initializer.

The transition queues only attempt 2 with separate output/log paths and the same
approved scope and checks. Its additional instruction preserves partial work and
requires fresh checks. It does not reset budgets, change approval, claim a pass,
start a writer or bypass migration guards. LangGraph reconciles and executes that
intent before rechecking predecessor evidence invalidated by the partial writes.
Fresh failing checks still block; full-plan validation, independent review and
verified delivery remain mandatory.

Snapshots and records are fsynced then exclusively linked into place, so a crash
cannot publish partial final bytes. A reused replacement must retain its exact new
output/log paths; aliasing original evidence paths is rejected before any launch.

Identical applied requests return `already-applied` without advancing, even after
completion. An identical pre-projection crash reuses only the same unlaunched
assignment/immutable intent; a launched replacement is never created again.
