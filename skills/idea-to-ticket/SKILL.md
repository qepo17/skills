---
name: idea-to-ticket
description: "Turn an idea not yet represented by a Jira or GitHub ticket into an evidence-backed, outcome-oriented ticket draft. Research repository/docs first, clarify only material unknowns with a cumulative maximum of 10 questions, and publish only with explicit authorization. Optional preparation, not an execution prerequisite; reuse existing tickets rather than duplicate them."
---

# Idea to Ticket

`idea → focused evidence → necessary clarification → ticket draft → authorized publication`

Use independently for unticketed ideas. This is **optional upstream preparation**, never a mandatory stage of `end-to-end-development` or `fast-end-to-end-development`. Those skills turn existing tickets into grounded implementation specs. Do not implement code, run an orchestrator, or produce exhaustive file-by-file designs, speculative schemas, or implementation task trees here. No sibling skill or runtime dependency is required.

If the user supplies an existing ticket, read and reference it, check that it covers the idea, and hand off for execution instead of creating a duplicate. A related but distinct ticket is evidence, not permission to create a new one. Route a needed amendment to the existing ticket; do not edit it automatically. Handoff is a recommendation, not authorization to start execution.

## 1. Establish context and preserve the record

Read repository instructions (`AGENTS.md`, `CONTRIBUTING.md`, relevant nested instructions), then the request and any prior discovery/handoff. Resolve the repository from evidence; do not assume a remote or tracker project. Preserve existing work. Use read-only research; do not run database commands or copy credentials.

Maintain one concise task record outside the checkout, in a user-specified location or `${XDG_STATE_HOME:-$HOME/.local/state}/idea-to-ticket/<task-id>/record.md`. Reuse that record on resume; return its path with the draft. If persistence is unavailable, return the complete record for handoff and report the limitation. Never store secrets or unbounded transcripts.

Record the original goal, repository/baseline, inherited decisions and question history, effective question cap, draft revision, and publication history. Do not reset counters or create a new task identity to bypass a limit. If inherited discovery already exceeded the cap, ask no more questions and record the overrun. If history/count is unavailable, do not assume zero: reconstruct it from available records; otherwise stop clarification and mark material unknowns as blockers.

## 2. Research before asking

Inspect only the relevant entry points, nearby tests, product docs, and established conventions. Read remote docs only when a material fact cannot be established locally; record the source/version or access date. Stop research once the outcome, constraints, and remaining material decisions can be explained. Do not scan the whole repository to build a speculative design.

- Cite focused evidence as `E-001`, etc.: repository path and symbol/line range plus baseline commit, or document/ticket URL and version/date; summarize the finding and its implication. Distinguish current behavior from the requested outcome and unsupported hypotheses.
- Search the relevant Jira project or GitHub repository for supplied IDs, distinctive terms, synonyms, and related features, including closed tickets when relevant. Use available authorized read tools; never invent a successful search. Record target, query, time, candidate IDs, and why each matches or differs.
- If an existing ticket covers the idea, return its canonical link and the evidence/ledger for execution; do not create another. If overlap is materially ambiguous, resolve it within the shared question budget or block creation. If tracker access is missing, draft locally and record that duplicate checking is incomplete; publication is blocked.
- Adopt evidence-backed, reversible, in-scope recommendations without routine confirmation. Record the rationale and uncertainty. Evidence does **not** authorize guesses about security, data loss, conflicting user requirements, public contracts, or external writes. Unresolved material choices in these areas require a decision or a blocker.

## 3. Clarify only what changes the outcome

Ask **zero questions** when the evidence and request are sufficient. Do not request blanket approval of routine recommendations or of the draft.

Rank genuinely unresolved material decisions by impact on safety, user outcome, scope, or acceptance. Ask only the highest-impact necessary questions, normally **1–3 in a batch**, not a quota. Explain briefly why each matters and provide an evidence-backed recommendation when possible. Do not ask about details execution can safely determine later.

**Hard cumulative cap: at most 10 independently answerable clarification questions for the entire task**, including inherited discovery, follow-ups, repeated/rephrased questions, retries, resumes, and questions asked by other stages or agents. Honor a lower user cap; “no interview” means zero further questions. Remaining budget is `max(0, effective cap − already asked)`. Count every independently answerable part, not numbered bullets; never hide multiple decisions inside one item.

Persist each question and increment the count **before sending it**, so an interrupted/retried turn cannot reset the ledger. Preserve answered, unanswered, superseded, and repeated questions with their original IDs and dispositions. Record volunteered decisions without charging a question. A clarification that reveals another unknown does not extend the budget.

At the cap, with no interview, or when the budget cannot be recovered, record remaining material choices and return **not-ready**; never continue a questionnaire or invent approval. If all material choices are resolved, proceed without spending the remaining budget. Non-material uncertainties may remain explicit assumptions with rationale and a safe fallback.

Required explicit publication authorization is separate from clarification. It may ask only for permission to perform the fully specified write; do not disguise unresolved target, scope, or product questions as an authorization request to evade the cap.

## 4. Draft an outcome contract

Keep the ticket concise: problem, desired outcome, users, evidence, scope/non-goals, and observable acceptance criteria. Give criteria stable IDs (`AC-001`, `AC-002`, …), retaining IDs across revisions and retiring rather than renumbering removed criteria. Describe verifiable behavior and relevant failure/boundary outcomes, not speculative implementation steps. Reference evidence and decisions where useful; execution determines the grounded implementation spec and validation commands.

