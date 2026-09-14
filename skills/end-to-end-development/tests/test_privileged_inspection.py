"""No test invokes sudo: exercise its exact pipe/argument seam and real unprivileged procfs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_workflow_engine  # noqa: F401
import privileged_inspection as transport
import read_only_process_inspector as inspector


class PrivilegedInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.worktree = self.root / 'worktree'
        self.worktree.mkdir()
        self.authorization = {'mode': 'sudo-once', 'authority': 'user', 'text': 'Inspect once as root, read-only.',
                              'authorization_id': 'a' * 32, 'subject_uid': os.getuid(),
                              'inspector_sha256': hashlib.sha256(transport.SOURCE.read_bytes()).hexdigest()}
        self.calls = []
        self.mutate = lambda receipt: None

    def sudo(self, args, **kwargs):
        self.calls.append((args, kwargs))
        self.assertEqual(['/usr/bin/sudo', '-n', '--', '/usr/bin/python3', '-I', '-S', '-B', '-c'], args[:8])
        self.assertEqual(self.authorization['inspector_sha256'], hashlib.sha256(args[8].encode()).hexdigest())
        self.assertEqual('/', kwargs['cwd'])
        self.assertEqual({'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, kwargs['env'])
        self.assertEqual(subprocess.DEVNULL, kwargs['stdin'])
        self.assertEqual(15, kwargs['timeout'])
        self.assertNotIn('shell', kwargs)
        challenge = json.loads(args[9])
        self.assertEqual(os.getuid(), challenge['subject_uid'])
        self.assertEqual(str(self.worktree), challenge['worktree'])
        now = time.monotonic()
        receipt = {'status': 'clear', 'euid': 0, 'subject_uid': os.getuid(),
                   'challenge_sha256': transport.digest(challenge), 'started_monotonic': now,
                   'finished_monotonic': now, 'processes': [[123, 456]]}
        self.mutate(receipt)
        return subprocess.CompletedProcess(args, 0, json.dumps(receipt), '')

    def inspect(self, runner=None):
        with mock.patch.object(transport, 'trusted_binary', side_effect=lambda path: path), \
             mock.patch.object(transport.subprocess, 'run', side_effect=runner or self.sudo):
            return transport.inspect_once(self.root, self.worktree, 'b' * 64, self.authorization)

    def test_success_is_request_bound_and_preserves_the_exact_source_and_claim(self):
        result = self.inspect()
        self.assertEqual(1, len(self.calls))
        self.assertEqual(3, len(result['evidence']))
        for ref in result['evidence']:
            self.assertEqual(ref['sha256'], hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest())
        evidence = json.loads(Path(result['result']['path']).read_text())
        self.assertEqual(self.authorization, evidence['authorization'])
        self.assertEqual('direct-sudo-stdout', evidence['transport'])
        self.assertEqual('b' * 64, evidence['challenge']['request_sha256'])
        self.assertEqual(transport.SOURCE.read_bytes(), Path(evidence['source']['path']).read_bytes())
        with self.assertRaisesRegex(ValueError, 'already consumed'):
            self.inspect()
        self.assertEqual(1, len(self.calls))

    def test_directory_parent_entries_are_durable_before_the_first_sudo_attempt(self):
        synced = []
        fsync = os.fsync
        def sync(descriptor):
            synced.append(os.readlink(f'/proc/self/fd/{descriptor}'))
            return fsync(descriptor)
        def sudo(args, **kwargs):
            for parent in (self.root, self.root / 'logs', self.root / 'logs' / 'privileged-inspections'):
                self.assertIn(str(parent), synced)
            return self.sudo(args, **kwargs)
        with mock.patch.object(transport.os, 'fsync', side_effect=sync):
            self.inspect(sudo)
        self.assertEqual(1, len(self.calls))

    def test_failed_authentication_is_consumed_without_logging_stderr_or_retrying(self):
        def failed(args, **kwargs):
            self.calls.append(args)
            return subprocess.CompletedProcess(args, 1, '', 'PRIVATE STDERR MUST NOT BE RECORDED')
        with self.assertRaisesRegex(ValueError, 'authentication'):
            self.inspect(failed)
        with self.assertRaisesRegex(ValueError, 'already consumed'):
            self.inspect(failed)
        self.assertEqual(1, len(self.calls))
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn('PRIVATE STDERR', path.read_text())

    def test_crash_after_claim_never_reexecutes_sudo(self):
        with self.assertRaises(KeyboardInterrupt):
            self.inspect(lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
        with self.assertRaisesRegex(ValueError, 'already consumed'):
            self.inspect()
        self.assertFalse(self.calls)

    def test_bad_or_stale_receipt_is_never_clearance(self):
        cases = {'wrong nonce': {'challenge_sha256': '0' * 64}, 'unprivileged': {'euid': os.getuid()},
                 'wrong subject': {'subject_uid': 0}, 'wrong status': {'status': 'blocked'},
                 'old observation': {'started_monotonic': 0, 'finished_monotonic': 0},
                 'duplicate pid': {'processes': [[123, 1], [123, 2]]},
                 'invalid rows': {'processes': [[True, 1]]}, 'extra fields': {'extra': 'not allowed'}}
        for index, (name, values) in enumerate(cases.items()):
            with self.subTest(case=name):
                self.authorization['authorization_id'] = f'{index:032x}'
                self.mutate = lambda receipt, values=values: receipt.update(values)
                with self.assertRaisesRegex(ValueError, 'authenticated evidence'):
                    self.inspect()

    def test_unapproved_authority_uid_or_source_never_calls_sudo(self):
        original = copy.deepcopy(self.authorization)
        for values in ({'subject_uid': 0}, {'subject_uid': True}, {'subject_uid': os.getuid() + 1},
                       {'mode': 'auto'}, {'authority': 'coordinator'}, {'text': ''},
                       {'authorization_id': '../escape'}, {'inspector_sha256': '0' * 64}):
            with self.subTest(values=values):
                self.authorization = {**original, **values}
                with self.assertRaises(ValueError):
                    self.inspect()
        self.assertFalse(self.calls)
        self.assertFalse((self.root / 'logs').exists())

    def test_root_or_setuid_coordinator_is_rejected(self):
        with mock.patch.object(transport.os, 'getuid', return_value=0), \
             mock.patch.object(transport.os, 'geteuid', return_value=0):
            self.authorization['subject_uid'] = 0
            with self.assertRaisesRegex(ValueError, 'unprivileged UID'):
                self.inspect()
        self.assertFalse(self.calls)

    def test_observation_expires_and_cannot_cross_hosts_or_namespaces(self):
        observation = {'finished_monotonic': time.monotonic(), 'host': inspector.host_context()}
        transport.require_fresh(observation)
        observation['finished_monotonic'] -= 30
        with self.assertRaisesRegex(ValueError, 'fresh'):
            transport.require_fresh(observation)
        observation['finished_monotonic'] = time.monotonic()
        observation['host']['namespaces']['mnt'] += 1
        with self.assertRaisesRegex(ValueError, 'fresh'):
            transport.require_fresh(observation)

    def test_user_owned_executable_is_not_a_trusted_privilege_boundary(self):
        path = self.root / 'sudo'
        path.write_text('not a trusted binary')
        with self.assertRaisesRegex(ValueError, 'root-owned'):
            transport.trusted_binary(str(path))

    def test_standalone_source_cannot_claim_root_from_an_environment_variable(self):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(transport.SOURCE), '{}'],
                                env={'SUDO_UID': str(os.getuid())}, capture_output=True, text=True, timeout=15)
        self.assertEqual(1, result.returncode)
        self.assertEqual('blocked', json.loads(result.stdout)['status'])


class InspectorScanTests(unittest.TestCase):
    def test_explicit_subject_uid_is_used_even_when_the_inspector_is_root(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / '123'; p.mkdir()
            (p / 'cwd').symlink_to(temp, target_is_directory=True)
            with mock.patch.object(inspector.os, 'getuid', return_value=0):
                with self.assertRaisesRegex(ValueError, 'still using the task worktree'):
                    inspector.inspect_process(p, Path(temp), os.stat(p).st_uid, kernel_path=True)

    def test_new_identity_requires_rescan_and_persistent_churn_blocks(self):
        with mock.patch.object(inspector, 'owned_processes', side_effect=[{}, {123: 1}] * 3), \
             mock.patch.object(inspector, 'inspect_process') as inspect:
            with self.assertRaisesRegex(ValueError, 'did not settle'):
                inspector.scan(Path('/task'), 1000)
            inspect.assert_not_called()

    def test_recycled_identity_never_substitutes_for_an_observed_pid(self):
        with mock.patch.object(inspector, 'owned_processes', return_value={123: 1}), \
             mock.patch.object(inspector, 'identity', return_value=2), \
             mock.patch.object(inspector, 'inspect_process') as inspect:
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                inspector.scan(Path('/task'), 1000)
            inspect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
