"""A later accepted packet's incomplete check needs separate, bounded authority."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import test_interrupted_validation as original
import test_workflow_engine as fixtures
from workflow_engine import WorkflowError


class LaterBatch(original.InterruptedBatch):
    def __init__(self):
        super().__init__()
        self.partial_log = True
        self.same_tree = False
        self.unfinished_plan = False
        self.advisory_prior_failure = False
        self.advisory_final_failure = False
        self.prior_content = None

    def __call__(self, paths, **kwargs):
        code, manifest = super().__call__(paths, **kwargs)
        for path in paths:
            assignment = json.loads(path.read_text())
            output = Path(assignment['output_artifact'])
            result = json.loads(output.read_text())
            if assignment['stage'] == 'plan':
                result['tasks'][0]['validation_ids'].append('API-VAL-002')
                task = copy.deepcopy(result['tasks'][0])
                task.update(id='API-TASK-002', depends_on=['API-TASK-001'], expected_files=['feature.txt'],
                            summary='Finish the later approved vertical packet.')
                result['tasks'].append(task)
                packet = copy.deepcopy(result['work_packets'][0])
                packet.update(id='API-PACKET-002', task_ids=['API-TASK-002'], depends_on=['API-PACKET-001'])
                result['work_packets'].append(packet)
                if self.unfinished_plan:
                    result['tasks'].append(task | {'id': 'API-TASK-003', 'depends_on': ['API-TASK-002']})
                    result['work_packets'].append(packet | {'id': 'API-PACKET-003', 'task_ids': ['API-TASK-003'], 'depends_on': ['API-PACKET-002']})
                if self.advisory_prior_failure or self.advisory_final_failure:
                    result['validations'].append(result['validations'][0] | {
                        'id': 'API-VAL-003', 'command': 'python advisory-check.py', 'purpose': 'supplemental', 'gate': 'advisory'})
            elif assignment.get('packet_id') == 'API-PACKET-002':
                (Path(assignment['cwd']) / 'feature.txt').write_text(
                    self.prior_content if self.same_tree else 'Later approved source, not a replay.\n')
                row = result['validations'][1]
                row.update(result='not-run', exit_code=None, summary='Execution interrupted after partial output; no child exit observed.')
                if self.partial_log:
                    Path(row['log_path']).write_text('One test passed; interrupted before completion. Child exit unknown.\n')
                else:
                    row['log_path'] = None
                if self.advisory_final_failure:
                    result['validations'][2].update(result='fail', exit_code=1)
            elif assignment.get('validation_refresh'):
                self.prior_content = (Path(assignment['cwd']) / 'feature.txt').read_text()
                if self.advisory_prior_failure:
                    result['validations'][2].update(result='fail', exit_code=1)
            output.write_text(json.dumps(result) + '\n')
        return code, manifest


class LaterInterruptedValidationTests(unittest.TestCase):
    setUp = original.InterruptedValidationTests.setUp
    tearDown = original.InterruptedValidationTests.tearDown
    now = original.InterruptedValidationTests.now
    write_spec = original.InterruptedValidationTests.write_spec
    initialize = original.InterruptedValidationTests.initialize
    start = original.InterruptedValidationTests.start
    decision = original.InterruptedValidationTests.decision
    blocked_fixer = original.InterruptedValidationTests.blocked
    original_request = original.InterruptedValidationTests.request

    def blocked_later(self, batch=None):
        batch, engine, graph, config = self.blocked_fixer(batch or LaterBatch())
        first_request = self.original_request(engine)
        engine.apply_amendment(first_request)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertEqual(['API-VAL-002'], engine.validation_summary('api')['missing_ids'])
        return batch, engine, graph, config, first_request

    def request(self, engine):
        return self.original_request(engine) | {
            'decision': 'retry-later-interrupted', 'text': 'authorized to extend',
            'rationale': 'Separate authorization for the later packet; preserve the consumed earlier retry.',
            'interruption': {'kind': 'execution-interruption', 'harness_exit_code': None, 'child_exit_code': None}}

    def test_partial_coverage_gate_preserves_known_passes(self):
        _, engine, _, _, _ = self.blocked_later()
        blocker = engine.load_run()['blockers'][0]
        self.assertEqual(['API-VAL-002'], blocker['gate']['check_ids'])
        self.assertNotIn('API-VAL-001', blocker['summary'])
        self.assertEqual(1, blocker['summary'].count('API-VAL-002'))

    def test_extension_finishes_without_replacing_prior_claim_or_source_budget(self):
        batch, engine, graph, config, first_request = self.blocked_later()
        before = engine.load_run()
        source = engine.validation_summary('api')['source_artifact']
        original_bytes = Path(source['path']).read_bytes()
        request = self.request(engine)
        engine.apply_amendment(request)
        batch.reuse = True
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        after = engine.load_run()
        self.assertEqual('complete', after['status'])
        self.assertEqual(before['validation_retry_attempts'], after['validation_retry_attempts'])
        self.assertEqual(before['retry_limits'], after['retry_limits'])
        self.assertEqual(before['plan_review'], after['plan_review'])
        self.assertEqual(original_bytes, Path(source['path']).read_bytes())
        self.assertEqual(1, len(after['later_validation_retry_attempts']))
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))
        for req in (first_request, request):
            self.assertEqual('already-applied', engine.apply_amendment(req)['status'])
        self.assertEqual({}, engine._exclusions('api'))

    def test_old_overreported_gate_is_reconciled_only_for_passing_check_ids(self):
        _, engine, _, _, _ = self.blocked_later()
        # Emulate the persisted overbroad blocker from the previous engine.
        run = engine.load_run()
        run['blockers'][0]['gate']['check_ids'] = ['API-VAL-001', 'API-VAL-002']
        other = {'id': 'BLOCK-OTHER', 'kind': 'decision', 'summary': 'Unrelated unresolved decision.',
                 'evidence_path': str(engine.run_path), 'required_action': 'Resolve separately.'}
        run['blockers'].append(other)
        engine._save_run(run)
        engine.apply_amendment(self.request(engine))
        self.assertEqual([other], engine.load_run()['blockers'])
        self.assertTrue(engine.load_run()['pending_validation_refresh'])

    def test_second_failure_never_creates_a_third_retry(self):
        batch, engine, graph, config, _ = self.blocked_later()
        engine.apply_amendment(self.request(engine))
        batch.retry_outcome = 'fail'
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        with self.assertRaisesRegex(WorkflowError, 'exhausted'):
            engine.apply_amendment(self.request(engine))
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))

    def test_not_a_replacement_for_an_unconsumed_original_retry(self):
        _, engine, _, _ = self.blocked_fixer(LaterBatch())
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(self.request(engine))

    def test_original_verifier_must_have_only_passing_observations(self):
        batch = LaterBatch(); batch.advisory_prior_failure = True
        _, engine, _, _, _ = self.blocked_later(batch)
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(self.request(engine))

    def test_later_source_must_differ_from_original_verified_tree(self):
        batch = LaterBatch(); batch.same_tree = True
        _, engine, _, _, _ = self.blocked_later(batch)
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(self.request(engine))

    def test_all_plan_packets_must_be_complete(self):
        batch = LaterBatch(); batch.unfinished_plan = True
        _, engine, _, _, _ = self.blocked_later(batch)
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(self.request(engine))

    def test_known_nonpassing_extra_is_not_cleared(self):
        batch = LaterBatch(); batch.advisory_final_failure = True
        _, engine, _, _, _ = self.blocked_later(batch)
        run = engine.load_run()
        exact = copy.deepcopy(run['blockers'][0]); exact['id'] = 'BLOCK-EXACT'
        run['blockers'][0]['gate']['check_ids'].append('API-VAL-003')
        run['blockers'].append(exact)
        engine._save_run(run)
        engine.apply_amendment(self.request(engine))
        self.assertEqual(1, len(engine.load_run()['blockers']))
        self.assertEqual(['API-VAL-003'], engine.load_run()['blockers'][0]['gate']['check_ids'])

    def test_different_source_gate_is_not_cleared(self):
        _, engine, _, _, _ = self.blocked_later()
        run = engine.load_run()
        old_source = json.loads((self.run_dir / 'run-amendment-v1.json').read_text())['source_artifact']
        other = copy.deepcopy(run['blockers'][0])
        other.update(id='BLOCK-OTHER-SOURCE', evidence_path=old_source['path'])
        other['gate']['artifact'] = old_source
        run['blockers'].append(other)
        engine._save_run(run)
        engine.apply_amendment(self.request(engine))
        self.assertEqual([other], engine.load_run()['blockers'])

    def test_interruption_requires_a_pinned_partial_execution_log(self):
        batch = LaterBatch()
        batch.partial_log = False
        _, engine, _, _, _ = self.blocked_later(batch)
        source = engine.validation_summary('api')['source_artifact']
        request = self.decision(engine) | {'kind': 'validation-retry', 'decision': 'retry-later-interrupted',
            'text': 'authorized to extend', 'evidence': [source],
            'interruption': {'kind': 'execution-interruption', 'harness_exit_code': None, 'child_exit_code': None}}
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(request)

    def test_claim_crash_cannot_relaunch_either_verifier(self):
        _, engine, _, _, _ = self.blocked_later()
        earlier = copy.deepcopy(engine.load_run()['validation_retry_attempts'])
        engine.apply_amendment(self.request(engine))
        with mock.patch.object(engine, 'batch_runner', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.execute_phase('implement')
        self.assertEqual('blocked', engine.execute_phase('implement'))
        self.assertEqual(earlier, engine.load_run()['validation_retry_attempts'])
        self.assertTrue(engine.load_run()['later_validation_retry_attempts'])

    def test_stale_context_or_known_child_exit_is_rejected(self):
        _, engine, _, _, _ = self.blocked_later()
        request = self.request(engine)
        before = engine.run_path.read_bytes()
        for patch in ({'expected_context': '0' * 64},
                      {'interruption': request['interruption'] | {'child_exit_code': 1}},
                      {'interruption': request['interruption'] | {'harness_exit_code': 124}},
                      {'authority': 'coordinator', 'text': None}):
            with self.subTest(patch=patch), self.assertRaises(WorkflowError):
                engine.apply_amendment(request | patch)
            self.assertEqual(before, engine.run_path.read_bytes())

    def test_accepted_extension_crash_recovers_without_another_launch(self):
        batch, engine, graph, config, _ = self.blocked_later()
        engine.apply_amendment(self.request(engine))
        append = engine._append_event
        def crash(event, **kwargs):
            append(event, **kwargs)
            if event == 'artifact-accepted' and kwargs.get('action_id', '').startswith('validate:'):
                raise KeyboardInterrupt('Accepted later verifier before checkpoint.')
        with mock.patch.object(engine, '_append_event', side_effect=crash), self.assertRaises(KeyboardInterrupt):
            graph.invoke({'run_dir': str(self.run_dir)}, config)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_later_authorization_projection_crash_preserves_both_decisions(self):
        _, engine, _, _, _ = self.blocked_later()
        request = self.request(engine)
        earlier = copy.deepcopy(engine.load_run()['validation_retry_attempts'])
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            engine.apply_amendment(request)
        path = self.run_dir / 'run-amendment-v3.json'
        raw = path.read_bytes()
        self.assertEqual('applied', engine.apply_amendment(request)['status'])
        self.assertEqual(raw, path.read_bytes())
        self.assertEqual(earlier, engine.load_run()['validation_retry_attempts'])
        self.assertEqual('already-applied', engine.apply_amendment(request)['status'])

    def test_later_claim_cannot_be_written_into_original_claim_slot(self):
        _, engine, _, _, _ = self.blocked_later()
        engine.apply_amendment(self.request(engine))
        with mock.patch.object(engine, 'batch_runner', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            engine.execute_phase('implement')
        run = engine.load_run()
        run['validation_retry_attempts'] = run['later_validation_retry_attempts']
        with self.assertRaisesRegex(fixtures.artifact_guard.ValidationError, 'distinct original/later'):
            fixtures.artifact_guard.validate_run(run)

    def test_unfinished_later_result_cannot_escape_through_environment_resume(self):
        batch, engine, graph, config, _ = self.blocked_later()
        run = engine.load_run(); run['phase'] = 'validate'; engine._save_run(run)
        engine.apply_amendment(self.request(engine))
        def unfinished(assignment, result):
            result.update(status='blocked', blockers=[{'id': 'BLOCK-ENV', 'kind': 'environment',
                'summary': 'Fixture interrupted.', 'evidence_path': result['validations'][1]['log_path'],
                'required_action': 'Restore fixture.'}])
        batch.mutate = unfinished
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertTrue(engine.resume_external_blockers())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_complete_but_incomplete_verifier_does_not_launch_a_third_attempt(self):
        batch, engine, graph, config, _ = self.blocked_later()
        run = engine.load_run(); run['phase'] = 'validate'; engine._save_run(run)
        engine.apply_amendment(self.request(engine))
        batch.mutate = lambda _, result: result['validations'][1].update(result='not-run', exit_code=None)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))
        self.assertTrue(engine.load_run()['pending_validation_refresh'])
        # Old engines could have already lost the pending projection after acceptance.
        run = engine.load_run(); run['pending_validation_refresh'] = {}; run['status'] = 'working'
        engine._save_run(run)
        self.assertEqual('blocked', engine.execute_phase('validate'))
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_prior_successful_verifier_log_is_still_immutable_after_later_authorization(self):
        batch, engine, _, _, _ = self.blocked_later()
        run = engine.load_run()
        assignment = json.loads(Path(run['validation_retry_attempts']['api']['path']).read_text())
        prior = json.loads(Path(assignment['output_artifact']).read_text())
        engine.apply_amendment(self.request(engine))
        Path(prior['validations'][1]['log_path']).write_text('Tampered prerequisite verification log.\n')
        with self.assertRaises((WorkflowError, fixtures.artifact_guard.ValidationError)):
            engine.execute_phase('implement')
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_later_verifier_cannot_change_source(self):
        batch, engine, _, _, _ = self.blocked_later()
        earlier = copy.deepcopy(engine.load_run()['validation_retry_attempts'])
        engine.apply_amendment(self.request(engine))
        def mutate(assignment, result):
            (Path(assignment['cwd']) / 'feature.txt').write_text('Unapproved validation write.\n')
        batch.mutate = mutate
        self.assertEqual('blocked', engine.execute_phase('implement'))
        self.assertEqual(earlier, engine.load_run()['validation_retry_attempts'])
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_later_verifier_cannot_reuse_the_interrupted_target(self):
        batch, engine, _, _, _ = self.blocked_later()
        engine.apply_amendment(self.request(engine))
        batch.mutate = lambda _, result: result['validations'][1].update(cache_status='reused')
        self.assertEqual('blocked', engine.execute_phase('implement'))
        self.assertEqual(2, sum(a['stage'] == 'validate' for a in batch.assignments))

    def test_later_no_drive_does_not_launch_or_advance_checkpoint(self):
        import orchestrator
        from contextlib import contextmanager
        batch, engine, graph, config, _ = self.blocked_later()
        path = self.root / 'later-retry.json'
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
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))
        self.assertFalse(engine.load_run().get('later_validation_retry_attempts'))

    def test_later_partial_log_cannot_change_after_authorization(self):
        _, engine, _, _, _ = self.blocked_later()
        request = self.request(engine)
        engine.apply_amendment(request)
        Path(request['evidence'][1]['path']).write_text('Changed old partial log.\n')
        with self.assertRaises((WorkflowError, fixtures.artifact_guard.ValidationError)):
            engine.execute_phase('implement')

    def test_unknown_ids_in_old_blocker_are_not_cleared_as_passing(self):
        _, engine, _, _, _ = self.blocked_later()
        run = engine.load_run()
        run['blockers'][0]['gate']['check_ids'].append('API-VAL-999')
        engine._save_run(run)
        before = engine.run_path.read_bytes()
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(self.request(engine))
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_status_offers_separate_authority_not_replenished_original_retry(self):
        _, engine, _, _, _ = self.blocked_later()
        candidates = [a for a in engine.status_details()['eligible_actions'] if a.get('kind') == 'validation-retry']
        self.assertEqual(['retry-later-interrupted'], [a['decision'] for a in candidates])
        self.assertEqual(['API-VAL-002'], candidates[0]['check_ids'])
        self.assertEqual('user', candidates[0]['authority'])


if __name__ == '__main__':
    unittest.main()
