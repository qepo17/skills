# Producer-order / generated-bundle recovery

`recover-generation-scope` is an explicitly authorized, one-shot interpretation/scope repair, not replanning or a generic unblock. It applies only to a settled full-profile implementation with validation-policy version 1 and a user-approved bundle, one accepted permission blocker naming `dist/openapi.yaml`, and a no-change blocked consumer with an unused ordinary replacement. All worker/supervisor handles must be settled and cleaned, and all repository/Git evidence unchanged. No active actions, writer leases, staged changes or unrelated pending work may exist.

The contract must already describe every dependency with the literal `Producer-to-consumer edge:` reason prefix and have the selected producer upstream of the consumers. The recovery interprets those existing edges as producer → consumer; unrecovered runs retain the legacy consumer → prerequisite convention. This preserves the approved product meaning and original contract, plans, bundle, results, logs and assignments. It does not revise an approved design, change policy versions, replenish budgets or accept an unimplemented packet.

Prepare the request outside canonical state. Required keys:

- `run_id`, exact `expected_run_sha256`, current `blocker_id`;
- `blocker_evidence`, `authorization`, `contract`, `review`: `{path, sha256}` file references. `authorization` is an immutable record of the presented scope and exact user reply, not a mutable interaction ledger;
- `producer_repo_id`, sorted nonempty `read_consumers`, and sorted nonempty `write_consumers` (a subset of readers);
- `generated_path: "dist/openapi.yaml"`, `dependency_direction: "producer-to-consumer"`;
- `repository_states`: every repository's current `workflow_tools.repository_state` observation. These must also agree with accepted implementation evidence, or the planning baseline when no writer has run.

The output must be ignored, untracked, and free of symlink traversal. This is a logical permission exception, **not** an operating-system sandbox expansion. Read-only source scope stays read-only except for the exact generated-file path. Runtime denials remain blockers. No generated code may be hand-edited.

Compute the request SHA-256 from UTF-8 `json.dumps(request, sort_keys=True, separators=(",", ":"))`. Review the request and preserve that hash; do not silently refresh stale authorization. Invoke with the exact affirmative user reply (`authorized` or `approved`, following the fully scoped request):

```bash
run-orchestrator recover-generation-scope "$RUN_DIR" \
  --input /absolute/recovery-request.json --request-sha256 "$REQUEST_SHA256" \
  --text 'authorized' --no-drive
```

The CLI holds the execution lock and refuses a pending graph cursor. It writes immutable `generation-recovery-run-before.json` and `generation-recovery.json`, then atomically attaches the latter's hash to the run and releases only this blocker. Identical reapplication is idempotent; conflicting or stale requests fail. A crash before projection may reuse identical intent. `--no-drive` permits inspection before ordinary `run` continues through LangGraph.

Future consumer assignments gain producer reads, hash-pinned upstream result evidence, and a producer source/Git snapshot. Only implementation/fix/validation/integration checks gain the authorized generated output writes; reviews remain read-only. Normalization refuses changed/stale producer source/Git evidence. Replacements get fresh scope and upstream evidence in a **new** immutable assignment within the existing replacement limit. The completed earlier packet is not replayed. Validation and pending-remediation work use separate dependency-ordered graph waves: upstream workers must settle and be accepted before a downstream assignment is even constructed. A retained worker cannot launch a downstream rebundler. Historical assignment hashes and the preceding completed packet (or planning baseline) mechanically establish the no-change admission condition. Artifact-only repairs never inherit the generated-write exception. Existing legacy behavior remains unchanged without the recovery reference.

This cannot authorize a material product/contract change. Such a change still needs its matching supported replanning transition and renewed whole-bundle approval. Do not edit canonical artifacts or run state to make this recovery eligible.
