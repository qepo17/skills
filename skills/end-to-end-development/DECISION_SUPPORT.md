# Optional decision support

Use TypeSafe, when available, to classify workflow, impact, and ambiguity at
intake and again against the final diff. It is advisory context, not a
workflow engine or authorization mechanism. If it is unavailable, apply the
same rubric manually.

## Questions

Ask these independently against one sanitized state:

| Field | Type | Levels |
| --- | --- | --- |
| `workflow_kind` | `Choice` | `implementation`, `diagnosis`, `research`, `refactor`, `ui`, `multi_repository` |
| `impact` | `Score` | 0: reversible/local; 1: bounded/routine; 2: user-facing, compatibility-sensitive, or multi-repository; 3: destructive, security-sensitive, data-sensitive, or externally published |
| `ambiguity` | `Score` | 0: clear; 1: repository precedent resolves it; 2: important details unclear; 3: unsafe to understand without clarification |

Use this shared prompt:

```text
Using the request, repository instructions, and a sanitized change summary,
classify the workflow, impact, and ambiguity independently. Use confidence to
signal uncertainty. Do not authorize actions or invent missing requirements.
```

## Decision record

Keep this in the task record or conversation context, not in the target
repository unless explicitly requested:

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

`source` is `typesafe` or `manual`. Derive the remaining fields with ordinary
workflow policy; the classifier does not decide them directly.

## Policy

- Confidence below `0.5`: `inspect`, or `human_review` for impact 3.
- Ambiguity 3: `clarify`; do not infer missing behavior.
- Impact 0–1: focused or standard verification as appropriate.
- Impact 2–3: expanded verification and independent review.
- If the final diff raises impact or ambiguity, repeat the applicable checks.
- Never let TypeSafe authorize a push, pull request, migration, deployment,
  destructive operation, or permission change.

## Context and fallback

Send only the minimum sanitized context: the request, repository metadata,
relevant instructions, affected-file/test summaries, and redacted evidence.
Never send credentials, tokens, private keys, secret-bearing files, or
unnecessary private content.

If TypeSafe times out or returns unusable data, use `source: "manual"` and
apply the rubric conservatively. High-impact work must not become low-risk
because classification failed.
