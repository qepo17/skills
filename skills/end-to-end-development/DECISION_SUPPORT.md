# Optional decision support

TypeSafe can provide structured, confidence-bearing judgments when the task
contains classification or triage work. It is advisory context for the agent,
not a workflow engine and not an authorization mechanism.

## When to use it

Use TypeSafe at two points when it is available:

1. After reading the request and repository instructions, classify the work
   before choosing the depth of investigation and verification.
2. Before delivery, evaluate the request together with the final diff. If the
   apparent scope or impact increased, revisit verification and review.

Do not call it for every implementation step. The agent remains responsible
for understanding the code, making the change, running checks, and interpreting
evidence.

## Questions

Ask independent, atomic questions against the same sanitized state. Use
TypeSafe's `Choice` for `workflow_kind` and `Score` for `impact` and
`ambiguity`. Compose their answers with ordinary workflow policy.

Use this shared prompt:

```text
Using the request, repository instructions, and a sanitized change summary,
classify the workflow, impact, and ambiguity independently. Use confidence to
signal uncertainty. Do not authorize actions or invent missing requirements.
```

### `workflow_kind` — Choice

Choose the kind that best describes the requested work:

- `implementation`: add or change behavior.
- `diagnosis`: determine why existing behavior is broken, slow, or unsafe.
- `research`: gather evidence before deciding or implementing.
- `refactor`: change structure without intentionally changing behavior.
- `ui`: change a rendered interface or interaction.
- `multi_repository`: coordinate a change across independent repositories.

### `impact` — Score

Use ordered levels:

0. Reversible local change with no external effect.
1. Bounded behavior change with routine verification.
2. User-facing, multi-repository, compatibility-sensitive, or otherwise costly
   failure.
3. Destructive, security-sensitive, data-sensitive, or externally published
   change.

### `ambiguity` — Score

Use ordered levels:

0. The requested outcome and acceptance evidence are clear.
1. A routine choice remains, but repository precedent resolves it.
2. Important behavior, compatibility, or verification details are unclear.
3. The task cannot be safely understood without clarification or more evidence.

## Normalized decision record

Keep the record in the task record or conversation context. Do not commit it
to the target repository unless the user explicitly requests that artifact.

```json
{
  "schema_version": 1,
  "workflow_kind": {"value": "implementation", "confidence": 0.91},
  "impact": {"level": "medium", "score": 1.8, "confidence": 0.76},
  "ambiguity": {"level": "low", "score": 0.4, "confidence": 0.88},
  "recommended_action": "proceed",
  "verification_profile": "standard",
  "review_required": true,
  "source": "typesafe"
}
```

`source` is `typesafe` when the record came from TypeSafe and `manual` when
the agent used the same rubric without it. `recommended_action` is one of:

- `proceed`: continue the normal loop.
- `inspect`: gather repository or task evidence before deciding.
- `clarify`: ask about a consequential unresolved choice.
- `human_review`: route the judgment to a person before acting.

The record is a recommendation. It must not override repository instructions,
tests, explicit user decisions, or the delivery safety rules.

## Deterministic policy

Apply these defaults after normalizing the answers:

- If any required answer has confidence below `0.5`, use `inspect` for routine
  work or `human_review` for impact level 3.
- If ambiguity is level 3, use `clarify` and do not implement an inferred
  behavior.
- Impact levels 0–1 use `focused` or `standard` verification according to the
  change. Impact levels 2–3 use `expanded` verification and independent review.
- A final-diff review that raises impact or ambiguity invalidates the earlier
  recommendation and requires the applicable verification again.
- TypeSafe may suggest a route, but it never authorizes a push, pull request,
  migration, deployment, destructive operation, or permission change.

These thresholds are conservative defaults. Calibrate them against actual task
outcomes if the repository later gains enough evidence to justify doing so.

## Input and failure rules

Send only the minimum sanitized state needed for the questions:

- the user request;
- repository names, branches, and relevant instructions;
- a concise summary of the affected files, tests, and final diff;
- redacted evidence needed to distinguish the choices.

Never send credentials, tokens, private keys, raw secret-bearing files, or
unnecessary private repository content. If TypeSafe is unavailable, times out,
or returns unusable data, continue with `source: "manual"` and apply the same
rubric conservatively. High-impact work must not be treated as low-risk merely
because the classifier failed.

## Examples

### Proceed normally

An isolated implementation has clear acceptance criteria, no external effect,
and high-confidence classification. Use `recommended_action: "proceed"` and
the ordinary checks for the repository.

### Ask before implementing

A request asks to change compatibility behavior but does not say which clients
must remain supported. Use `recommended_action: "clarify"`; do not choose a
compatibility policy from the classifier's preferred option.

### Expand verification

A change touches several repositories or changes a user-facing contract. Use
impact level 2 or 3, select `verification_profile: "expanded"`, and require
independent review before any requested delivery.

### Classifier unavailable

Proceed with `source: "manual"` when the task is routine. For destructive or
externally published work, preserve the existing explicit authorization and
delivery checks and apply the conservative high-impact path.
