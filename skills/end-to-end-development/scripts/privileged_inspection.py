"""Explicit one-shot sudo transport; the orchestrator never changes its UID."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from read_only_process_inspector import host_context
from writer_incident import digest, preserve

SOURCE = Path(__file__).with_name('read_only_process_inspector.py')
MAX_AGE_SECONDS = 15


def validate_authorization(value: Any) -> None:
    fields = {'mode', 'authority', 'text', 'authorization_id', 'subject_uid', 'inspector_sha256'}
    if (not isinstance(value, dict) or set(value) != fields
            or value['mode'] != 'sudo-once' or value['authority'] != 'user'
            or not isinstance(value['text'], str) or not 1 <= len(value['text'].strip()) <= 4000
            or not isinstance(value['authorization_id'], str) or not re.fullmatch('[a-f0-9]{32}', value['authorization_id'])
            or type(value['subject_uid']) is not int or value['subject_uid'] <= 0
            or value['subject_uid'] != os.getuid() or os.geteuid() != os.getuid()
            or not isinstance(value['inspector_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['inspector_sha256'])):
        raise ValueError('separate one-time user authorization and the original unprivileged UID are required')


def trusted_binary(path: str) -> str:
    resolved = Path(path).resolve(strict=True)
    for item in (resolved, *resolved.parents, *Path(path).parents):
        info = item.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('inspection requires root-owned, non-writable system executables and ancestors')
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError('inspection executable must be a regular system file')
    return str(resolved)


def require_fresh(observation: dict[str, Any]) -> None:
    age = time.monotonic() - observation['finished_monotonic']
    if not 0 <= age <= MAX_AGE_SECONDS or observation['host'] != host_context():
        raise ValueError('privileged inspection is no longer fresh; do not reuse or repeat its authorization')


def inspect_once(run_dir: Path, worktree: Path, request_sha256: str,
                 authorization: dict[str, Any]) -> dict[str, Any]:
    validate_authorization(authorization)
    if not isinstance(request_sha256, str) or not re.fullmatch('[a-f0-9]{64}', request_sha256):
        raise ValueError('inspection must bind the reviewed recovery request')
    if not run_dir.is_absolute() or run_dir.resolve() != run_dir or worktree.resolve() != worktree:
        raise ValueError('inspection paths must be canonical')
    # Execute reviewed bytes, not a user-writable script pathname under sudo.
    source = SOURCE.read_bytes()
    if len(source) > 32768 or hashlib.sha256(source).hexdigest() != authorization['inspector_sha256']:
        raise ValueError('inspector source changed after review')
    sudo, python = trusted_binary('/usr/bin/sudo'), trusted_binary('/usr/bin/python3')
    challenge = {'nonce': secrets.token_hex(32), 'request_sha256': request_sha256,
                 'subject_uid': authorization['subject_uid'], 'worktree': str(worktree), 'host': host_context()}
    directory = run_dir / 'logs' / 'privileged-inspections'
    for item in (run_dir / 'logs', directory):
        item.mkdir(exist_ok=True)
        if item.resolve() != item:
            raise ValueError('inspection records must not follow directory aliases')
        # Persist each parent entry too: syncing only the new child loses the claim on host crash.
        descriptor = os.open(item.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    claim_path = directory / f"{authorization['authorization_id']}.attempt.json"
    claim = {'authorization': authorization, 'request_sha256': request_sha256, 'challenge': challenge}
    # Even a crash or failed authentication consumes this authorization; never auto-retry sudo.
    try:
        descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    except FileExistsError as error:
        raise ValueError('one-time inspection authorization was already consumed; no sudo retry') from error
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(claim, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    source_ref = preserve(claim_path.with_suffix('.source.py'), source)
    claim_ref = {'path': str(claim_path), 'sha256': hashlib.sha256(claim_path.read_bytes()).hexdigest()}
    started = time.monotonic()
    try:
        result = subprocess.run([sudo, '-n', '--', python, '-I', '-S', '-B', '-c', source.decode('utf-8'),
                                 json.dumps(challenge, sort_keys=True, separators=(',', ':'))],
                                cwd='/', env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        preserve(claim_path.with_suffix('.outcome.json'), b'{"status":"inspection-unavailable"}\n')
        raise ValueError('one-time sudo inspection unavailable; no recovery or automatic retry') from error
    if result.returncode != 0 or len(result.stdout) > 512 * 1024:
        preserve(claim_path.with_suffix('.outcome.json'), b'{"status":"inspection-unavailable"}\n')
        raise ValueError('one-time sudo inspection failed or requires operator authentication; no recovery or automatic retry')
    try:
        receipt = json.loads(result.stdout)
        fields = {'status', 'euid', 'subject_uid', 'challenge_sha256', 'started_monotonic', 'finished_monotonic', 'processes'}
        if (not isinstance(receipt, dict) or set(receipt) != fields or receipt['status'] != 'clear'
                or type(receipt['euid']) is not int or receipt['euid'] != 0
                or receipt['subject_uid'] != authorization['subject_uid']
                or receipt['challenge_sha256'] != digest(challenge)
                or type(receipt['started_monotonic']) not in (int, float)
                or type(receipt['finished_monotonic']) not in (int, float)
                or not started <= receipt['started_monotonic'] <= receipt['finished_monotonic'] <= time.monotonic()
                or not isinstance(receipt['processes'], list) or len(receipt['processes']) > 4096
                or any(not isinstance(row, list) or len(row) != 2 or any(type(x) is not int or x < 0 for x in row)
                       for row in receipt['processes'])
                or receipt['processes'] != sorted(receipt['processes'])
                or len({row[0] for row in receipt['processes']}) != len(receipt['processes'])):
            raise ValueError('invalid inspection receipt')
        observation = {'finished_monotonic': receipt['finished_monotonic'], 'host': challenge['host']}
        require_fresh(observation)
    except (ValueError, TypeError, KeyError) as error:
        preserve(claim_path.with_suffix('.outcome.json'), b'{"status":"invalid-receipt"}\n')
        raise ValueError('privileged inspection did not provide fresh authenticated evidence') from error
    evidence = {'authorization': authorization, 'challenge': challenge, 'receipt': receipt,
                'inspector_sha256': authorization['inspector_sha256'], 'transport': 'direct-sudo-stdout',
                'claim': claim_ref, 'source': source_ref}
    reference = preserve(claim_path.with_suffix('.outcome.json'), (json.dumps(evidence, indent=2) + '\n').encode())
    return {**observation, 'result': reference, 'evidence': [claim_ref, source_ref, reference]}
