"""Admission, preservation, replay and graph gates for lost packet recovery."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import test_interrupted_packets as packets
import test_workflow_engine as fixtures
import interrupted_packet
import orchestrator
import workflow_tools
import worker_supervisor


class FinishPacket(fixtures.FakeSuccessfulBatch):
    def __call__(self, paths, **kwargs):
        assignment = json.loads(paths[0].read_text())
        worktree = Path(assignment['cwd'])
        if assignment['stage'] == 'implement':
            assert assignment['packet_id'] == 'API-PACKET-002' and assignment['attempt'] == 2
            (worktree / 'later.txt').write_text('finished preserved runtime work\n')
        if assignment['stage'] == 'deliver':
            self._git(worktree, 'add', 'later.txt')
        code, manifest = super().__call__(paths, **kwargs)
        if assignment['stage'] == 'implement':
            output = Path(assignment['output_artifact'])
            value = json.loads(output.read_text())
            value['changed_files'] = ['feature.txt', 'later.txt']
            output.write_text(json.dumps(value, indent=2) + '\n')
        return code, manifest


class InterruptedPacketRecoveryTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize
    interrupted = packets.InterruptedPacketTests.interrupted

    def incident(self):
        engine, graph, config, action, _ = self.interrupted('pending')
        state = engine.load_run()
        state['next_actions'] = []  # The old engine lost the action behind a stale gate.
        state['repositories']['api']['active_writer'] = None
        state['worker_execution']['backend'] = 'herdr'
        engine._save_run(state)
        self.assertEqual('blocked', engine.phase_implement())
        assignment = Path(action['assignment_path'])
        worker_path = self.run_dir / 'supervisor' / worker_supervisor.WorkerSupervisor.record_name(action['action_id'])
        worker_path.write_text(json.dumps({'action_id': action['action_id'], 'assignment_path': str(assignment),
            'backend': 'herdr', 'runtime': 'pi', 'cwd': str(self.worktree), 'agent_name': 'original-worker',
            'status': 'settled', 'cleanup_status': 'complete', 'started_at': '2026-08-22T10:00:00Z',
            'details': {'pane_id': 'w1:p1', 'workspace_id': 'w1'}}))
        request = {'run_id': engine.load_run()['run_id'], 'repo_id': 'api',
                   'run_sha256': interrupted_packet.reference(engine.run_path)['sha256'],
                   'agents_sha256': interrupted_packet.reference(engine.agents_path)['sha256'],
                   'assignment': interrupted_packet.reference(assignment),
                   'worker': interrupted_packet.reference(worker_path),
                   'output': interrupted_packet.reference(Path(action['output_artifact'])),
                   'repository_state': workflow_tools.repository_state(self.worktree),
                   'boot_ids': {'worker': 'a' * 32, 'current': 'b' * 32},
                   'local_host_confirmation': {'authority': 'user', 'question': interrupted_packet.HOST_CONFIRMATION_QUESTION,
                                               'text': 'yes', 'machine_id_sha256': 'f' * 64}}
        return engine, graph, config, request

    def recover(self, engine, request):
        with mock.patch.object(interrupted_packet, 'settlement', return_value={'proof': 'test host reboot'}):
            return interrupted_packet.recover(engine, request, request_sha256=interrupted_packet.digest(request), text='yess')

    def test_preserves_all_history_and_finishes_only_through_fresh_checks_review_and_delivery(self):
        engine, graph, config, request = self.incident()
        before = engine.load_run()
        evidence = {Path(ref['path']): Path(ref['path']).read_bytes() for ref in
                    list(before['repositories']['api']['accepted_artifacts'].values()) +
                    [request['assignment'], request['worker'], request['output']]}
        self.assertEqual('applied', self.recover(engine, request))
        after = engine.load_run()
        self.assertEqual(before['plan_review'], after['plan_review'])
        self.assertEqual(before['retry_limits'], after['retry_limits'])
        self.assertEqual(2, after['next_actions'][0]['attempt'])
        self.assertEqual(before['repositories']['api']['accepted_artifacts'], after['repositories']['api']['accepted_artifacts'])
        self.assertEqual('already-applied', self.recover(engine, request))
        batch = FinishPacket()
        engine.batch_runner = batch
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value=None), \
             mock.patch('workflow_tools.retry_worker_cleanups', return_value=[]):
            engine.reconcile()
            graph.invoke(None, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(['implement', 'review-1', 'deliver'], [a['stage'] for a in batch.assignments])
        self.assertTrue(next(a for a in batch.assignments if a['stage'] == 'implement')['validation_ids'])
        for path, content in evidence.items():
            self.assertEqual(content, path.read_bytes(), str(path))
        self.assertEqual('already-applied', self.recover(engine, request))

    def test_fresh_failure_blocks_before_review_or_delivery(self):
        engine, graph, config, request = self.incident()
        self.recover(engine, request)
        batch = FinishPacket()
        def fail_check(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            assignment = json.loads(paths[0].read_text())
            output = Path(assignment['output_artifact'])
            value = json.loads(output.read_text())
            check = value['validations'][0]
            check.update(result='fail', exit_code=1, summary='Fresh check failed.')
            Path(check['log_path']).write_text('Fresh check failed.\n')
            output.write_text(json.dumps(value))
            return code, manifest
        engine.batch_runner = fail_check
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value=None), \
             mock.patch('workflow_tools.retry_worker_cleanups', return_value=[]):
            engine.reconcile()
            graph.invoke(None, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(['implement'], [a['stage'] for a in batch.assignments])
        self.assertEqual('local-validation', engine.load_run()['blockers'][0]['gate']['type'])

    def test_missing_shutdown_proof_creates_no_recovery_or_replacement(self):
        engine, _, _, request = self.incident()
        before = engine.run_path.read_bytes()
        with mock.patch.object(interrupted_packet, 'settlement', side_effect=ValueError('unknown descendants')):
            with self.assertRaisesRegex(ValueError, 'unknown descendants'):
                interrupted_packet.recover(engine, request, request_sha256=interrupted_packet.digest(request), text='yes')
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(list((self.run_dir / 'assignments').glob('*attempt-2.json')))

    def test_stale_requests_and_generic_continue_are_rejected(self):
        engine, _, _, request = self.incident()
        with self.assertRaisesRegex(ValueError, 'authorization'):
            interrupted_packet.recover(engine, request, request_sha256=interrupted_packet.digest(request), text='continue')
        for key in ('run_sha256', 'agents_sha256'):
            stale = {**request, key: '0' * 64}
            with self.assertRaisesRegex(ValueError, 'changed after inspection'):
                self.recover(engine, stale)
        (self.worktree / 'later.txt').write_text('other writer changed source\n')
        with self.assertRaisesRegex(ValueError, 'changed after inspection'):
            self.recover(engine, request)

    def test_missing_operator_host_confirmation_is_not_inferred_from_repair_approval(self):
        engine, _, _, request = self.incident()
        request['local_host_confirmation']['text'] = ''
        with self.assertRaisesRegex(ValueError, 'local-host confirmation'):
            self.recover(engine, request)
        with mock.patch.object(interrupted_packet, 'machine_id_sha256', return_value='different-host'):
            with self.assertRaisesRegex(ValueError, 'differs from this machine'):
                interrupted_packet.settlement({}, request['boot_ids'], request['local_host_confirmation'])

    def test_preexisting_replacement_cannot_alias_prior_logs_or_noncanonical_output(self):
        engine, _, _, request = self.incident()
        assignment = json.loads(Path(request['assignment']['path']).read_text())
        resumed = {**assignment, 'instructions': sorted(set(assignment['instructions'] + [fixtures.artifact_guard.INTERRUPTED_PACKET_INSTRUCTION]))}
        path = engine._replacement(resumed)
        original = path.read_bytes()
        for key, value in [('log_dir', assignment['log_dir']), ('output_artifact', str(self.run_dir / 'elsewhere.json'))]:
            with self.subTest(key=key):
                replacement = json.loads(original)
                replacement[key] = value
                path.write_text(json.dumps(replacement))
                with self.assertRaisesRegex(ValueError, 'new unlaunched intent'):
                    self.recover(engine, request)
                path.write_bytes(original)
        self.assertEqual('blocked', engine.load_run()['status'])

    def test_snapshot_publication_crash_never_leaves_partial_final_bytes(self):
        path = self.root / 'snapshot.json'
        with mock.patch('writer_incident.os.link', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                interrupted_packet.preserve(path, b'{"complete": true}')
        self.assertFalse(path.exists())
        interrupted_packet.preserve(path, b'{"complete": true}')
        self.assertEqual(b'{"complete": true}', path.read_bytes())
        with self.assertRaises(ValueError):
            interrupted_packet.preserve(path, b'changed')
        self.assertEqual(b'{"complete": true}', path.read_bytes())

    def test_real_handoff_is_not_replayed(self):
        engine, _, _, request = self.incident()
        path = Path(request['output']['path'])
        value = json.loads(path.read_text())
        value['summary'] = 'Actual completed work, not an initializer.'
        path.write_text(json.dumps(value))
        request['output'] = interrupted_packet.reference(path)
        with self.assertRaisesRegex(ValueError, 'initialization placeholder'):
            self.recover(engine, request)

    def test_uncleaned_worker_cannot_be_replaced(self):
        engine, _, _, request = self.incident()
        path = Path(request['worker']['path'])
        value = json.loads(path.read_text())
        value['cleanup_status'] = 'pending'
        path.write_text(json.dumps(value))
        request['worker'] = interrupted_packet.reference(path)
        with self.assertRaisesRegex(ValueError, 'settled and cleaned'):
            self.recover(engine, request)

    def test_budget_is_not_reset(self):
        engine, _, _, request = self.incident()
        state = engine.load_run()
        state['retry_limits']['worker_replacements_per_stage'] = 0
        engine._save_run(state)
        request['run_sha256'] = interrupted_packet.reference(engine.run_path)['sha256']
        with self.assertRaisesRegex(ValueError, 'replacement budget'):
            self.recover(engine, request)

    def test_projection_crash_reuses_unlaunched_intent_and_history_drift_fails_closed(self):
        engine, _, _, request = self.incident()
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.recover(engine, request)
        replacement = next((self.run_dir / 'assignments').glob('*attempt-2.json'))
        content = replacement.read_bytes()
        self.assertEqual('applied', self.recover(engine, request))
        self.assertEqual(content, replacement.read_bytes())
        Path(request['output']['path']).write_text('{}')
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            engine.load_run()

    def test_cli_no_drive_leaves_checkpoint_and_workers_untouched(self):
        engine, _, _, request = self.incident()
        path = self.root / 'request.json'
        path.write_text(json.dumps(request))
        args = orchestrator.build_parser().parse_args(['recover-interrupted-packet', str(self.run_dir),
            '--input', str(path), '--request-sha256', interrupted_packet.digest(request), '--text', 'yes', '--no-drive'])
        with mock.patch.object(interrupted_packet, 'settlement', return_value={'proof': 'test reboot'}), \
             mock.patch.object(orchestrator, '_open_graph', side_effect=AssertionError('must not open checkpoint')):
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
        self.assertEqual('applied', result['recovery'])
        self.assertEqual('working', result['status'])
        self.assertFalse((self.run_dir / 'langgraph.sqlite').exists())


class BootProofTests(unittest.TestCase):
    def test_requires_unique_historical_boot_and_exact_current_kernel_identity(self):
        boots = [{'index': -1, 'boot_id': 'old', 'first_entry': 0, 'last_entry': 2_000_000},
                 {'index': 0, 'boot_id': 'new', 'first_entry': 3_000_000, 'last_entry': 5_000_000}]
        self.assertEqual('old', interrupted_packet.prove_boots(boots, 'new', '1970-01-01T00:00:01Z',
                         {'worker': 'old', 'current': 'new'})['worker_boot']['boot_id'])
        for started, expected in [('1970-01-01T00:00:04Z', {'worker': 'new', 'current': 'new'}),
                                  ('1970-01-01T00:00:01Z', {'worker': 'old', 'current': 'stale'})]:
            with self.assertRaises(ValueError):
                interrupted_packet.prove_boots(boots, 'new', started, expected)
        ambiguous = copy.deepcopy(boots)
        ambiguous[1]['first_entry'] = 1
        with self.assertRaises(ValueError):
            interrupted_packet.prove_boots(ambiguous, 'new', '1970-01-01T00:00:01Z', {'worker': 'old', 'current': 'new'})


if __name__ == '__main__':
    unittest.main()
