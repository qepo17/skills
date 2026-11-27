# Start with laws

A law states what must hold for every case in an agreed scope. Write the law before choosing a proof technique or changing the behavior it describes.

## Settle intent and scope

Read the request and the relevant contracts, proofs, code, and tests. Look for the affected domain's glossary and decision records. Use these sources to answer factual questions and identify choices about intended behavior. If a term is ambiguous or conflicts with a documented definition, show the competing meanings and propose the term to use. If the contract, implementation, or request disagree, point to the relevant evidence and ask which behavior should govern when the intended change is unclear.

Propose the smallest boundary that can express the guarantee. Name the command or component, the applicable actors, inputs and starting states, and the promised result. Include rejection, persistent effects, retries, or concurrent operations when they affect the guarantee. Record exclusions that would otherwise make the claim sound broader than it is.

Ask one question at a time about a decision the sources leave open. Start with the decision that determines the others. Use a concrete case where the possible answers lead to different observable outcomes. State your recommendation and why, and phrase the question so the user can accept it or correct it directly.

> The contract limits manual approval to `READY`, but the command uses a shared transition that also accepts `AWAITING_PAYMENT`. Should manual approval from `AWAITING_PAYMENT` return a conflict and leave the record and payment unchanged? I recommend yes. Payment settlement can still use the shared transition after it verifies payment.

Wait for the answer before asking a dependent question or implementing the affected rule. Continue independent work while waiting. As each decision settles, record the agreed terminology, boundary, and expected outcome in the existing specification or task record. Use those decisions to write the laws without asking the user to repeat them.

## Write the laws

State each agreed rule in plain language using the project's terms. Give it a stable name if it will have a proof or regression check. Specify any assumptions and what a violation would look like. Record the law in the repository's existing specification or in the task record before assigning dependent work. Review changes to an agreed law as changes to the specification.

If the user accepts the recommendation, write the law for the manual approval command. It may succeed only for a record in `READY`. From `AWAITING_PAYMENT`, it must return a conflict and preserve the record and its open payment. An otherwise valid manual approval from `READY` must still succeed.

## Carry the laws into verification

- Use the repository's proof tooling when it covers the law. Tie the model to executable source through shared definitions, generation, or a checked correspondence where practical. State exactly what the checker consumes, any bounds or assumptions, and which implementation paths remain outside the model.
- Verify that the evidence detects a violation. Reproduce an existing counterexample or make a small, temporary change in an isolated workspace and check that it fails for the expected reason. Include a valid case when a rule about allowed behavior could pass because every request is rejected.
- When a model covers only transition tables, follow the real command entry points and other write paths that can bypass the tables. Use behavioral checks for applicable guards, stored effects, and transaction or retry behavior beyond the proof. Keep those results distinct from the proof result.
- During review, trace each law to its evidence. Record which laws the checker accepted, which received behavioral checks, and which remain unverified. Run established or agreed proof checks locally. Use the same check in CI when CI enforcement is required or agreed. Bind the results to the verified revision. If a required proof fails or cannot run, report the blocker and preserve the law while diagnosing it.
