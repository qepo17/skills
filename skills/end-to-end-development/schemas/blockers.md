# Worker blocker contract

Use this contract when an assigned stage cannot finish. A finding discovered by a completed review is not itself a blocker: record it in `findings` with the review still complete. Likewise, on a validation-policy-version-1 assignment, a reported check failure does not make finished source/check-reporting work blocked; preserve the failed observation in a complete result and let the engine evaluate its gate.

Every blocker has all five fields:

```json
{
  "id": "BLOCK-001",
  "kind": "environment",
  "summary": "The isolated test service is unavailable.",
  "evidence_path": "/absolute/run/repos/api/logs/service.log",
  "required_action": "Restore the isolated test service, then resume."
}
```

Kinds are `decision`, `environment`, `authentication`, `permission`, `infrastructure`, `dependency`, and `code`. Choose from actual evidence; never omit `kind` or guess a retryable category to bypass a real decision. Evidence must exist. A blocked artifact needs at least one blocker; a complete artifact has none. Blocker prose is descriptive evidence, never transition authority: do not copy, tune, or regex-match a message to imitate a supported recovery condition. Only typed gate fields, current hash-pinned evidence, and supported commands can authorize a transition.

A local validation-gate blocker may expose exact candidate check IDs. It cannot waive missing/protected evidence or convert unfinished work to complete. An exclusion clears only its targeted eligible check; every untargeted or non-validation blocker remains. A required-CI blocker reports the latest observed identities/state and PR URL when known; it does not by itself authorize a source fix.

For new runs the coordinator, not the worker, derives scoped `gate` metadata: `local-validation`, `required-ci`, or the narrowly recognized `delivery-state` body/readiness conflict. The latter permits only read-only re-observation after external resolution; it is not a generic decision/code-blocker bypass.

After initializing and completing the other semantic fields, prefer the typed constructor:

```bash
python3 <validator_path> block <assignment_path> \
  --kind environment \
  --summary "The isolated test service is unavailable." \
  --evidence-path /absolute/run/repos/api/logs/service.log \
  --required-action "Restore the isolated test service, then resume."
```

Optional `--id BLOCK-...` supplies an explicit unique ID. The command validates the blocker and sets `status: blocked` only in the active assignment's unaccepted output. It refuses arbitrary or accepted outputs. It does not complete other semantic fields, fix code, alter coordinator state, or authorize a migration. Run the stage validator before returning.

An assignment with `execution_mode: artifact-repair` is different: initialization copies the original result. Add only the missing existing `blockers[*].kind`, based on the pinned evidence. Do not append blockers, change outcomes/text/checks, rerun commands, or modify project/Git/forge state. If classification remains ambiguous, preserve the missing field and explain the ambiguity in the worker log; the graph will stop rather than invent evidence.
