# One-time privileged process inspection

An **optional, separately user-authorized** addition to the existing interrupted-packet recovery request. It is not an automatic fallback, a process exception, a new recovery mode, or permission to elevate the orchestrator. Existing requests continue to use strict unprivileged inspection.

```json
{
  "privileged_inspection": {
    "mode": "sudo-once",
    "authority": "user",
    "text": "The user's exact explicit authorization for one read-only privileged inspection.",
    "authorization_id": "32-random-lowercase-hex-characters",
    "subject_uid": 1000,
    "inspector_sha256": "sha256-of-reviewed-read_only_process_inspector.py-bytes"
  }
}
```

Add this field only after explicit user permission. `subject_uid` must equal the nonzero real/effective UID of the unprivileged coordinator. Keep the host-origin confirmation and recovery authorization separately. Pin the new complete request digest before invoking the same guarded `recover-interrupted-packet --no-drive` command. A missing/null/malformed authorization does not opt in. The entire recovery runner refuses root/setuid execution.

## Privilege boundary

Only the bundled `scripts/read_only_process_inspector.py` code is elevated. The coordinator reads its bytes once, checks their reviewed hash and size, then passes those exact bytes to root-owned/non-user-writable system sudo and Python executables. It never imports the workflow, application or user-installed modules as root, and never executes a mutable script pathname under sudo.

The fixed invocation is noninteractive `sudo -n -- <system-python> -I -S -B -c <reviewed-bytes> <bounded-json-challenge>`. Environment input is reduced to system PATH and locale; sudo supplies its authenticated `SUDO_UID`. The helper requires real/effective UID 0 and matching nonzero `SUDO_UID`/subject UID. Python ignores ambient configuration, user/global site initialization and bytecode writes. There is no shell, credential collection, elevated validation or provider call. Root code writes only its stdout result and has a ten-second self-deadline; the caller has a fifteen-second deadline.

The helper reads fixed host/namespace identity and bounded kernel process identity/cwd metadata. It does not read application contents, command lines, credentials or process environments (only sudo's own invoking UID), write files, change permissions, install capabilities, kill processes or start services. Kernel cwd text is compared without traversing user-controlled filesystem paths as root. The existing deleted/unreachable/missing-cwd/ownership/identity uncertainty remains blocked. It scans the original user, **not UID 0**. A bounded rescan rejects new/recycled identities or unsettled inventory; no name/parent/time exemptions exist.

## Evidence and one-shot behavior

The unprivileged coordinator generates a fresh challenge binding a random nonce, reviewed request digest, subject UID, canonical worktree, machine/boot and PID/mount/user namespaces. Only the direct subprocess's successful response can supply evidence; there is no upload or receipt-file input.

Before sudo is invoked, an exclusive, fsynced `logs/privileged-inspections/<authorization-id>.attempt.json` consumes the authorization. The exact source and sanitized outcome are preserved separately. Failure, authentication unavailability, timeout, invalid output or coordinator crash never retries sudo under that authorization. A further attempt requires a new explicit user instruction and separately reviewed request; never manufacture a new ID to reuse a one-time approval. Successful reapplication of the already-committed recovery remains read-only/idempotent without another privileged call.

The coordinator validates the challenge digest, actual root role, original UID, bounded process identities and monotonic timing. Machine/boot/namespaces and freshness (at most fifteen seconds) are rechecked before projection. Immutable recovery evidence pins the authorization claim, executed source and result. Their hashes remain checked on later run loads. Historical receipts are audit evidence, never reusable privileged clearance for a new recovery.

All other recovery admission checks run before the privileged operation. Canonical run/agent/assignment/output/source evidence is rechecked afterward. Failure leaves canonical state and application work unchanged; the consumed authorization/diagnostic files remain as evidence. A successful `--no-drive` operation queues only the existing budgeted replacement, without launching it. Inspect the result and resume through LangGraph as before.

This restores visibility for the existing **point-in-time cwd inspection**. It is not a continuous writer lease or proof against arbitrary absolute-path writers; it does not silently expand the claim made by the existing recovery contract. No new registry, rootless trust-boundary redesign, approval change, application run/worktree or check waiver is introduced.
