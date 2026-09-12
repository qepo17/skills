from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver

import test_workflow_engine as fixtures
import worker_supervisor
from workflow_engine import WorkflowError, build_graph


class InterruptedBatch(fixtures.FakeSuccessfulBatch):
    def __init__(self, *, timeout=False):
        super().__init__()
        self.timeout = timeout
        self.writes = 0

    def __call__(self, paths, **kwargs):
        assignment = json.loads(paths[0].read_text())
        if assignment['stage'] != 'implement':
            return super().__call__(paths, **kwargs)
        self.writes += 1
        if self.timeout:
            self.assignments.append(assignment)
            return 1, {'workers': [{
                'action_id': assignment['action_id'], 'agent_name': 'retained-writer',
                'status': 'timeout', 'settled': False, 'timed_out': True,
                'cleanup_status': 'retained', 'backend': 'test', 'handle_id': 'old-writer',
                'reason': 'writer is still running',
            }]}
        code, manifest = super().__call__(paths, **kwargs)
        output = Path(assignment['output_artifact'])
        result = json.loads(output.read_text())
        log = Path(assignment['log_dir']) / 'unfinished.log'
        log.write_text('External prerequisite is unavailable; source work is unfinished.\n')
        result.update(status='blocked', summary='Unfinished external prerequisite.', blockers=[{
            'id': 'BLOCK-EXTERNAL', 'kind': 'infrastructure',
            'summary': 'External prerequisite is unavailable.',
            'required_action': 'Restore the prerequisite and resume.', 'evidence_path': str(log),
        }])
        for check in result['validations']:
            check.update(result='not-run', exit_code=None, summary='Not executed while unfinished.')
        output.write_text(json.dumps(result, indent=2) + '\n')
        return code, manifest


class WriterLifecycleTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def start_blocked(self, batch):
        engine = self.initialize(batch)
        build_graph(engine, InMemorySaver()).invoke(
            {'run_dir': str(self.run_dir)},
            {'configurable': {'thread_id': 'writer-lifecycle'}, 'recursion_limit': 150},
        )
        return engine

    def test_unsettled_writer_never_launches_a_replacement(self):
        batch = InterruptedBatch(timeout=True)
        engine = self.start_blocked(batch)
        self.assertEqual(1, batch.writes)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual('retained', engine.load_agents()['agents'][-1]['cleanup_status'])

    def test_external_resume_never_normalizes_or_overwrites_accepted_blocked_output(self):
        batch = InterruptedBatch()
        engine = self.start_blocked(batch)
        original = next(a for a in batch.assignments if a['stage'] == 'implement')
        output = Path(original['output_artifact'])
        original_bytes = output.read_bytes()
        log_bytes = {f: f.read_bytes() for f in Path(original['log_dir']).iterdir() if f.is_file()}
        (self.worktree / 'feature.txt').write_text('Preserved external repair, not a validated pass.\n')
        self.assertTrue(engine.resume_external_blockers())
        pending = []
        def capture(paths, **kwargs):
            pending.extend(json.loads(p.read_text()) for p in paths)
            raise KeyboardInterrupt
        engine.batch_runner = capture
        with self.assertRaises(KeyboardInterrupt):
            engine.phase_implement()
        self.assertEqual(original_bytes, output.read_bytes())
        for path, content in log_bytes.items():
            self.assertEqual(content, path.read_bytes())
        self.assertEqual(1, len(pending))
        self.assertNotEqual(original['action_id'], pending[0]['action_id'])
        self.assertNotEqual(original['output_artifact'], pending[0]['output_artifact'])
        self.assertNotEqual(original['log_dir'], pending[0]['log_dir'])
        self.assertEqual(hashlib.sha256(original_bytes).hexdigest(),
                         engine.load_run()['repositories']['api']['accepted_artifacts'][original['action_id']]['sha256'])

    def test_execution_seam_refuses_an_accepted_output_even_with_allow_existing(self):
        batch = InterruptedBatch()
        engine = self.start_blocked(batch)
        original = next(a for a in batch.assignments if a['stage'] == 'implement')
        before = Path(original['output_artifact']).read_bytes()
        path = next(p for p in (self.run_dir / 'assignments').glob('*.json')
                    if json.loads(p.read_text())['action_id'] == original['action_id'])
        with self.assertRaisesRegex(WorkflowError, 'accepted'):
            engine._execute_assignments([path])
        self.assertEqual(before, Path(original['output_artifact']).read_bytes())
        self.assertEqual(1, batch.writes)

    def test_settled_but_uncleaned_source_is_not_accepted_or_replaced(self):
        batch = fixtures.FakeSuccessfulBatch()
        def worker(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            if json.loads(paths[0].read_text())['stage'] == 'implement':
                manifest['workers'][0].update(settled=True, cleanup_status='failed', cleanup_error='close failed')
            return code, manifest
        engine = self.start_blocked(worker)
        run = engine.load_run()
        source = next(a for a in batch.assignments if a['stage'] == 'implement')
        self.assertEqual('blocked', run['status'])
        self.assertEqual([source['action_id']], [a['action_id'] for a in run['next_actions']])
        self.assertNotIn(source['action_id'], run['repositories']['api']['accepted_artifacts'])
        self.assertEqual(['plan', 'implement'], [a['stage'] for a in batch.assignments])

    def test_batch_seam_does_not_normalize_a_settled_output_before_cleanup(self):
        batch = InterruptedBatch(timeout=True)
        engine = self.start_blocked(batch)
        source = next(a for a in batch.assignments if a['stage'] == 'implement')
        path = next(p for p in (self.run_dir / 'assignments').glob('*.json')
                    if json.loads(p.read_text())['action_id'] == source['action_id'])
        fixtures.FakeSuccessfulBatch()([path], run_dir=self.run_dir, worker_runtime='pi', allow_existing=True)
        output = Path(source['output_artifact'])
        before = output.read_bytes()
        outcome = {'action_id': source['action_id'], 'agent_name': 'fixture', 'assignment_path': str(path),
                   'backend': 'direct', 'handle_id': 'fixture', 'settled': True, 'timed_out': False,
                   'reason': 'cleanup failed', 'cleanup_status': 'failed', 'cleanup_error': 'close failed',
                   'started_at': self.now(), 'ended_at': self.now()}
        with mock.patch.object(worker_supervisor.WorkerSupervisor, 'run_batch', return_value=[outcome]), \
             mock.patch.object(fixtures.workflow_tools, 'normalize_worker_artifact') as normalize:
            code, manifest = fixtures.workflow_tools.run_assignment_batch([path], run_dir=self.run_dir,
                worker_runtime='pi', worker_backend='direct', allow_existing=True)
            normalize.assert_not_called()
        self.assertEqual(1, code)
        self.assertEqual('rejected', manifest['workers'][0]['status'])
        self.assertEqual(before, output.read_bytes())

    def test_unknown_starting_record_never_becomes_presumed_cleanup(self):
        batch = InterruptedBatch(timeout=True)
        engine = self.start_blocked(batch)
        source = next(a for a in batch.assignments if a['stage'] == 'implement')
        path = next(p for p in (self.run_dir / 'assignments').glob('*.json')
                    if json.loads(p.read_text())['action_id'] == source['action_id'])
        fixtures.FakeSuccessfulBatch()([path], run_dir=self.run_dir, worker_runtime='pi', allow_existing=True)
        output = Path(source['output_artifact'])
        before = output.read_bytes()
        record = self.run_dir / 'supervisor' / worker_supervisor.WorkerSupervisor.record_name(source['action_id'])
        record.write_text(json.dumps({'action_id': source['action_id'], 'status': 'starting',
                                     'cleanup_status': 'pending', 'handle_id': None}))
        self.assertTrue(engine.resume_external_blockers())
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value=None), \
             mock.patch('workflow_tools.retry_worker_cleanups', return_value=[]):
            engine.reconcile()
        run = engine.load_run()
        self.assertEqual('blocked', run['status'])
        self.assertEqual([source['action_id']], [a['action_id'] for a in run['next_actions']])
        self.assertNotIn(source['action_id'], run['repositories']['api']['accepted_artifacts'])
        self.assertEqual(before, output.read_bytes())

    def test_existing_supervisor_handle_is_adopted_not_overwritten(self):
        supervisor = worker_supervisor.WorkerSupervisor(
            self.run_dir, worker_supervisor.ExecutionContext('herdr', 'pi', 'test', {}))
        assignment = self.root / 'assignment.json'
        assignment.write_text('{}\n')
        request = worker_supervisor.WorkerRequest('implement:api:packet:attempt-1', 'old-worker',
                    assignment, self.worktree, 1, 'pi', 'test')
        path = self.run_dir / 'supervisor' / supervisor.record_name(request.action_id)
        path.parent.mkdir(parents=True)
        original = b'{"handle_id":"original","status":"timeout","cleanup_status":"retained"}\n'
        path.write_bytes(original)
        outcome = {'action_id': request.action_id, 'settled': False, 'timed_out': True,
                   'cleanup_status': 'retained'}
        with mock.patch.object(supervisor, 'recover', return_value=outcome) as recover, \
             mock.patch.object(supervisor, '_start') as launch:
            self.assertEqual([outcome], supervisor.run_batch([request]))
            recover.assert_called_once_with(request)
            launch.assert_not_called()
        self.assertEqual(original, path.read_bytes())
