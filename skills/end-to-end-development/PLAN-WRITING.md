# Write plans people can follow

Make the plan easy to understand, not merely short. Borrow `show-me`'s principle: **pick the smallest view that makes the key point clear**. This guide is self-contained; no other skill or visual tool is required.

## Give the reader a path

Lead with the change, not a preamble about your process. Use this reading order, merging sections for small work rather than filling a template:

1. **What changes and why.** Name the user's problem and intended outcome in a few sentences. State the recommended approach and the main reason for it. Make a blocking decision or consequential risk visible here, not buried at the end.
2. **How it works.** Explain the important behavior or boundary. If a small flow, tree, or before/after view explains it better, put that view beside the sentence it supports. Distinguish current behavior from the proposed change.
3. **What we will do.** Order concrete, outcome-named slices by real dependencies. For each, say what changes, where responsibility belongs, why a non-obvious choice is needed, and what observable check proves it. Keep acceptance IDs and prerequisites attached to the slice.
4. **How we know it works.** Summarize acceptance coverage, preserved behavior, important failure cases, and required checks. Put exact commands and baseline-bound evidence in the existing execution fields; reference them rather than repeat them. Planned checks are not passing results.
5. **Boundaries and decisions.** State non-goals, meaningful trade-offs, remaining risks, and unresolved choices. End with the actual next action under the workflow's policy, not a routine approval question.

A reader skimming the opening and slice titles should understand the change. A reader implementing it should find the constraints, dependencies, and verification without guessing. This is a reading order for human-facing prose, **not** a new artifact schema or permission to reorder machine-required fields.

## Choose the form that answers the question

Use prose by default. Add a visual only when it removes explanation or makes an otherwise hidden relationship clear; zero visuals is valid. Do not turn every plan into a diagram gallery.

| The reader needs to understand… | Smallest useful view |
| --- | --- |
| A simple decision and its reason | A sentence or short bullet |
| Behavior, order, or a branch | A short text flow or pseudocode |
| Which component calls which | A shallow call tree; a sequence diagram only if handoffs matter |
| Ownership across modules or files | A shallow responsibility tree |
| What changes in a familiar structure | A focused `diff` with enough surrounding context |
| A real choice between alternatives | A small comparison table with a recommendation and trade-off |

Keep only the relevant calls, states, files, and boundaries. Use established domain terms; explain unfamiliar ones on first use. Prefer text fences when the viewer may not render Mermaid. A diagram must not introduce behavior, dependencies, or mechanisms missing from the plan.

Keep long-lived product prose at the behavior/module level. In local execution detail, use inspected baseline-bound paths/symbols; label proposed shapes as proposed and conceptual pseudocode as illustrative, never as existing code. Show a whole block instead of a diff when most of it is new or omitted context would hide ownership/order. This does not authorize speculative code in durable spec prose or relax the existing narrow prototype exception.

HTML is not the default plan format. Use it only when requested or when a spatial/UI question genuinely needs it and the workflow permits the artifact. It must not replace canonical evidence or approval. Keep the plan understandable without opening another artifact.

## Keep the useful detail; cut the reading cost

- Use short paragraphs, concrete verbs, and headings that tell the story. Prefer “Keep the draft after a failed send” to “Error-handling enhancements.”
- Put rationale beside the decision, evidence beside the claim, and verification beside the behavior. Do not make readers assemble one idea from several distant sections.
- Replace vague steps such as “update the backend” or “add tests” with the behavior, owner, and observable result. Name consequential edge cases and compatibility constraints; do not inventory every helper or repeat the ticket.
- Separate facts, user decisions, agent recommendations, and blockers. Keep uncertainty visible. Concision never means dropping required fields, checks, risks, or acceptance coverage.
- Scale to the work: a small bug may need one paragraph and one checked-by slice; a larger change needs a short overview followed by focused slices. For multiple repositories, explain the shared behavior first, then repository-local responsibilities and cross-repository prerequisites. Avoid one wall of prose or a giant table of long paragraphs.

## Example: a small bug, enough detail

Illustrative scenario only: the request is to preserve a message draft when sending fails; inspection has established that the composer already handles the send result. This is a human-facing sketch, not a complete canonical artifact.

**Keep the draft after a failed send.** Today the composer clears the text before the request finishes. Move clearing into the existing success path so a failed send keeps the user's text available for retry. No new draft store is needed.

Proposed behavior:

```text
Send → existing request
  success → clear draft as today
  failure → keep draft + show existing error
```

**1. Clear only after success** — The composer owns this change. Keep the existing send/error handling; change only when the draft is cleared. Covers AC-1 (retain failed drafts) and AC-2 (preserve successful-send behavior). Blocked by: none.

**Check:** At the existing composer interaction seam, reject a send and assert that the typed draft and error remain visible. Resolve a send and assert that the draft clears. Attach the inspected test location and exact command in execution evidence. These are planned checks, not recorded passes.

**Boundary:** No persistence across reloads, automatic retry, or new messaging behavior. The next action follows the workflow's existing risk/approval policy.

For a one-line fix, this can be shorter and omit the flow. For a broader change, repeat the outcome/change/check pattern only where a distinct slice needs it—not the same summary in five formats.

## Before presenting

Read it once as someone who did not do the investigation. Can they say what changes, why this approach, what happens first, and what proves success? Remove filler, duplicated explanation, and decorative visuals; fill any gaps that force them to guess.

In the fast workflow, apply this directly to `plan.md`. In the durable workflow, write clear task/packet summaries, focused steps, validation rationales, and risks inside the existing fields. The coordinator's readable overview must faithfully describe the current canonical bundle, link its full path/hash, and retain per-repository task/packet/risk/validation coverage. Never rewrite a hash-pinned bundle for presentation or treat an overview as a substitute approval target. All existing high-risk approval, clarification, migration, and validation gates remain unchanged.
