"""A settled source fixer must not need another source budget to finish a check."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import test_validation_policy as policy
import test_workflow_engine as fixtures
from workflow_engine import WorkflowError


class InterruptedBatch(policy.PolicyBatch):
    def __init__(self):
        super().__init__(advisory=False, protected=True)
        self.retry_outcome = 'pass'
        self.fix_exit_code = 124
        self.mutate = None
        self.reuse = False

    def __call__(self, paths, **kwargs):
        code, manifest = super().__call__(paths, **kwargs)
        for path in paths:
            assignment = json.loads(path.read_text())
            output = Path(assignment['output_artifact'])
            result = json.loads(output.read_text())
            if assignment['stage'] == 'validation-fix':
                row = result['validations'][1]
                row.update(result='fail', exit_code=self.fix_exit_code, summary='Enclosing harness timeout; child exit is unknown.'
                           if self.fix_exit_code == 124 else 'Observed child assertion failure.')
                Path(row['log_path']).write_text('Five tests passed; enclosing harness timed out, no child exit.\n')
            if assignment.get('validation_refresh'):
                decision = json.loads(Path(assignment['validation_refresh']['path']).read_text())
                if decision['kind'] == 'validation-retry':
                    row = result['validations'][1]
                    row.update(result=self.retry_outcome, exit_code=0 if self.retry_outcome == 'pass' else 124)
                    Path(row['log_path']).write_text('Fresh child command outcome: ' + self.retry_outcome + '\n')
                    if self.reuse:
                        source = json.loads(Path(decision['source_artifact']['path']).read_text())
                        result['validations'][0] = copy.deepcopy(source['validations'][0])
                        result['validations'][0].update(cache_status='reused', source_artifact=decision['source_artifact'])
                    if self.mutate:
                        self.mutate(assignment, result)
            output.write_text(json.dumps(result) + '\n')
        return code, manifest


class InterruptedValidationTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize
    start = policy.ValidationPolicyTests.start
    decision = policy.ValidationPolicyTests.decision

    def blocked(self, batch=None):
        batch = batch or InterruptedBatch()
        engine, graph, config = self.start(batch)
        engine.apply_amendment(self.decision(engine) | {
            'kind': 'check-remediation', 'decision': 'fix-related', 'authority': 'coordinator', 'text': None,
            'rationale': 'Approved task caused this failure.',
            'evidence': [engine.validation_summary('api')['source_artifact']]})
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual(('blocked', 'implement'), (engine.load_run()['status'], engine.load_run()['phase']))
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))
        return batch, engine, graph, config

    def request(self, engine):
        source = engine.validation_summary('api')['source_artifact']
        result = json.loads(Path(source['path']).read_text())
        row = result['validations'][1]
        return self.decision(engine) | {
            'kind': 'validation-retry', 'decision': 'retry-interrupted',
            'text': 'Authorized: retry the interrupted validation without source work or waivers.',
            'rationale': 'Reviewed harness evidence records a timeout, not a child test failure.',
            'evidence': [source, {'path': row['log_path'], 'sha256': row['log_sha256']}],
            'interruption': {'kind': 'enclosing-harness-timeout', 'harness_exit_code': 124, 'child_exit_code': None}}

    def test_guarded_retry_finishes_without_another_writer_or_budget(self):
        batch, engine, graph, config = self.blocked()
        before = engine.load_run()
        source = engine.validation_summary('api')['source_artifact']
        original = Path(source['path']).read_bytes()
        request = self.request(engine)
        self.assertEqual('applied', engine.apply_amendment(request)['status'])
        self.assertEqual(before['retry_limits'], engine.load_run()['retry_limits'])
        batch.reuse = True
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(original, Path(source['path']).read_bytes())
        self.assertEqual(before['plan_review'], engine.load_run()['plan_review'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))
        retries = [a for a in batch.assignments if a.get('validation_refresh')]
        self.assertEqual(1, len(retries))
        self.assertTrue(all(retries[0][key] == 'none' for key in ('project_file_access', 'git_access', 'forge_access')))
        self.assertEqual({}, engine._exclusions('api'))
        self.assertEqual('already-applied', engine.apply_amendment(request)['status'])
        self.assertTrue(engine.validation_summary('api')['historical_failures'])

    def test_failed_retry_stays_blocked_and_cannot_replenish_itself(self):
        batch, engine, graph, config = self.blocked()
        batch.retry_outcome = 'fail'
        engine.apply_amendment(self.request(engine))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        with self.assertRaisesRegex(WorkflowError, 'retry.*exhausted'):
            engine.apply_amendment(self.request(engine))
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_invalid_requests_leave_state_untouched(self):
        _, engine, _, _ = self.blocked()
        request = self.request(engine)
        before = engine.run_path.read_bytes()
        cases = [request | {'evidence': []}, request | {'target': 'ci'},
                 request | {'authority': 'coordinator', 'text': None},
                 request | {'interruption': request['interruption'] | {'child_exit_code': 1}},
                 request | {'check_ids': ['API-VAL-001']}, request | {'expected_context': '0' * 64}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(WorkflowError):
                engine.apply_amendment(case)
            self.assertEqual(before, engine.run_path.read_bytes())

    def test_initial_packet_cannot_use_the_exhausted_fixer_recovery(self):
        batch = InterruptedBatch()
        engine, _, _ = self.start(batch)
        with self.assertRaisesRegex(WorkflowError, 'source-fix'):
            engine.apply_amendment(self.request(engine))

    def test_child_failure_after_fixer_is_not_an_interruption(self):
        batch = InterruptedBatch()
        batch.fix_exit_code = 1
        _, engine, _, _ = self.blocked(batch)
        with self.assertRaisesRegex(WorkflowError, 'harness'):
            engine.apply_amendment(self.request(engine))

    def test_retained_verifier_is_adopted_only_after_settlement(self):
        batch, engine, graph, config = self.blocked()
        engine.apply_amendment(self.request(engine))
        def retained(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            manifest['workers'][0].update(status='timeout', settled=False, cleanup_status='retained')
            return 1, manifest
        engine.batch_runner = retained
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value={'settled': False, 'cleanup_status': 'retained'}):
            graph.invoke({'run_dir': str(self.run_dir)}, config)
        blocked = engine.load_run()
        self.assertEqual('blocked', blocked['status'])
        self.assertEqual(1, len(blocked['next_actions']))
        action = blocked['next_actions'][0]['action_id']
        self.assertNotIn(action, blocked['repositories']['api']['accepted_artifacts'])
        self.assertTrue(engine.resume_external_blockers())
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value={'settled': True, 'cleanup_status': 'complete'}):
            engine.reconcile()
        self.assertIn(action, engine.load_run()['repositories']['api']['accepted_artifacts'])
        engine.batch_runner = batch
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_tampered_log_and_source_fail_closed(self):
        _, engine, _, _ = self.blocked()
        request = self.request(engine)
        log = Path(request['evidence'][1]['path'])
        original = log.read_bytes()
        log.write_text('made up success\n')
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(request)
        log.write_bytes(original)
        (self.worktree / 'feature.txt').write_text('external change\n')
        with self.assertRaisesRegex(WorkflowError, 'stale'):
            engine.apply_amendment(request)

    def test_retry_intent_is_idempotent_across_projection_crash(self):
        _, engine, _, _ = self.blocked()
        request = self.request(engine)
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.apply_amendment(request)
        intent = self.run_dir / 'run-amendment-v2.json'
        original = intent.read_bytes()
        self.assertEqual('applied', engine.apply_amendment(request)['status'])
        self.assertEqual(original, intent.read_bytes())
        self.assertEqual('already-applied', engine.apply_amendment(request)['status'])

    def reject_worker_mutation(self, mutate):
        batch, engine, _, _ = self.blocked()
        batch.mutate = mutate
        engine.apply_amendment(self.request(engine))
        self.assertEqual('blocked', engine.execute_phase('implement'))
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))
        self.assertFalse(engine.load_run()['repositories']['api']['accepted_artifacts'].get(
            next(a['action_id'] for a in batch.assignments if a['stage'] == 'validate')))

    def test_worker_cannot_reuse_interrupted_target(self):
        self.reject_worker_mutation(lambda _, result: result['validations'][1].update(cache_status='reused'))

    def test_worker_cannot_change_index(self):
        self.reject_worker_mutation(lambda *_: fixtures.subprocess.run(
            ['git', 'add', 'feature.txt'], cwd=self.worktree, check=True))

    def test_worker_cannot_change_branch(self):
        self.reject_worker_mutation(lambda *_: fixtures.subprocess.run(
            ['git', 'branch', '-m', 'wrong-branch'], cwd=self.worktree, check=True))

    def test_stale_pending_intent_never_launches(self):
        batch, engine, _, _ = self.blocked()
        engine.apply_amendment(self.request(engine))
        (self.worktree / 'feature.txt').write_text('changed after authorization\n')
        with self.assertRaisesRegex(WorkflowError, 'stale repository'):
            engine.execute_phase('implement')
        self.assertFalse(any(a['stage'] == 'validate' for a in batch.assignments))

    def test_acceptance_crash_recovers_without_relaunch(self):
        batch, engine, graph, config = self.blocked()
        engine.apply_amendment(self.request(engine))
        append = engine._append_event
        def crash(event, **kwargs):
            append(event, **kwargs)
            if event == 'artifact-accepted' and kwargs.get('action_id', '').startswith('validate:'):
                raise KeyboardInterrupt('accepted retry before checkpoint')
        with mock.patch.object(engine, '_append_event', side_effect=crash), self.assertRaises(KeyboardInterrupt):
            graph.invoke({'run_dir': str(self.run_dir)}, config)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_cli_no_drive_records_decision_but_launches_nothing(self):
        import orchestrator
        from contextlib import contextmanager
        batch, engine, graph, config = self.blocked()
        path = self.root / 'retry.json'
        path.write_text(json.dumps(self.request(engine)))
        @contextmanager
        def open_graph(*args, **kwargs):
            yield engine, graph, config
        args = orchestrator.build_parser().parse_args(['amend', str(self.run_dir), '--input', str(path), '--no-drive'])
        checkpoint = graph.get_state(config)
        with mock.patch.object(orchestrator, '_open_graph', open_graph), mock.patch.object(graph, 'invoke') as invoke:
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            invoke.assert_not_called()
        self.assertEqual('applied', result['amendment']['status'])
        self.assertEqual(checkpoint, graph.get_state(config))
        self.assertTrue(engine.load_run()['pending_validation_refresh'])
        self.assertFalse(any(a['stage'] == 'validate' for a in batch.assignments))

    def test_status_offers_only_a_review_required_candidate(self):
        _, engine, _, _ = self.blocked()
        candidates = [a for a in engine.status_details()['eligible_actions'] if a.get('kind') == 'validation-retry']
        self.assertEqual(1, len(candidates))
        self.assertEqual(['API-VAL-002'], candidates[0]['check_ids'])
        self.assertIn('124 alone is not proof', candidates[0]['requires'])
        engine.apply_amendment(self.request(engine))
        self.assertFalse(any(a.get('kind') == 'validation-retry' for a in engine.status_details()['eligible_actions']))

    def test_unfinished_validate_retry_cannot_escape_through_ordinary_resume(self):
        batch, engine, graph, config = self.blocked()
        run = engine.load_run()
        run['phase'] = 'validate'
        engine._save_run(run)
        def unfinished(assignment, result):
            result.update(status='blocked', blockers=[{'id': 'BLOCK-ENV', 'kind': 'environment',
                'summary': 'Fixture environment unavailable.', 'evidence_path': result['validations'][1]['log_path'],
                'required_action': 'Restore the fixture environment.'}])
        batch.mutate = unfinished
        engine.apply_amendment(self.request(engine))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertTrue(engine.resume_external_blockers())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_migration_guard_precedes_retry_launch(self):
        batch, engine, _, _ = self.blocked()
        engine.apply_amendment(self.request(engine))
        with mock.patch.object(engine, '_migration_guard', return_value=False) as guard:
            with self.assertRaisesRegex(WorkflowError, 'migration target'):
                engine.execute_phase('implement')
            guard.assert_called_once_with('api')
        self.assertFalse(any(a['stage'] == 'validate' for a in batch.assignments))
        self.assertFalse(engine.load_run().get('validation_retry_attempts'))

    def test_historical_log_drift_after_authorization_is_rejected(self):
        batch, engine, _, _ = self.blocked()
        request = self.request(engine)
        engine.apply_amendment(request)
        Path(request['evidence'][1]['path']).write_text('changed after authorization\n')
        with self.assertRaises((WorkflowError, fixtures.artifact_guard.ValidationError)):
            engine.execute_phase('implement')
        self.assertFalse(any(a['stage'] == 'validate' for a in batch.assignments))

    def test_historical_log_drift_during_retry_cannot_be_accepted(self):
        batch, engine, _, _ = self.blocked()
        request = self.request(engine)
        engine.apply_amendment(request)
        batch.mutate = lambda *_: Path(request['evidence'][1]['path']).write_text('tampered historical log\n')
        with self.assertRaises((WorkflowError, fixtures.artifact_guard.ValidationError)):
            engine.execute_phase('implement')
        run = json.loads(engine.run_path.read_text())
        retry = next(a for a in batch.assignments if a['stage'] == 'validate')
        self.assertNotIn(retry['action_id'], run['repositories']['api']['accepted_artifacts'])

    def test_malformed_crash_output_remains_unaccepted_in_reconciliation(self):
        batch, engine, _, _ = self.blocked()
        engine.apply_amendment(self.request(engine))
        batch.mutate = lambda _, result: result['validations'][1].pop('id')
        with mock.patch.object(engine, '_validate_worker_output', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute_phase('implement')
        engine.reconcile()
        self.assertEqual('blocked', engine.execute_phase('implement'))
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_claimed_crashed_verifier_is_not_launched_again(self):
        batch, engine, _, _ = self.blocked()
        engine.apply_amendment(self.request(engine))
        with mock.patch.object(engine, 'batch_runner', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute_phase('implement')
        self.assertTrue(engine.load_run()['validation_retry_attempts'])
        self.assertEqual('blocked', engine.execute_phase('implement'))
        self.assertEqual(0, sum(a['stage'] == 'validate' for a in batch.assignments))


if __name__ == '__main__':
    unittest.main()
