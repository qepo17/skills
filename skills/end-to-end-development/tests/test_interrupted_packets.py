"""Interrupted later packets must not lose their writer or evidence on resume."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver

import test_workflow_engine as fixtures
import worker_supervisor
from workflow_engine import build_graph


class InterruptedLaterPacket(fixtures.FakeSuccessfulBatch):
    def __call__(self, paths, **kwargs):
        assignment = json.loads(paths[0].read_text())
        if assignment.get('packet_id') == 'API-PACKET-002':
            self.assignments.append(assignment)
            (Path(assignment['cwd']) / 'later.txt').write_text('unfinished runtime import\n')
            fixtures.artifact_guard.initialize_artifact(paths[0])
            record = kwargs['run_dir'] / 'supervisor' / worker_supervisor.WorkerSupervisor.record_name(assignment['action_id'])
            record.parent.mkdir(exist_ok=True)
            record.write_text(json.dumps({
                'action_id': assignment['action_id'], 'status': 'working',
                'backend': 'direct', 'handle_id': 'original-worker',
                'cleanup_status': 'pending',
            }))
            raise KeyboardInterrupt
        code, manifest = super().__call__(paths, **kwargs)
        if assignment['stage'] == 'plan':
            output = Path(assignment['output_artifact'])
            plan = json.loads(output.read_text())
            task = copy.deepcopy(plan['tasks'][0])
            task.update(id='API-TASK-002', depends_on=['API-TASK-001'], expected_files=['later.txt'])
            plan['tasks'].append(task)
            packet = copy.deepcopy(plan['work_packets'][0])
            packet.update(id='API-PACKET-002', task_ids=['API-TASK-002'], depends_on=['API-PACKET-001'])
            plan['work_packets'].append(packet)
            output.write_text(json.dumps(plan, indent=2) + '\n')
        return code, manifest


class InterruptedPacketTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def interrupted(self, status='working'):
        batch = InterruptedLaterPacket()
        engine = self.initialize(batch)
        run = engine.load_run()
        run['worker_execution'] = {'schema_version': 1, 'backend': 'direct', 'runtime': 'pi',
                                   'detected_from': 'test', 'evidence': {}}
        engine._save_run(run)
        graph = build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'interrupted-later-packet'}, 'recursion_limit': 150}
        with self.assertRaises(KeyboardInterrupt):
            graph.invoke({'run_dir': str(self.run_dir)}, config)
        state = engine.load_run()
        action = state['next_actions'][0]
        action['status'] = status
        engine._save_run(state)
        return engine, graph, config, action, batch

    def assert_uncleaned(self, status):
        engine, graph, config, action, batch = self.interrupted(status)
        output = Path(action['output_artifact'])
        placeholder = output.read_bytes()
        predecessor = next(value for key, value in engine.load_run()['repositories']['api']['accepted_artifacts'].items()
                           if key.startswith('implement:'))
        predecessor_bytes = Path(predecessor['path']).read_bytes()
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value=None), \
             mock.patch('workflow_tools.retry_worker_cleanups', return_value=[]):
            engine.reconcile()
            graph.invoke(None, config)
        state = engine.load_run()
        self.assertEqual('blocked', state['status'])
        self.assertEqual([action['action_id']], [item['action_id'] for item in state['next_actions']])
        self.assertEqual(placeholder, output.read_bytes())
        self.assertEqual(predecessor_bytes, Path(predecessor['path']).read_bytes())
        self.assertNotIn(action['action_id'], state['repositories']['api']['accepted_artifacts'])
        self.assertEqual(2, sum(item['stage'] == 'implement' for item in batch.assignments))
        self.assertNotEqual('local-validation', state['blockers'][0].get('gate', {}).get('type'))

    def test_working_placeholder_is_not_normalized_or_forgotten_without_cleanup(self):
        self.assert_uncleaned('working')

    def test_pending_placeholder_is_not_normalized_or_forgotten_without_cleanup(self):
        self.assert_uncleaned('pending')

    def test_pending_later_packet_is_resolved_before_stale_predecessor_checks(self):
        engine, _, _, action, _ = self.interrupted('pending')
        paths_seen = []
        def capture(paths, **kwargs):
            paths_seen.extend(paths)
            raise KeyboardInterrupt
        engine.batch_runner = capture
        with self.assertRaises(KeyboardInterrupt):
            engine.phase_implement()
        self.assertEqual([action['assignment_path']], [str(path) for path in paths_seen])
        self.assertEqual('working', engine.load_run()['status'])
        self.assertEqual([action['action_id']], [item['action_id'] for item in engine.load_run()['next_actions']])

    def test_invalid_blocked_pending_output_uses_supervisor_rejection_before_replacement(self):
        engine, _, _, action, _ = self.interrupted('pending')
        state = engine.load_run()
        state['retry_limits']['artifact_repairs_per_action'] = 0
        engine._save_run(state)
        output = Path(action['output_artifact'])
        placeholder = json.loads(output.read_text())
        placeholder['status'] = 'blocked'  # Invalid: no factual blocker was completed.
        output.write_text(json.dumps(placeholder))
        seen = []
        def adopt_then_replace(paths, **kwargs):
            assignment = json.loads(paths[0].read_text())
            seen.append(assignment)
            if assignment['attempt'] == 2:
                raise KeyboardInterrupt
            return 1, {'workers': [{'action_id': assignment['action_id'], 'agent_name': 'original-worker',
                'status': 'rejected', 'settled': True, 'cleanup_status': 'complete',
                'reason': 'Original worker exited with invalid unfinished output.', 'error_code': 'invalid-evidence'}]}
        engine.batch_runner = adopt_then_replace
        with self.assertRaises(KeyboardInterrupt):
            engine.phase_implement()
        self.assertEqual([1, 2], [a['attempt'] for a in seen])
        self.assertEqual(2, engine.load_run()['next_actions'][0]['attempt'])
        self.assertNotEqual(seen[0]['log_dir'], seen[1]['log_dir'])

    def test_new_packet_still_requires_current_predecessor_checks(self):
        engine, _, _, _, _ = self.interrupted('pending')
        state = engine.load_run()
        state['next_actions'] = []
        state['repositories']['api']['active_writer'] = None
        engine._save_run(state)
        engine.batch_runner = mock.Mock(side_effect=AssertionError('must not start a new writer'))
        self.assertEqual('blocked', engine.phase_implement())
        self.assertEqual('local-validation', engine.load_run()['blockers'][0]['gate']['type'])
        engine.batch_runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
