"""Real process/filesystem evidence at interrupted-packet settlement's OS seam."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import test_workflow_engine  # noqa: F401 - makes the self-contained scripts importable
import interrupted_packet


class ProcessSettlementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.worktree = self.root / 'worktree'
        self.worktree.mkdir()
        self.boot = self.root / 'boot'
        self.boot.write_text('b' * 32)
        self.record = {'cwd': str(self.worktree), 'started_at': '2026-01-01T00:00:00Z',
                       'agent_name': 'original-worker', 'details': {'pane_id': 'old:p1', 'workspace_id': 'old'}}

    def process(self, pid='123', *, cwd=None):
        process = self.proc / pid
        process.mkdir()
        (process / 'stat').write_text('live process fixture\n')
        if cwd is not None:
            (process / 'cwd').symlink_to(cwd, target_is_directory=True)
        return process

    @contextmanager
    def observations(self):
        def path(value):
            return {'/proc': self.proc, '/proc/sys/kernel/random/boot_id': self.boot}.get(str(value), Path(value))
        run = subprocess.run
        def query(args, **kwargs):
            if args[0] == 'journalctl' or args[0] == os.environ.get('E2E_HERDR_BINARY', 'herdr'):
                value = {'result': {'agents': []}} if 'agent' in args else {'result': {'workspaces': []}}
                return subprocess.CompletedProcess(args, 0, json.dumps(value), '')
            return run(args, **kwargs)
        with mock.patch.object(interrupted_packet, 'Path', side_effect=path), \
             mock.patch.object(interrupted_packet, 'machine_id_sha256', return_value='f' * 64), \
             mock.patch.object(interrupted_packet, 'prove_boots', return_value={'proof': 'separate reboot gate'}), \
             mock.patch.object(interrupted_packet.subprocess, 'run', side_effect=query):
            yield

    def settle(self):
        with self.observations():
            return interrupted_packet.settlement(self.record, {}, {'machine_id_sha256': 'f' * 64})

    def test_readable_outside_cwd_is_allowed(self):
        self.process(cwd=self.root)
        self.assertEqual('separate reboot gate', self.settle()['proof'])

    def test_worktree_and_descendant_cwd_block(self):
        child = self.worktree / 'nested'
        child.mkdir()
        process = self.process(cwd=self.worktree)
        for cwd in (self.worktree, child):
            with self.subTest(cwd=cwd):
                (process / 'cwd').unlink()
                (process / 'cwd').symlink_to(cwd, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'still using the task worktree'):
                    self.settle()

    def test_missing_cwd_with_live_process_is_unknown_not_exited(self):
        self.process()
        with self.assertRaisesRegex(ValueError, 'process 123.*settlement is unknown'):
            self.settle()

    def test_deleted_cwd_target_is_unknown_not_exited(self):
        self.process(cwd=self.root / 'deleted (deleted)')
        with self.assertRaisesRegex(ValueError, 'process 123.*settlement is unknown'):
            self.settle()

    def test_deleted_cwd_suffix_cannot_resolve_through_an_existing_outside_alias(self):
        alias = self.worktree / 'removed (deleted)'
        alias.symlink_to(self.root, target_is_directory=True)
        self.process(cwd=alias)
        with self.assertRaisesRegex(ValueError, 'process 123.*settlement is unknown'):
            self.settle()

    def test_confirmed_exit_during_observation_is_allowed(self):
        process = self.process(cwd=self.root)
        readlink = os.readlink
        def exited(path, **kwargs):
            if path == 'cwd':
                shutil.rmtree(process)
                raise FileNotFoundError('fixture process exited')
            return readlink(path, **kwargs)
        with mock.patch.object(interrupted_packet.os, 'readlink', side_effect=exited):
            self.assertEqual('separate reboot gate', self.settle()['proof'])

    def test_reused_pid_is_not_accepted_as_exited_process(self):
        process = self.process(cwd=self.root)
        readlink = os.readlink
        def replaced(path, **kwargs):
            if path == 'cwd':
                shutil.rmtree(process)
                self.process(cwd=self.worktree)
                raise FileNotFoundError('original process exited; numeric PID reused')
            return readlink(path, **kwargs)
        with mock.patch.object(interrupted_packet.os, 'readlink', side_effect=replaced):
            with self.assertRaisesRegex(ValueError, 'process 123.*settlement is unknown'):
                self.settle()

    def test_missing_stat_with_remaining_process_is_not_confirmed_exit(self):
        process = self.process()
        (process / 'stat').unlink()
        with self.assertRaisesRegex(ValueError, 'process 123.*settlement is unknown'):
            self.settle()

    def test_cwd_change_during_observation_is_unknown(self):
        self.process(cwd=self.root)
        readlink = os.readlink
        observations = iter([str(self.root), str(self.worktree)])
        def changing(path, **kwargs):
            return next(observations) if path == 'cwd' else readlink(path, **kwargs)
        with mock.patch.object(interrupted_packet.os, 'readlink', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'process 123.*settlement is unknown'):
                self.settle()

    def test_unrelated_owned_process_permission_denial_is_not_an_exemption(self):
        self.process(cwd=self.root)
        readlink = os.readlink
        def denied(path, **kwargs):
            if path == 'cwd':
                raise PermissionError('fixture permission denial outside worktree')
            return readlink(path, **kwargs)
        with mock.patch.object(interrupted_packet.os, 'readlink', side_effect=denied):
            with self.assertRaisesRegex(ValueError, 'process 123.*settlement is unknown'):
                self.settle()

    @unittest.skipUnless(sys.platform == 'linux' and os.getuid() != 0, 'requires unprivileged Linux procfs')
    def test_real_nondumpable_sd_pam_named_child_remains_blocked_with_actionable_error(self):
        # A name-based exception would hide this real, unprivileged test process.
        script = '''
import ctypes, sys
libc = ctypes.CDLL(None, use_errno=True)
assert libc.prctl(15, b"(sd-pam)", 0, 0, 0) == 0
assert libc.prctl(4, 0, 0, 0, 0) == 0
print("ready", flush=True)
sys.stdin.read()
'''
        with subprocess.Popen([sys.executable, '-c', script], cwd=self.worktree,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
            try:
                self.assertEqual('ready', child.stdout.readline().strip())
                (self.proc / str(child.pid)).symlink_to(Path('/proc') / str(child.pid), target_is_directory=True)
                with self.assertRaisesRegex(ValueError, rf'process {child.pid}.*settlement is unknown'):
                    self.settle()
                self.assertIsNone(child.poll(), 'inspection must never stop a process')
            finally:
                child.stdin.close()
                child.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
