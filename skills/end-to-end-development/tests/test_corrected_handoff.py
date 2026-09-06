from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver

import test_workflow_engine as fixtures

artifact_guard = fixtures.artifact_guard
workflow_tools = fixtures.workflow_tools
WorkflowError = fixtures.WorkflowError


class CorrectedHandoffTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def prepare(self, *, failed_check: bool = False):
        batch = fixtures.FakeSuccessfulBatch(fail_first_validation=failed_check)

        def overlong(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment['stage'] == 'implement':
                    output = Path(assignment['output_artifact'])
                    payload = json.loads(output.read_text())
                    payload['next_action'] = 'Follow the planned next packet. ' * 20
                    output.write_text(json.dumps(payload) + '\n')
                    workflow_tools.normalize_worker_artifact(path, assignment, output, payload)
                    worker = next(w for w in manifest['workers'] if w['action_id'] == assignment['action_id'])
                    worker.update(status='rejected', cleanup_status='complete', error_code='invalid-evidence',
                                  error_path='$.next_action',
                                  reason='$.next_action: must be at most 300 characters')
                    code = 1
            return code, manifest

        engine = self.initialize(overlong, profile='full', legacy=True)
        graph = fixtures.build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'corrected-handoff'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume={
            'decision': 'approve', 'review_sha256': review['review_sha256'],
            'text': 'I approve all plans in this exact review bundle.',
        }), config)
        run = engine.load_run()
        self.assertEqual('blocked', run['status'])
        self.assertIn('$.next_action: must be at most 300 characters', run['blockers'][0]['summary'])
        self.assertFalse(engine.resume_external_blockers())
        assignment = next(a for a in batch.assignments if a['stage'] == 'implement')
        output = Path(assignment['output_artifact'])
        original = self.root / 'original-result.json'
        original.write_bytes(output.read_bytes())
        payload = json.loads(output.read_text())
        payload['next_action'] = 'Follow the planned next packet; preserve all validation and release gates.'
        output.write_text(json.dumps(payload) + '\n')
        engine.batch_runner = batch
        return engine, graph, config, batch, original, output

    def test_corrected_result_is_accepted_once_without_replaying_source(self):
        engine, graph, config, batch, original, output = self.prepare()
        before = engine.load_run()
        raw_original, raw_output = original.read_bytes(), output.read_bytes()
        self.assertTrue(engine.retry_corrected_handoff(original))
        recovered = engine.load_run()
        self.assertEqual(before['plan_review'], recovered['plan_review'])
        self.assertEqual(before['retry_limits'], recovered['retry_limits'])
        self.assertEqual(before.get('artifact_repairs'), recovered.get('artifact_repairs'))
        self.assertEqual(raw_original, original.read_bytes())
        self.assertEqual(raw_output, output.read_bytes())
        self.assertFalse(engine.retry_corrected_handoff(original))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'review-1' for a in batch.assignments))

    def test_failed_checks_are_preserved_not_turned_into_passes(self):
        engine, _, _, _, original, output = self.prepare(failed_check=True)
        validations = copy.deepcopy(json.loads(output.read_text())['validations'])
        self.assertTrue(engine.retry_corrected_handoff(original))
        self.assertEqual(validations, json.loads(output.read_text())['validations'])
        self.assertIsNone(engine._current_validation('api', require_pass=True))
        fixtures.build_graph(engine, InMemorySaver()).invoke(
            {'run_dir': str(self.run_dir)},
            {'configurable': {'thread_id': 'failed-check'}, 'recursion_limit': 150},
        )
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, len(engine._artifacts(repo_id='api', stage='validation-fix')))

    def test_cli_exposes_explicit_original_artifact_parameter(self):
        import orchestrator
        args = orchestrator.build_parser().parse_args([
            'retry-corrected-handoff', str(self.run_dir),
            '--original-artifact', str(self.root / 'original.json'),
        ])
        self.assertEqual('retry-corrected-handoff', args.command)
        self.assertEqual(self.root / 'original.json', args.original_artifact)

    def assert_rejected(self, change):
        engine, _, _, _, original, output = self.prepare()
        change(engine, original, output)
        before = engine.run_path.read_bytes()
        with self.assertRaises((WorkflowError, artifact_guard.ValidationError, ValueError, OSError)):
            if not engine.retry_corrected_handoff(original):
                raise WorkflowError('ineligible')
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_other_result_fields_cannot_be_rewritten(self):
        def change(_, __, output):
            payload = json.loads(output.read_text())
            payload['summary'] = 'Different claimed result.'
            output.write_text(json.dumps(payload))
        self.assert_rejected(change)

    def test_corrected_artifact_must_pass_the_entire_schema(self):
        def change(_, original, output):
            for path in (original, output):
                payload = json.loads(path.read_text())
                payload['validations'][0]['exit_code'] = 'invalid'
                path.write_text(json.dumps(payload))
        self.assert_rejected(change)

    def test_source_drift_is_not_normalized_away(self):
        self.assert_rejected(lambda *_: (self.worktree / 'feature.txt').write_text('changed\n'))

    def test_head_drift_is_rejected_even_without_content_changes(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(
            ['git', 'commit', '--allow-empty', '-qm', 'different HEAD'], cwd=self.worktree, check=True))

    def test_branch_drift_is_rejected(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(
            ['git', 'branch', '-m', 'different-branch'], cwd=self.worktree, check=True))

    def test_index_drift_is_rejected(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(
            ['git', 'add', 'feature.txt'], cwd=self.worktree, check=True))

    def test_approval_bundle_drift_is_rejected(self):
        self.assert_rejected(lambda engine, *_: Path(
            engine.load_run()['plan_review']['review_path']).write_text('changed plan\n'))

    def test_unrelated_decision_blocker_is_not_cleared(self):
        def change(engine, *_):
            run = engine.load_run()
            run['blockers'][0]['summary'] = 'Different decision.'
            engine._save_run(run)
        self.assert_rejected(change)

    def test_live_or_uncleaned_workers_prevent_recovery(self):
        def change(engine, *_):
            agents = engine.load_agents()
            agents['agents'][-1]['cleanup_status'] = 'retained'
            engine._save_agents(agents)
        self.assert_rejected(change)

    def test_original_and_evidence_are_hash_pinned_on_subsequent_load(self):
        engine, _, _, _, original, _ = self.prepare()
        self.assertTrue(engine.retry_corrected_handoff(original))
        original.write_text(original.read_text() + '\n')
        with self.assertRaises(artifact_guard.ValidationError):
            engine.load_run()

    def test_crash_after_acceptance_cannot_replay_the_writer(self):
        engine, graph, config, batch, original, _ = self.prepare()
        with mock.patch.object(engine, '_append_event', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.retry_corrected_handoff(original)
        self.assertFalse(engine.retry_corrected_handoff(original))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_cli_recovery_dispatch_returns_control_to_the_graph(self):
        import orchestrator
        engine, graph, config, batch, original, _ = self.prepare()
        args = orchestrator.build_parser().parse_args([
            'retry-corrected-handoff', str(self.run_dir), '--original-artifact', str(original),
        ])
        with mock.patch.object(orchestrator, '_open_graph') as opened:
            opened.return_value.__enter__.return_value = (engine, graph, config)
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
        self.assertEqual('complete', result['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
