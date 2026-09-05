# Worker blocker contract

Before any work, read [SKILL.md — Validation rules](../SKILL.md#validation-rules). It contains the shared limits, required fields, evidence rules, and role boundaries; this file is a shape reminder.

Use this contract when an assigned stage cannot finish. A finding discovered by a completed review is not itself a blocker: record it in `findings` with the review still complete.

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

Kinds are `decision`, `environment`, `authentication`, `permission`, `infrastructure`, `dependency`, and `code`. Choose from actual evidence; never omit `kind` or guess a retryable category to bypass a real decision. Evidence must exist. A blocked artifact needs at least one blocker; a complete artifact has none.

After initializing and completing the other semantic fields, prefer the typed constructor:

```bash
python3 <validator_path> block <assignment_path> \
  --kind environment \
  --summary "The isolated test service is unavailable." \
  --evidence-path /absolute/run/repos/api/logs/service.log \
  --required-action "Restore the isolated test service, then resume."
```

Optional `--id BLOCK-...` supplies an explicit unique ID. The command validates the blocker and sets `status: blocked` only in the active assignment's unaccepted output. It refuses arbitrary or accepted outputs. It does not complete other semantic fields, fix code, alter coordinator state, or authorize a migration. Follow SKILL.md's stage-aware preflight before returning: check every semantic field and run the stage validator when mechanical metadata is ready; otherwise report normalization pending. The graph still normalizes and validates before acceptance.

An assignment with `execution_mode: artifact-repair` is different: initialization copies the original result. Add only the missing existing `blockers[*].kind`, based on the pinned evidence. Do not append blockers, change outcomes/text/checks, rerun commands, or modify project/Git/forge state. If classification remains ambiguous, preserve the missing field and explain the ambiguity in the worker log; the graph will stop rather than invent evidence.
