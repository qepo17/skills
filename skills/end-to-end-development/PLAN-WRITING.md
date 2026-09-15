# Write readable plans

Lead with the user's problem, proposed change and reason. Make consequential risks or decisions visible immediately. Scale detail to the task; a small fix may need one paragraph and one outcome/check pair.

Use this reading order inside existing artifact fields:

1. **Change and reason:** current behavior, intended outcome and recommended approach.
2. **Behavior:** explain ownership, boundaries and important happy/error paths.
3. **Work:** outcome-named slices in dependency order, each with responsibility, rationale, acceptance IDs and verification.
4. **Proof:** acceptance coverage, preserved behavior and required checks. Keep exact commands and inspected paths in execution evidence; planned checks are not passes.
5. **Limits:** non-goals, trade-offs, blockers and the next action under existing policy.

Put evidence beside claims and rationale beside decisions. Distinguish facts, user decisions, recommendations and blockers. Use established domain terms; explain unfamiliar terms. Avoid vague steps, repeated ticket prose, helper inventories and new artifact fields.

## Use the smallest useful view

Prose is the default. Add a short flow for behavior/order, a shallow tree for ownership/calls, a focused diff for structural change, or a comparison table for a real choice. Keep only relevant relationships; visuals must not invent behavior or dependencies. Use text fences if diagram rendering is uncertain.

Keep durable product prose at module/behavior level. Execution detail may use inspected baseline-bound paths/symbols; label proposed shapes and illustrative pseudocode. The only code exception in product prose is a provenance-labelled existing prototype excerpt expressing a settled decision. HTML is appropriate only when requested or genuinely needed for a permitted spatial/UI artifact; the plan must remain understandable without it.

## Example

**Keep drafts after failed sends.** The composer currently clears text before the request finishes. Clear it in the existing success path so failures retain text for retry; no new store is needed.

**Slice:** change composer clearing, preserving existing send/error handling. Covers AC-1 (retain failed drafts) and AC-2 (clear successful drafts). No prerequisites.

**Check:** at the existing composer interaction seam, a rejected send preserves text/error; a successful send clears text. Attach inspected test location and exact command as planned execution evidence.

**Scope:** no reload persistence or automatic retry. Proceed under the workflow's existing approval policy.

## Present the canonical plan

Check that a reader can identify what changes, why, what comes first and what proves success. For multiple repositories, explain shared behavior before local responsibilities and cross-repository prerequisites.

Write summaries, steps, validations and risks in the durable plan's existing fields. The coordinator overview must match the canonical bundle, link its full path/hash and cover each repository's tasks, packets, risks and checks. Never alter a hash-pinned bundle for presentation or substitute the overview for its approval target.
