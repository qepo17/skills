from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver
import test_workflow_engine as fixtures


class CorrectedDecisionKindTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def prepare(self, *, failed_check=False, legacy=False, partially_staged=False):
        batch = fixtures.FakeSuccessfulBatch(fail_first_validation=failed_check)

        def invalid_kind(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment['stage'] != 'implement':
                    continue
                output = Path(assignment['output_artifact'])
                payload = json.loads(output.read_text())
                payload['decisions'] = [
                    dict(id='DEC-001', kind='implementation', summary='Preserve existing behavior.', evidence='Approved fixture.'),
                    dict(id='DEC-002', kind='validation-environment', summary='Use an isolated cache for the same validation.', evidence='Existing validation log.'),
                ]
                output.write_text(json.dumps(payload) + '\n')
                if partially_staged:
                    feature = self.worktree / 'feature.txt'
                    feature.write_text('first staged content\n')
                    fixtures.subprocess.run(['git', 'add', 'feature.txt'], cwd=self.worktree, check=True)
                    feature.write_text('unchanged final worktree content\n')
                fixtures.workflow_tools.normalize_worker_artifact(path, assignment, output, payload)
                previous_path = fixtures.artifact_guard.CURRENT_ARTIFACT_PATH
                try:
                    fixtures.artifact_guard.CURRENT_ARTIFACT_PATH = output
                    fixtures.artifact_guard.validate_result(payload)
                except fixtures.artifact_guard.ValidationError as error:
                    self.assertEqual('$.decisions[1].kind', error.path)
                    worker = next(w for w in manifest['workers'] if w['action_id'] == assignment['action_id'])
                    worker.update(status='rejected', cleanup_status='complete', error_code=error.code,
                                  error_path=error.path, reason=str(error))
                    code = 1
                finally:
                    fixtures.artifact_guard.CURRENT_ARTIFACT_PATH = previous_path
            return code, manifest

        engine = self.initialize(invalid_kind, profile='full', legacy=legacy)
        graph = fixtures.build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'decision-kind'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume=dict(decision='approve', review_sha256=review['review_sha256'],
            text='approved all plans')), config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertIn('$.decisions[1].kind', engine.load_run()['blockers'][0]['summary'])
        self.assertFalse(engine.resume_external_blockers())
        assignment = next(a for a in batch.assignments if a['stage'] == 'implement')
        output = Path(assignment['output_artifact'])
        original = self.root / 'original-result.json'
        original.write_bytes(output.read_bytes())
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        payload = json.loads(output.read_text())
        payload['decisions'][1]['kind'] = 'validation'
        output.write_text(json.dumps(payload) + '\n')
        engine.batch_runner = batch
        return engine, graph, config, batch, original, output, digest

    def recover(self, engine, original, digest, **kwargs):
        return engine.retry_corrected_decision_kind(original, original_sha256=digest,
            decision_index=kwargs.pop('decision_index', 1), text=kwargs.pop('text', 'yea'), **kwargs)

    def test_full_graph_resumes_without_source_replay_or_changed_approval(self):
        engine, graph, config, batch, original, output, digest = self.prepare()
        before = engine.load_run()
        evidence = {p: p.read_bytes() for p in (original, output)}
        self.assertTrue(self.recover(engine, original, digest))
        after = engine.load_run()
        for key in ('plan_review', 'retry_limits', 'workflow_policy', 'worker_execution'):
            self.assertEqual(before.get(key), after.get(key))
        record = next(iter(after['corrected_handoff_recoveries'].values()))
        self.assertEqual('validation-kind', record['correction_kind'])
        self.assertEqual('yea', record['authorization_text'])
        self.assertEqual(digest, record['original_sha256'])
        self.assertFalse(self.recover(engine, original, digest))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        for p, raw in evidence.items(): self.assertEqual(raw, p.read_bytes())

    def test_failed_validation_stays_failed_and_does_not_pass_gate(self):
        engine, graph, config, _, original, output, digest = self.prepare(failed_check=True)
        checks = copy.deepcopy(json.loads(output.read_text())['validations'])
        self.assertTrue(self.recover(engine, original, digest))
        self.assertEqual(checks, json.loads(output.read_text())['validations'])
        self.assertIsNone(engine._current_validation('api', require_pass=True))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])

    def test_legacy_run_remains_legacy(self):
        engine, _, _, _, original, _, digest = self.prepare(legacy=True)
        self.assertTrue(self.recover(engine, original, digest))
        self.assertNotIn('validation_policy_version', engine.load_run())

    def reject(self, change, **kwargs):
        engine, _, _, _, original, output, digest = self.prepare()
        change(engine, original, output)
        before = engine.run_path.read_bytes()
        with self.assertRaises((fixtures.WorkflowError, fixtures.artifact_guard.ValidationError, ValueError, OSError)):
            if not self.recover(engine, original, digest, **kwargs):
                raise fixtures.WorkflowError('ineligible')
        self.assertEqual(before, engine.run_path.read_bytes())

    @staticmethod
    def change_json(path, change):
        data = json.loads(path.read_text()); change(data); path.write_text(json.dumps(data) + '\n')

    def test_other_result_field(self):
        self.reject(lambda e, o, p: self.change_json(p, lambda d: d.update(summary='changed claim')))

    def test_next_action_cannot_be_changed_together(self):
        self.reject(lambda e, o, p: self.change_json(p, lambda d: d.update(next_action='changed hint')))

    def test_original_cannot_be_freshened_to_hide_semantic_changes(self):
        def change(e, o, p):
            for f in (o, p): self.change_json(f, lambda d: d.update(summary='rewritten claim'))
        self.reject(change)

    def test_wrong_index(self):
        self.reject(lambda *_: None, decision_index=0)

    def test_wrong_target_kind(self):
        self.reject(lambda e, o, p: self.change_json(p, lambda d: d['decisions'][1].update(kind='implementation')))

    def test_empty_authorization(self):
        self.reject(lambda *_: None, text=' ')

    def test_negative_authorization(self):
        self.reject(lambda *_: None, text='not authorized')

    def test_authorization_is_bounded(self):
        self.reject(lambda *_: None, text=' ' * 4001 + 'yea')

    def test_source_drift(self):
        self.reject(lambda *_: (self.worktree / 'feature.txt').write_text('drift'))

    def test_index_drift(self):
        self.reject(lambda *_: fixtures.subprocess.run(['git', 'add', 'feature.txt'], cwd=self.worktree, check=True))

    def test_status_preserving_index_drift_is_rejected(self):
        engine, _, _, _, original, _, digest = self.prepare(partially_staged=True)
        before = fixtures.workflow_tools.repository_state(self.worktree)
        status = fixtures.subprocess.check_output(['git', 'status', '--short'], cwd=self.worktree)
        blob = fixtures.subprocess.check_output(['git', 'hash-object', '-w', '--stdin'],
            input=b'different staged content\n', cwd=self.worktree).decode().strip()
        fixtures.subprocess.run(['git', 'update-index', '--cacheinfo', '100644', blob, 'feature.txt'],
            cwd=self.worktree, check=True)
        after = fixtures.workflow_tools.repository_state(self.worktree)
        self.assertEqual(status, fixtures.subprocess.check_output(['git', 'status', '--short'], cwd=self.worktree))
        self.assertEqual(before['fingerprint'], after['fingerprint'])
        self.assertNotEqual(before['index_sha256'], after['index_sha256'])
        run = engine.run_path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError): self.recover(engine, original, digest)
        self.assertEqual(run, engine.run_path.read_bytes())

    def test_staged_handoff_without_pinned_index_fails_closed(self):
        engine, _, _, _, original, _, digest = self.prepare(partially_staged=True)
        with self.assertRaises(fixtures.WorkflowError): self.recover(engine, original, digest)

    def test_head_drift(self):
        self.reject(lambda *_: fixtures.subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'drift'], cwd=self.worktree, check=True))

    def test_log_drift(self):
        self.reject(lambda e, o, p: Path(json.loads(p.read_text())['validations'][0]['log_path']).write_text('drift'))

    def test_unclean_worker(self):
        def change(e, *_):
            agents = e.load_agents(); agents['agents'][-1]['cleanup_status'] = 'retained'; e._save_agents(agents)
        self.reject(change)

    def test_active_writer(self):
        def change(e, *_):
            run = e.load_run(); run['repositories']['api']['active_writer'] = 'active'; e._save_run(run)
        self.reject(change)

    def test_unrelated_blocker(self):
        def change(e, *_):
            run = e.load_run(); run['blockers'][0]['summary'] = 'Different decision.'; e._save_run(run)
        self.reject(change)

    def test_schema_invalid_corrected_output(self):
        self.reject(lambda e, o, p: self.change_json(p, lambda d: d['validations'][0].update(exit_code='bad')))

    def test_branch_drift(self):
        self.reject(lambda *_: fixtures.subprocess.run(['git', 'branch', '-m', 'drift'], cwd=self.worktree, check=True))

    def test_approval_drift(self):
        self.reject(lambda e, *_: Path(e.load_run()['plan_review']['review_path']).write_text('drift'))

    def test_wrong_digest(self):
        engine, _, _, _, original, _, _ = self.prepare()
        with self.assertRaises(fixtures.WorkflowError): self.recover(engine, original, '0' * 64)

    def test_generation_source_is_rechecked(self):
        engine, _, _, _, original, _, digest = self.prepare()
        # Inject only the already-validated assignment input at the source-state seam.
        import workflow_engine
        load = workflow_engine._load_json
        def with_generation(path):
            data = load(path)
            if 'output_artifact' in data and data.get('stage') == 'implement':
                data['generation_recovery'] = {'fixture': True}
            return data
        with mock.patch.object(workflow_engine, '_load_json', side_effect=with_generation), \
             mock.patch.object(fixtures.artifact_guard, 'validate_assignment'), \
             mock.patch('generation_recovery.verify_source', side_effect=fixtures.WorkflowError('producer drift')) as verify:
            with self.assertRaisesRegex(fixtures.WorkflowError, 'producer drift'):
                self.recover(engine, original, digest)
            verify.assert_called_once()

    def test_old_length_command_does_not_admit_enum_correction(self):
        engine, _, _, _, original, _, _ = self.prepare()
        self.assertFalse(engine.retry_corrected_handoff(original))

    def test_tampering_after_acceptance_is_detected(self):
        engine, _, _, _, original, _, digest = self.prepare()
        self.assertTrue(self.recover(engine, original, digest))
        original.write_text(original.read_text() + '\n')
        with self.assertRaises(fixtures.artifact_guard.ValidationError): engine.load_run()

    def test_crash_after_acceptance_does_not_replay_source(self):
        engine, graph, config, batch, original, _, digest = self.prepare()
        with mock.patch.object(engine, '_append_event', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.recover(engine, original, digest)
        self.assertFalse(self.recover(engine, original, digest))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_real_cli_no_drive_then_graph_continuation(self):
        engine, graph, config, batch, original, _, digest = self.prepare()
        command = [fixtures.sys.executable, str(fixtures.SCRIPTS_DIR / 'orchestrator.py'),
                   'retry-corrected-decision-kind', str(self.run_dir), '--original-artifact', str(original),
                   '--original-sha256', digest, '--decision-index', '1', '--text', 'yea', '--no-drive']
        result = fixtures.subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('working', json.loads(result.stdout)['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
