#!/usr/bin/env python3
"""Durable guard for externally observable development effects.

The agent owns development. This module only records intent, reconciles an
idempotent external effect, and stores bounded observations and receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import delivery_tools

if os.name == "nt":
    import msvcrt
else:
    import fcntl


MAX_EVIDENCE_BYTES = 1024 * 1024
RUNTIME_DELIVERY_FIELDS = {
    "check_timeout_seconds",
    "git_write_timeout_seconds",
}
GUARD_CONTROLLED_DELIVERY_FIELDS = {
    "log_dir",
    "pr_intent_path",
    "run_id",
}
DELIVERY_FIELDS = {
    "base_branch",
    "baseline",
    "branch",
    "check_timeout_seconds",
    "commit_message",
    "expected_fingerprint",
    "git_write_timeout_seconds",
    "local_validation_summary",
    "pr_body",
    "pr_lifecycle",
    "pr_title",
    "remote",
    "repository",
    "task_files",
    "worktree",
}


class EffectGuardError(ValueError):
    """The requested effect cannot be represented safely."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(namespace: bytes, value: Any) -> str:
    return hashlib.sha256(namespace + _canonical_json(value).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_json(value: Mapping[str, Any]) -> str:
    encoded = _canonical_json(value)
    if len(encoded.encode()) > MAX_EVIDENCE_BYTES:
        raise EffectGuardError("effect observation exceeds the one MiB evidence limit")
    return encoded


def _stopped(reason_code: str, summary: str, *, effect_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "stopped",
        "effect_id": effect_id,
        "reason_code": reason_code,
        "summary": summary,
    }


class EffectGuard:
    """Persist and reconcile external effects through a two-operation interface."""

    def __init__(
        self,
        journal: Path,
        *,
        registry: Path | None = None,
        delivery_factory: Callable[[dict[str, Any]], Any] = delivery_tools.Delivery,
        now: Callable[[], str] = _now,
    ) -> None:
        self.journal = journal.resolve()
        state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self.registry = (
            registry or state_root / "end-to-end-development" / "effect-targets.sqlite"
        ).resolve()
        self.delivery_factory = delivery_factory
        self.now = now

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(f"{self.journal.as_uri()}?mode=ro", uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.journal, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS effects (
                effect_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                target_key TEXT NOT NULL,
                proposal_digest TEXT NOT NULL,
                proposal TEXT NOT NULL,
                approval_digest TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                effect_id TEXT NOT NULL REFERENCES effects(effect_id),
                observed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS receipts (
                effect_id TEXT PRIMARY KEY REFERENCES effects(effect_id),
                completed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )
        return connection

    def _connect_registry(self) -> sqlite3.Connection:
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.registry, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS target_claims (
                target_key TEXT PRIMARY KEY,
                effect_id TEXT NOT NULL,
                journal_path TEXT NOT NULL,
                proposal_digest TEXT NOT NULL,
                acquired_at TEXT NOT NULL
            );
            """
        )
        return connection

    def _release_claim(self, connection: sqlite3.Connection, target_key: str, effect_id: str) -> None:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM target_claims WHERE target_key = ? AND effect_id = ? AND journal_path = ?",
            (target_key, effect_id, str(self.journal)),
        )
        connection.commit()

    @contextmanager
    def _target_process_lock(self, target_key: str):
        lock_root = self.registry.parent / "effect-locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        lock_path = lock_root / f"{hashlib.sha256(target_key.encode()).hexdigest()}.lock"
        handle = lock_path.open("a+b")
        acquired = False
        try:
            try:
                if os.name == "nt":
                    if handle.tell() == 0:
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError) as error:
                raise EffectGuardError("another caller is reconciling this target") from error
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    @staticmethod
    def _normalise(effect: Mapping[str, Any]) -> tuple[dict[str, Any], str, str, str]:
        if not isinstance(effect, Mapping):
            raise EffectGuardError("effect must be an object")
        kind = effect.get("kind")
        if kind != "github-pull-request":
            raise EffectGuardError("unsupported effect kind")
        payload = effect.get("delivery")
        if not isinstance(payload, Mapping):
            raise EffectGuardError("github-pull-request requires a delivery object")
        repository = payload.get("repository")
        branch = payload.get("branch")
        if not isinstance(repository, str) or not repository:
            raise EffectGuardError("delivery repository must be a non-empty string")
        if not isinstance(branch, str) or not branch:
            raise EffectGuardError("delivery branch must be a non-empty string")
        change_set = effect.get("change_set")
        if change_set is not None and (not isinstance(change_set, str) or not change_set or len(change_set) > 256):
            raise EffectGuardError("change_set must be a non-empty string of at most 256 characters")
        approval_required = effect.get("approval_required", False)
        if not isinstance(approval_required, bool):
            raise EffectGuardError("approval_required must be boolean")

        delivery = dict(payload)
        unknown = set(delivery) - DELIVERY_FIELDS - GUARD_CONTROLLED_DELIVERY_FIELDS
        if unknown:
            raise EffectGuardError(f"unsupported delivery fields: {', '.join(sorted(unknown))}")
        for field in GUARD_CONTROLLED_DELIVERY_FIELDS:
            delivery.pop(field, None)
        if isinstance(delivery.get("worktree"), str):
            delivery["worktree"] = str(Path(delivery["worktree"]).resolve())
        identity_delivery = {
            key: value
            for key, value in delivery.items()
            if key not in RUNTIME_DELIVERY_FIELDS
        }
        if isinstance(identity_delivery.get("task_files"), list):
            identity_delivery["task_files"] = sorted(identity_delivery["task_files"])
        identity = {
            "kind": kind,
            "change_set": change_set,
            "approval_required": approval_required,
            "delivery": identity_delivery,
        }
        effect_id = _digest(b"end-to-end-development-effect-v1\0", identity)
        proposal_digest = _digest(b"end-to-end-development-proposal-v1\0", identity)
        target_key = f"github-pull-request:{repository.lower()}:{branch}"
        normalised = {
            "kind": kind,
            "change_set": change_set,
            "approval_required": approval_required,
            "delivery": delivery,
        }
        return normalised, effect_id, proposal_digest, target_key

    @staticmethod
    def _approval_digest(approval: Mapping[str, Any] | None, proposal_digest: str) -> str | None:
        if approval is None:
            return None
        if not isinstance(approval, Mapping):
            raise EffectGuardError("approval must be an object")
        if approval.get("proposal_digest") != proposal_digest:
            raise EffectGuardError("approval is not bound to the current proposal digest")
        actor = approval.get("actor")
        text = approval.get("text")
        if not isinstance(actor, str) or not actor.strip() or not isinstance(text, str) or not text.strip():
            raise EffectGuardError("approval requires non-empty actor and text")
        return _digest(
            b"end-to-end-development-approval-v1\0",
            {"proposal_digest": proposal_digest, "actor": actor, "text": text},
        )

    def _delivery_spec(self, effect_id: str, delivery: Mapping[str, Any]) -> dict[str, Any]:
        spec = dict(delivery)
        effect_root = self.journal.parent / "effects"
        spec["log_dir"] = str(effect_root / effect_id / "logs")
        spec["run_id"] = effect_id
        spec["pr_intent_path"] = str(effect_root / effect_id / "pr-creation-intent.json")
        Path(spec["log_dir"]).mkdir(parents=True, exist_ok=True)
        return spec

    def ensure(
        self,
        effect: Mapping[str, Any],
        *,
        approval: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ensure an external effect, reconciling an identical prior attempt first."""
        try:
            normalised, effect_id, proposal_digest, target_key = self._normalise(effect)
            approval_digest = self._approval_digest(approval, proposal_digest)
            proposal_json = _bounded_json(normalised)
        except (EffectGuardError, TypeError, ValueError) as error:
            return _stopped("invalid-effect", str(error))

        try:
            process_lock = self._target_process_lock(target_key)
            process_lock.__enter__()
        except EffectGuardError as error:
            return _stopped("target-busy", str(error), effect_id=effect_id)
        except OSError as error:
            return _stopped("target-lock-unavailable", f"target lock is unavailable: {error}", effect_id=effect_id)

        timestamp = self.now()
        try:
            connection = self._connect()
        except sqlite3.Error as error:
            process_lock.__exit__(None, None, None)
            return _stopped("journal-unavailable", f"effect journal is unavailable: {error}", effect_id=effect_id)
        try:
            registry = self._connect_registry()
        except sqlite3.Error as error:
            connection.close()
            process_lock.__exit__(None, None, None)
            return _stopped("registry-unavailable", f"target registry is unavailable: {error}", effect_id=effect_id)
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM effects WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            stored_identity_valid = True
            if existing is not None:
                try:
                    _, stored_id, stored_digest, stored_target = self._normalise(
                        json.loads(existing["proposal"])
                    )
                    stored_identity_valid = (
                        stored_id == effect_id
                        and stored_digest == proposal_digest
                        and stored_target == target_key
                    )
                except (EffectGuardError, TypeError, ValueError, json.JSONDecodeError):
                    stored_identity_valid = False
            if existing is not None and (
                existing["kind"] != normalised["kind"]
                or existing["target_key"] != target_key
                or existing["proposal_digest"] != proposal_digest
                or not stored_identity_valid
            ):
                connection.rollback()
                return _stopped("journal-integrity-violation", "stored effect identity conflicts with the proposal", effect_id=effect_id)
            if (
                existing is not None
                and existing["approval_digest"] is not None
                and approval_digest is not None
                and existing["approval_digest"] != approval_digest
            ):
                connection.rollback()
                return _stopped(
                    "authorization-mismatch",
                    "stored authorization differs from the supplied approval",
                    effect_id=effect_id,
                )
            receipt = connection.execute(
                "SELECT payload FROM receipts WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            if receipt is not None:
                connection.commit()
                self._release_claim(registry, target_key, effect_id)
                return json.loads(receipt["payload"])

            stored_approval_digest = existing["approval_digest"] if existing is not None else None
            if (
                normalised["approval_required"]
                and approval_digest is None
                and stored_approval_digest is None
            ):
                connection.rollback()
                return {
                    "status": "decision-required",
                    "effect_id": effect_id,
                    "proposal_digest": proposal_digest,
                    "reason_code": "approval-required",
                    "summary": "Approve this exact external-effect proposal before it is attempted.",
                }

            if existing is None:
                connection.execute(
                    "INSERT INTO effects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        effect_id,
                        normalised["kind"],
                        target_key,
                        proposal_digest,
                        proposal_json,
                        approval_digest,
                        "intent-recorded",
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE effects SET approval_digest = COALESCE(approval_digest, ?), "
                    "status = 'intent-recorded', updated_at = ? WHERE effect_id = ?",
                    (approval_digest, timestamp, effect_id),
                )
            connection.commit()

            registry.execute("BEGIN IMMEDIATE")
            claim = registry.execute(
                "SELECT effect_id, journal_path, proposal_digest FROM target_claims WHERE target_key = ?",
                (target_key,),
            ).fetchone()
            if claim is not None and (
                claim["effect_id"] != effect_id
                or claim["journal_path"] != str(self.journal)
                or claim["proposal_digest"] != proposal_digest
            ):
                registry.rollback()
                conflict = _stopped(
                    "target-conflict",
                    "another indeterminate effect owns this repository branch; reconcile its original journal first",
                    effect_id=effect_id,
                )
                conflict["blocking_effect_id"] = claim["effect_id"]
                conflict["blocking_journal"] = claim["journal_path"]
                return conflict
            if claim is None:
                registry.execute(
                    "INSERT INTO target_claims VALUES (?, ?, ?, ?, ?)",
                    (target_key, effect_id, str(self.journal), proposal_digest, timestamp),
                )
            registry.commit()

            try:
                delivery = self.delivery_factory(self._delivery_spec(effect_id, normalised["delivery"]))
                result = delivery.run()
            except Exception as error:
                result = {
                    "status": "blocked",
                    "effect_state": "indeterminate",
                    "reason_code": "indeterminate-effect-execution",
                    "summary": f"delivery adapter stopped unexpectedly ({type(error).__name__}); reconcile the identical effect",
                }
            if not isinstance(result, Mapping):
                result = {
                    "status": "blocked",
                    "effect_state": "indeterminate",
                    "reason_code": "invalid-effect-observation",
                    "summary": "delivery adapter returned an invalid observation",
                }
            delivery_result = dict(result)
            result_status = delivery_result.get("status")
            effect_state = delivery_result.get("effect_state")
            settled = effect_state in {"not-applied", "settled"}
            if not settled:
                outcome_status = "pending"
            elif result_status == "complete":
                outcome_status = "complete"
            elif result_status == "pending":
                outcome_status = "pending"
            else:
                outcome_status = "stopped"
            outcome = {
                "status": outcome_status,
                "effect_id": effect_id,
                "proposal_digest": proposal_digest,
                "reason_code": (
                    delivery_result.get("reason_code")
                    if settled
                    else "effect-outcome-indeterminate"
                ),
                "summary": (
                    delivery_result.get("summary", "External effect observed.")
                    if settled
                    else "The adapter outcome is indeterminate; reconcile the identical effect before revising it."
                ),
                "receipt": delivery_result,
            }
            payload = _bounded_json(outcome)

            timestamp = self.now()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO observations(effect_id, observed_at, status, payload) VALUES (?, ?, ?, ?)",
                (effect_id, timestamp, outcome_status, payload),
            )
            connection.execute(
                "UPDATE effects SET status = ?, updated_at = ? WHERE effect_id = ?",
                (outcome_status, timestamp, effect_id),
            )
            if outcome_status == "complete":
                connection.execute(
                    "INSERT OR IGNORE INTO receipts VALUES (?, ?, ?)",
                    (effect_id, timestamp, payload),
                )
            connection.commit()
            if settled:
                self._release_claim(registry, target_key, effect_id)
            return outcome
        except sqlite3.OperationalError as error:
            return _stopped("journal-busy", f"effect journal is busy: {error}", effect_id=effect_id)
        finally:
            registry.close()
            connection.close()
            process_lock.__exit__(None, None, None)

    def inspect(self, effect_id: str) -> dict[str, Any]:
        """Return the last durable observation without invoking an adapter."""
        if not isinstance(effect_id, str) or re.fullmatch(r"[0-9a-f]{64}", effect_id) is None:
            return _stopped("invalid-effect-id", "effect id must be a 64-character digest")
        if not self.journal.is_file():
            return _stopped("unknown-effect", "the effect journal has no matching intent", effect_id=effect_id)
        try:
            connection = self._connect(read_only=True)
        except sqlite3.Error as error:
            return _stopped("journal-unavailable", f"effect journal is unavailable: {error}", effect_id=effect_id)
        try:
            effect = connection.execute(
                "SELECT kind, target_key, proposal_digest, proposal, status, created_at, updated_at "
                "FROM effects WHERE effect_id = ?",
                (effect_id,),
            ).fetchone()
            if effect is None:
                return _stopped("unknown-effect", "the effect journal has no matching intent", effect_id=effect_id)
            try:
                proposal = json.loads(effect["proposal"])
                _, stored_id, stored_digest, stored_target = self._normalise(proposal)
            except (EffectGuardError, TypeError, ValueError, json.JSONDecodeError):
                return _stopped("journal-integrity-violation", "stored effect proposal is invalid", effect_id=effect_id)
            if (
                stored_id != effect_id
                or stored_digest != effect["proposal_digest"]
                or stored_target != effect["target_key"]
            ):
                return _stopped("journal-integrity-violation", "stored effect proposal does not match its identity", effect_id=effect_id)
            receipt = connection.execute(
                "SELECT payload FROM receipts WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            if receipt is not None:
                return json.loads(receipt["payload"])
            observation = connection.execute(
                "SELECT payload FROM observations WHERE effect_id = ? ORDER BY sequence DESC LIMIT 1",
                (effect_id,),
            ).fetchone()
            if observation is not None:
                outcome = json.loads(observation["payload"])
                outcome["proposal"] = proposal
                return outcome
            return {
                "status": "pending",
                "effect_id": effect_id,
                "proposal_digest": effect["proposal_digest"],
                "proposal": proposal,
                "reason_code": "effect-outcome-indeterminate",
                "summary": "The effect has durable intent but no settled observation; call ensure with the identical effect.",
            }
        finally:
            connection.close()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise EffectGuardError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".effect-", delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _exit_code(outcome: Mapping[str, Any]) -> int:
    return {"complete": 0, "pending": 8, "decision-required": 9}.get(str(outcome.get("status")), 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fingerprint = subparsers.add_parser("fingerprint", help="print the current Git content fingerprint")
    fingerprint.add_argument("worktree", type=Path)

    ensure = subparsers.add_parser("ensure", help="ensure and durably observe an external effect")
    ensure.add_argument("--journal", required=True, type=Path)
    ensure.add_argument("--input", required=True, type=Path)
    ensure.add_argument("--approval", type=Path)
    ensure.add_argument("--output", required=True, type=Path)

    inspect = subparsers.add_parser("inspect", help="read the last durable effect observation")
    inspect.add_argument("--journal", required=True, type=Path)
    inspect.add_argument("effect_id")
    inspect.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "fingerprint":
        print(delivery_tools.content_fingerprint(args.worktree.resolve()))
        return 0

    guard = EffectGuard(args.journal)
    if args.command == "ensure":
        outcome = guard.ensure(
            _load_object(args.input),
            approval=_load_object(args.approval) if args.approval else None,
        )
    else:
        outcome = guard.inspect(args.effect_id)
    _write_json(args.output, outcome)
    print(json.dumps(outcome, sort_keys=True))
    return _exit_code(outcome)


if __name__ == "__main__":
    raise SystemExit(main())
