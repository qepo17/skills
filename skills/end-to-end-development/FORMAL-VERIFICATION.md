# Start with laws

A law states what must hold for every case in an agreed scope. Write the law before choosing a proof technique or changing the behavior it describes.

## Settle intent and scope

Read the request and the relevant contracts, proofs, code, and tests. Look for the affected domain's glossary and decision records. Use these sources to answer factual questions and identify choices about intended behavior. If a term is ambiguous or conflicts with a documented definition, show the competing meanings and propose the term to use. If the contract, implementation, or request disagree, point to the relevant evidence and ask which behavior should govern when the intended change is unclear.

Propose the smallest boundary that can express the guarantee. Name the command or component, the applicable actors, inputs and starting states, and the promised result. Include rejection, persistent effects, retries, or concurrent operations when they affect the guarantee. Record exclusions that would otherwise make the claim sound broader than it is.

Ask one question at a time about a decision the sources leave open. Start with the decision that determines the others. Use a concrete case where the possible answers lead to different observable outcomes. State your recommendation and why, and phrase the question so the user can accept it or correct it directly.

> The contract limits manual approval to `READY`, but the command uses a shared transition that also accepts `AWAITING_PAYMENT`. Should manual approval from `AWAITING_PAYMENT` return a conflict and leave the record and payment unchanged? I recommend yes. Payment settlement can still use the shared transition after it verifies payment.

Wait for the answer before asking a dependent question or implementing the affected rule. Continue independent work while waiting. As each decision settles, record the agreed terminology, boundary, and expected outcome in the existing specification or task record. Use those decisions to write the laws without asking the user to repeat them.

## Write the laws

State each agreed rule in plain language using the project's terms. Give it a stable name if it will have a proof or regression check. Specify any assumptions and what a violation would look like. Record the law in the repository's existing specification or in the task record before assigning dependent work. Agree which obligations require formal proof and where behavioral checks are sufficient. Review changes to the law or its required evidence as changes to the specification.

If the user accepts the recommendation, write the law for the manual approval command. It may succeed only for a record in `READY`. From `AWAITING_PAYMENT`, it must return a conflict and preserve the record and its open payment. An otherwise valid manual approval from `READY` must still succeed.

## Carry the laws into verification

- Map each distinct obligation to the assertion or behavioral check that covers it, and record gaps. Show that cases in the law's scope can occur under the assumptions used to check them. For manual approval, show that a valid `READY` request succeeds and that an `AWAITING_PAYMENT` request reaches the command, returns a conflict, and preserves both the record and payment.
- Use the repository's proof tooling and extend its coverage when needed for a required proof and within task scope. State what the checker consumes, its assumptions and bounds, and how the model corresponds to executable source, such as through shared definitions, generation, or a checked correspondence. Limit implementation claims to paths covered by that correspondence.
- Verify that the evidence detects a relevant violation by reproducing a counterexample or introducing a small, temporary change in an isolated workspace. Exercise the real command entry points and other write paths for obligations outside the proof, including applicable guards, stored effects, and transaction or retry behavior.
- Run established or agreed proof checks locally and use the same check in CI when required or agreed. For each obligation, report the result and its scope, including proofs, bounded checks, behavioral tests, and inconclusive results. Bind the evidence to the verified revision. Missing coverage, a failing or inconclusive result, or an unavailable check blocks completion for a required proof. Report the blocker and preserve the agreed law while diagnosing it.
