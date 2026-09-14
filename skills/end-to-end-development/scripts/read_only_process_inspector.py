"""Standalone read-only procfs inspector; privileged entry point accepts no file output."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path


def inspect_process(process: Path, worktree: Path, subject_uid: int | None = None, *, kernel_path: bool = False) -> None:
    if subject_uid is None:
        subject_uid = os.getuid()
    unknown = (f'cannot inspect process {process.name}; worker settlement is unknown. '
               'No replacement is authorized. Obtain separately authorized trusted inspection; '
               'do not exclude protected processes or elevate the recovery runner.')
    try:
        if process.stat().st_uid != subject_uid:
            return
        descriptor = os.open(process, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except (FileNotFoundError, ProcessLookupError):
        return
    except OSError as error:
        raise ValueError(unknown) from error
    try:
        # Pin the proc directory: a recycled numeric PID must not stand in for exit evidence.
        if os.fstat(descriptor).st_uid != subject_uid:
            raise ValueError(unknown)
        try:
            cwd = os.readlink('cwd', dir_fd=descriptor)
            # Kernel deleted-path text is ambiguous and may collide with a real outside alias.
            if not os.path.isabs(cwd) or cwd.endswith(' (deleted)'):
                raise ValueError(unknown)
            resolved = Path(cwd) if kernel_path else Path(cwd).resolve(strict=True)
            if os.readlink('cwd', dir_fd=descriptor) != cwd:
                raise ValueError(unknown)
            if resolved.is_relative_to(worktree):
                raise ValueError('a process is still using the task worktree; settlement is not exclusive')
        except (FileNotFoundError, ProcessLookupError) as error:
            # Missing cwd can mean a deleted directory or an exited main thread, not process exit.
            try:
                os.stat('stat', dir_fd=descriptor)
            except (FileNotFoundError, ProcessLookupError):
                try:
                    process.stat()
                except (FileNotFoundError, ProcessLookupError):
                    return
            raise ValueError(unknown) from error
    except OSError as error:
        raise ValueError(unknown) from error
    finally:
        os.close(descriptor)


def host_context() -> dict:
    return {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-', ''),
            'machine_id_sha256': hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest(),
            'namespaces': {name: os.stat(f'/proc/self/ns/{name}').st_ino for name in ('pid', 'mnt', 'user')}}


def identity(process: Path, subject_uid: int) -> int | None:
    try:
        if process.stat().st_uid != subject_uid:
            return None
        data = (process / 'stat').read_bytes()
        if len(data) > 4096 or int(data.split(b' ', 1)[0]) != int(process.name):
            raise ValueError('invalid process identity')
        fields = data[data.rfind(b')') + 2:].split()
        ticks = int(fields[19])
        if ticks < 0 or process.stat().st_uid != subject_uid:
            raise ValueError('process ownership changed')
        return ticks
    except (FileNotFoundError, ProcessLookupError):
        if process.exists():
            raise ValueError('process identity is unavailable')
        return None


def owned_processes(subject_uid: int) -> dict[int, int]:
    result = {}
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        ticks = identity(process, subject_uid)
        if ticks is not None:
            result[int(process.name)] = ticks
        if len(result) > 4096:
            raise ValueError('process inventory exceeds bound')
    return result


def scan(worktree: Path, subject_uid: int) -> list[list[int]]:
    for _ in range(3):
        before = owned_processes(subject_uid)
        for pid, ticks in before.items():
            process = Path('/proc') / str(pid)
            current = identity(process, subject_uid)
            if current is None and not process.exists():
                continue
            if current != ticks:
                raise ValueError('process identity changed')
            # procfs supplies a kernel path; do not traverse user-controlled files as root.
            inspect_process(process, worktree, subject_uid, kernel_path=True)
            current = identity(process, subject_uid)
            if current != ticks and (current is not None or process.exists()):
                raise ValueError('process identity changed')
        after = owned_processes(subject_uid)
        if set(after.items()) <= set(before.items()):
            return [[pid, ticks] for pid, ticks in sorted(after.items())]
    raise ValueError('process inventory did not settle')


def main() -> int:
    signal.alarm(10)
    try:
        if os.getuid() != 0 or os.geteuid() != 0 or len(sys.argv) != 2 or len(sys.argv[1]) > 16384:
            raise ValueError('requires one authorized sudo inspection')
        request = json.loads(sys.argv[1])
        if set(request) != {'nonce', 'request_sha256', 'subject_uid', 'worktree', 'host'}:
            raise ValueError('invalid inspection request')
        uid = request['subject_uid']
        if type(uid) is not int or uid <= 0 or str(uid) != os.environ.get('SUDO_UID'):
            raise ValueError('inspection must target the invoking unprivileged UID')
        worktree = Path(request['worktree'])
        if not worktree.is_absolute() or os.path.normpath(str(worktree)) != request['worktree']:
            raise ValueError('worktree must be canonical')
        if host_context() != request['host']:
            raise ValueError('inspection host or namespace differs')
        started = time.monotonic()
        processes = scan(worktree, uid)
        if host_context() != request['host']:
            raise ValueError('inspection host changed')
        result = {'status': 'clear', 'euid': os.geteuid(), 'subject_uid': uid,
                  'challenge_sha256': hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                  'started_monotonic': started, 'finished_monotonic': time.monotonic(),
                  'processes': processes}
        print(json.dumps(result, separators=(',', ':')))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        print(json.dumps({'status': 'blocked', 'error': 'process inspection was not conclusive'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