Keep **decisions**, **assumptions**, and **blockers** distinct. A user/evidence-established decision is not a guess; a routine adopted recommendation should state its rationale and reversibility. An assumption is uncertain but non-material and safely revisable. A blocker is a material unknown or missing prerequisite and must not masquerade as an assumption.

Use this compact record shape, omitting irrelevant fields but not the question or publication ledger:

```markdown
# <Outcome-oriented title>
Status: draft | ready | published | not-ready
Task ID / draft revision / record path:
Repository / baseline:
Original goal:

## Ticket draft
Problem and affected users:
Desired outcome:
In scope:
Non-goals:
Acceptance:
- AC-001: <observable outcome and verification signal>
Evidence:
- E-001: <source locator/version; finding; implication>
Decisions: <D-001; user/evidence/adopted recommendation; rationale; linked E/AC IDs>
Assumptions: <A-001; uncertainty; evidence/rationale; safe fallback>
Blockers: <B-001; unresolved choice/prerequisite; impact; needed resolution>

## Handoff ledger
Questions: cap=<0..10>; asked=<cumulative including inherited>; remaining=<n>
History source / inherited count / count certainty:
- Q-001: <one question; stage; asked time; answer or unanswered; decision/disposition>
Duplicate check: <target; query/time; candidate links; match/difference; completeness>
Execution handoff: <draft or canonical existing/published ticket; AC IDs; evidence; ledger>
Next action / owner:

## Publication ledger (local; not automatically included in ticket body)
Target: <Jira site/project OR GitHub owner/repository, only when applicable>
Type / parent: <only if requested or required by that tracker/workflow>
Authorization: <exact user grant; target; draft revision/body identity; time, or none>
Attempt: <stable operation marker; exact payload identity; time; result/error>
Reconciliation: <read queries; candidate IDs; verified fields; resolved/ambiguous>
Canonical ticket ID / URL: <only after verified creation or confirmed reuse>
```

Return the draft without requiring approval for routine recommendations. Use states precisely:

- **draft**: working proposal; research/readiness evaluation is incomplete. Never publish this state.
- **ready**: outcome and stable criteria are supported, no material blockers remain, and duplicate checking is sufficient for the intended next step. Ready is **not** permission to publish; an otherwise ready draft may await explicit publication authorization.
- **not-ready**: a material decision, question-budget uncertainty, duplicate check, or necessary prerequisite blocks progress. Show the useful partial draft, blocker, and next action; do not publish. Identify whether the blocker concerns content, execution handoff, or publication only.
- **published**: the canonical remote ticket has been read back and verified against the authorized target and draft. A create request sent, timeout, or unverified URL is not success. For an already-existing ticket, report `reused: <URL>` instead of claiming it was published by this task.

Target identity is necessary for tracker searches and publication, not for starting a local draft. Before publication require a specific Jira site/project or GitHub owner/repository. Require issue type or parent only if requested or required by that tracker's workflow (for example, a Jira subtask); do not demand irrelevant metadata. Discover defaults through read-only evidence, but never guess a write destination. Missing material metadata consumes clarification budget if asked; otherwise record a publication blocker.

## 5. Publish only when explicitly authorized

Default to returning the draft. Do **not** create, edit, comment on, transition, link, or otherwise modify Jira/GitHub objects automatically. Explicit user authorization must cover the exact target and current draft/content, plus type/parent when relevant. A request to draft, access credentials, a routine recommendation, or a ready state is not authorization. An earlier explicit grant is usable only if it unambiguously covers this payload and target; material changes invalidate it. Do not bundle unrelated writes into permission to create.

Before an authorized create:

1. Recheck readiness, authorization, and duplicates in the exact target. If a matching ticket now exists, reuse it without edits; do not create again.
2. Persist the intended target, exact payload or content hash, authorization evidence, and a stable per-task operation marker **before** the write. Include a searchable marker in the authorized ticket body when supported; do not add unapproved content after authorization.
3. Perform one create via the available authenticated tracker tool. Persist the result and read back the ticket, verifying target, title/body/acceptance IDs, and required type/parent before reporting `published` and its canonical ID/URL.
4. On a timeout, interrupted run, malformed response, or other ambiguous create result, **never blindly retry**. On resume reconcile this pending attempt before any new create: read any returned ID and search the exact target by marker and distinctive payload/title, inspecting candidate bodies and creation time. A verified match is success; multiple candidates, unavailable search, or inconclusive/eventually consistent absence means `not-ready` with publication outcome unknown. Preserve the attempt and stop rather than risking a duplicate.
5. Retry only after authoritative evidence establishes that no ticket was created and the same authorization remains valid. Keep the same logical operation identity (and idempotency key if the tracker supports it); reconcile again before writing. No automatic compensating deletes or edits if a created ticket differs from the intended payload—record the discrepancy and request separately scoped authorization if correction is needed.

Finish with status, draft or canonical link, key assumptions/blockers, cumulative question count/cap, record path, and the next action. Hand off the evidence, stable acceptance IDs, decisions, and full question ledger so execution does not restart discovery or its budget. Do not install or launch an execution skill automatically.
