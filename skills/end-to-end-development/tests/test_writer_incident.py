from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver

import test_workflow_engine as fixtures
import artifact_guard
import orchestrator
import worker_supervisor
import test_writer_lifecycle as lifecycle
import workflow_tools
import writer_incident


class WriterIncidentTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def prepare(self, *, historical_validation=False):
        timeout = lifecycle.InterruptedBatch(timeout=True)
        engine = self.initialize(timeout, profile='full')
        graph = fixtures.build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'incident'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume={'decision': 'approve', 'review_sha256': review['review_sha256'],
                                             'text': 'approved all plans'}), config)
        source = next(a for a in timeout.assignments if a['stage'] == 'implement')
        source_path = next(p for p in (self.run_dir / 'assignments').glob('*.json')
                           if json.loads(p.read_text())['action_id'] == source['action_id'])
        # Synthetic historical incident only: emulate the old engine losing its
        # handle and launching attempt 2, not a supported production transition.
        agents = engine.load_agents()
        for agent in agents['agents']:
            agent.update(cleanup_status='complete', backend='herdr')
        engine._save_agents(agents)
        historical = engine.load_run()
        historical['next_actions'] = []
        historical['repositories']['api']['active_writer'] = None
        engine._save_run(historical)
        second_path = engine._replacement(source)
        second = json.loads(second_path.read_text())
        engine.batch_runner = lifecycle.InterruptedBatch()
        engine._execute_assignments([second_path])
        fixtures.FakeSuccessfulBatch()([source_path], run_dir=self.run_dir, worker_runtime='pi', allow_existing=True)
        if historical_validation:
            validation_path = engine.build_assignment(stage='validate', repo_id='api', scope='historical',
                instructions=['Historical isolated check fixture.'], validation_ids=source['validation_ids'],
                validation_commands=source['validation_commands'])
            engine.batch_runner = fixtures.FakeSuccessfulBatch()
            engine._execute_assignments([validation_path])
        engine._install_actions([second_path])
        run = engine.load_run()
        run.update(status='working', phase='implement', external_resume_generation=1, blockers=[])
        run['worker_execution'] = {'schema_version': 1, 'backend': 'herdr', 'runtime': 'pi',
                                   'detected_from': 'test', 'evidence': {}}
        run['next_actions'][0]['status'] = 'working'
        run['repositories']['api'].update(active_writer=second['action_id'], status='working')
        engine._save_run(run)
        agents = engine.load_agents()
        for agent in agents['agents']:
            agent.update(cleanup_status='complete', backend='herdr')
        engine._save_agents(agents)
        graph.update_state(config, {'run_dir': str(self.run_dir)}, as_node='reconcile')
        self.assertEqual(('implement',), graph.get_state(config).next)
        broken_path = Path(second['output_artifact'])
        broken = json.loads(broken_path.read_text())
        broken['summary'] = 'Overwritten by an unsafe external resume; no new checks ran.'
        broken_path.write_text(json.dumps(broken, indent=2) + '\n')
        request = {'run_id': run['run_id'], 'repo_id': 'api', 'source_action_id': source['action_id'],
                   'damaged_action_id': second['action_id'], 'run_sha256': writer_incident.reference(engine.run_path)['sha256'],
                   'source_sha256': writer_incident.reference(Path(source['output_artifact']))['sha256'],
                   'damaged_sha256': writer_incident.reference(broken_path)['sha256'],
                   'plan_review_sha256': review['review_sha256'],
                   'repository_state': workflow_tools.repository_state(self.worktree), 'worker_identities': {}}
        supervisor = mock.Mock()
        supervisor.close_settled_incident_workers.return_value = {
            'before': {'result': {'agents': []}}, 'workspaces_before': {'result': {'workspaces': []}},
            'observations': [], 'after': {'result': {'agents': []}}, 'workspaces_after': {'result': {'workspaces': []}}}
        return engine, graph, config, request, supervisor

    def apply(self, engine, request, supervisor, **kwargs):
        return writer_incident.recover(engine, request, request_sha256=writer_incident.digest(request),
                                       text='yes', supervisor=supervisor, **kwargs)

    def verifier(self, *, outcome='compatible', failed=False, edit=False):
        batch = fixtures.FakeSuccessfulBatch()
        def worker(paths, **kwargs):
            assignments = [json.loads(p.read_text()) for p in paths]
            if any(a.get('execution_mode') == 'packet-verification' for a in assignments):
                with mock.patch.dict(artifact_guard.VALIDATORS, result=lambda _: None):
                    code, manifest = batch(paths, **kwargs)
                for assignment in assignments:
                    output = Path(assignment['output_artifact'])
                    artifact = json.loads(output.read_text())
                    record = json.loads(Path(assignment['writer_incident']['path']).read_text())
                    evidence = Path(assignment['log_dir']) / 'scope.md'
                    evidence.write_text('Independent current-tree scope and combined source inspection.\n')
                    artifact['changed_files'] = record['changed_files']
                    artifact['packet_verification'] = {'outcome': outcome, 'summary': 'Fresh combined source inspection.',
                                                       'evidence_path': str(evidence)}
                    if failed:
                        artifact['validations'][0].update(result='fail', exit_code=1)
                    if outcome != 'compatible':
                        artifact.update(status='blocked', blockers=[{'id': 'BLOCK-SCOPE',
                            'kind': 'decision' if outcome == 'material-change' else 'code',
                            'summary': 'The current packet is incompatible or unfinished.',
                            'required_action': 'Resolve through normal bounded planning, not source replay.',
                            'evidence_path': str(evidence)}])
                    output.write_text(json.dumps(artifact) + '\n')
                if edit:
                    (self.worktree / 'feature.txt').write_text('Unauthorized verification edit.\n')
                return code, manifest
            return batch(paths, **kwargs)
        return worker, batch

    def test_recovery_preserves_history_and_requires_fresh_verification_and_remaining_gates(self):
        engine, graph, config, request, supervisor = self.prepare()
        original = engine.load_run(validate=False)
        original_run = engine.run_path.read_bytes()
        original_agents = engine.agents_path.read_bytes()
        files = {p: p.read_bytes() for p in (self.run_dir / 'assignments').glob('*.json')}
        before_tree = workflow_tools.repository_state(self.worktree)
        with self.assertRaises(artifact_guard.ValidationError):
            engine.load_run()
        self.assertEqual('applied', self.apply(engine, request, supervisor))
        recovered = engine.load_run()
        self.assertEqual('implement', recovered['phase'])
        self.assertEqual([], recovered['next_actions'])
        self.assertEqual(original_agents, engine.agents_path.read_bytes())
        self.assertEqual(before_tree, workflow_tools.repository_state(self.worktree))
        for key in ('validation_policy_version', 'delivery_policy_version', 'plan_review', 'retry_limits', 'workflow_policy', 'external_resume_generation'):
            self.assertEqual(original.get(key), recovered.get(key))
        self.assertEqual(original['repositories']['api']['baseline'], recovered['repositories']['api']['baseline'])
        expected_refs = dict(original['repositories']['api']['accepted_artifacts'])
        invalidated = expected_refs.pop(request['damaged_action_id'])
        self.assertEqual(expected_refs, recovered['repositories']['api']['accepted_artifacts'])
        record_ref = recovered['writer_incident_recoveries'][request['damaged_action_id']]
        record = json.loads(Path(record_ref['path']).read_text())
        self.assertEqual(invalidated, record['invalidated_reference'])
        self.assertEqual(original_run, Path(record['snapshots']['run']['path']).read_bytes())
        for path, content in files.items():
            self.assertEqual(content, path.read_bytes())
        self.assertEqual('already-applied', self.apply(engine, request, supervisor))
        self.assertEqual(1, supervisor.close_settled_incident_workers.call_count)
        engine.batch_runner, batch = self.verifier()
        graph.invoke(None, config)
        completed = engine.load_run()
        self.assertEqual('complete', completed['status'])
        implementation = [a for a in batch.assignments if a['stage'] == 'implement']
        self.assertEqual(1, len(implementation))
        verification = implementation[0]
        self.assertEqual('packet-verification', verification['execution_mode'])
        self.assertEqual(('none', 'none', 'none'), tuple(verification[k] for k in ('project_file_access', 'git_access', 'forge_access')))
        self.assertEqual({'implement', 'review-1', 'deliver'}, {a['stage'] for a in batch.assignments})
        accepted = json.loads(Path(verification['output_artifact']).read_text())
        self.assertTrue(all(v['cache_status'] == 'fresh' and v['result'] == 'pass' for v in accepted['validations']))
        self.assertNotIn(request['source_action_id'], completed['repositories']['api']['accepted_artifacts'])
        self.assertNotIn(request['damaged_action_id'], completed['repositories']['api']['accepted_artifacts'])
        self.assertEqual(request['source_sha256'], writer_incident.reference(Path(record['request']['result']['path']))['sha256'])
        self.assertEqual(request['damaged_sha256'], writer_incident.reference(Path(record['request']['damaged_result']['path']))['sha256'])

    def test_stale_run_source_or_authorization_never_closes_workers_or_changes_state(self):
        engine, _, _, request, supervisor = self.prepare()
        before = engine.run_path.read_bytes()
        for key in ('run_sha256', 'source_sha256', 'damaged_sha256', 'plan_review_sha256'):
            with self.subTest(key=key):
                bad = dict(request, **{key: '0' * 64})
                with self.assertRaises(ValueError):
                    self.apply(engine, bad, supervisor)
        with self.assertRaises(ValueError):
            writer_incident.recover(engine, request, request_sha256=writer_incident.digest(request), text='no', supervisor=supervisor)
        self.assertEqual(before, engine.run_path.read_bytes())
        (self.worktree / 'feature.txt').write_text('Source drift after request capture.\n')
        with self.assertRaisesRegex(ValueError, 'Git identity'):
            self.apply(engine, request, supervisor)
        supervisor.close_settled_incident_workers.assert_not_called()

    def test_unrelated_accepted_evidence_drift_cannot_be_quarantined(self):
        engine, _, _, request, supervisor = self.prepare()
        run = engine.load_run(validate=False)
        ref = next(ref for key, ref in run['repositories']['api']['accepted_artifacts'].items()
                   if key != request['damaged_action_id'])
        Path(ref['path']).write_bytes(Path(ref['path']).read_bytes() + b'\n')
        with self.assertRaises(artifact_guard.ValidationError):
            self.apply(engine, request, supervisor)
        supervisor.close_settled_incident_workers.assert_not_called()

    def test_unrelated_pinned_log_corruption_aborts_before_cleanup(self):
        engine, _, _, request, supervisor = self.prepare(historical_validation=True)
        run = engine.load_run(validate=False)
        artifacts = [json.loads(Path(ref['path']).read_text()) for ref in run['repositories']['api']['accepted_artifacts'].values()]
        validation = next(a for a in artifacts if a.get('stage') == 'validate')
        log = Path(validation['validations'][0]['log_path'])
        log.write_bytes(log.read_bytes() + b'changed prior accepted log\n')
        before = engine.run_path.read_bytes()
        with self.assertRaises(artifact_guard.ValidationError):
            self.apply(engine, request, supervisor)
        self.assertEqual(before, engine.run_path.read_bytes())
        supervisor.close_settled_incident_workers.assert_not_called()

    def test_pre_projection_crash_reuses_exact_immutable_intent_with_new_clock_and_cleanup(self):
        engine, _, _, request, supervisor = self.prepare()
        before = engine.run_path.read_bytes()
        with mock.patch.object(engine, '_save_run', side_effect=OSError('simulated pre-projection crash')):
            with self.assertRaisesRegex(OSError, 'pre-projection'):
                self.apply(engine, request, supervisor)
        self.assertEqual(before, engine.run_path.read_bytes())
        record_path = next((self.run_dir / 'logs' / 'incidents').glob('writer-recovery-*/recovery.json'))
        intent = record_path.read_bytes()
        engine.now = lambda: '2026-08-20T12:00:00Z'
        supervisor.close_settled_incident_workers.return_value = {
            **supervisor.close_settled_incident_workers.return_value, 'additional_observation': 'a later positive cleanup probe'}
        self.assertEqual('applied', self.apply(engine, request, supervisor))
        self.assertEqual(intent, record_path.read_bytes())
        self.assertEqual(2, supervisor.close_settled_incident_workers.call_count)
        self.assertEqual('implement', engine.load_run()['phase'])

    def test_retained_one_shot_verifier_is_adopted_after_settlement_without_relaunch(self):
        engine, graph, config, request, supervisor = self.prepare()
        self.apply(engine, request, supervisor)
        verify, batch = self.verifier()
        def retained(paths, **kwargs):
            code, manifest = verify(paths, **kwargs)
            manifest['workers'][0].update(status='timeout', settled=False, timed_out=True, cleanup_status='retained')
            return 1, manifest
        engine.batch_runner = retained
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value={'settled': False, 'cleanup_status': 'retained'}):
            graph.invoke(None, config)
        blocked = engine.load_run()
        self.assertEqual('blocked', blocked['status'])
        self.assertEqual(1, len(blocked['next_actions']))
        verify_id = blocked['next_actions'][0]['action_id']
        self.assertIn(verify_id, blocked['writer_incident_attempts'])
        self.assertNotIn(verify_id, blocked['repositories']['api']['accepted_artifacts'])
        self.assertEqual(1, len(batch.assignments))
        self.assertTrue(engine.resume_external_blockers())
        with mock.patch.object(engine, '_wait_for_crash_survivor', return_value={'settled': True, 'cleanup_status': 'complete'}):
            engine.reconcile()
        accepted = engine.load_run()
        self.assertEqual([], accepted['next_actions'])
        self.assertIn(verify_id, accepted['repositories']['api']['accepted_artifacts'])
        self.assertEqual(1, len(batch.assignments))
        engine.batch_runner, finish = self.verifier()
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertFalse(any(a['stage'] == 'implement' for a in finish.assignments))

    def test_cleanup_failure_preserves_invalid_status_and_all_outputs(self):
        engine, _, _, request, supervisor = self.prepare()
        before = engine.run_path.read_bytes()
        supervisor.close_settled_incident_workers.side_effect = RuntimeError('writer is still working')
        with self.assertRaisesRegex((RuntimeError, ValueError), 'working'):
            self.apply(engine, request, supervisor)
        self.assertEqual(before, engine.run_path.read_bytes())
        with self.assertRaises(artifact_guard.ValidationError):
            engine.load_run()

    def test_drift_during_cleanup_aborts_the_transition(self):
        engine, _, _, request, supervisor = self.prepare()
        before = engine.run_path.read_bytes()
        def drift(_, **kwargs):
            (self.worktree / 'feature.txt').write_text('Still writing.\n')
            return {'observations': []}
        supervisor.close_settled_incident_workers.side_effect = drift
        with self.assertRaisesRegex(ValueError, 'changed during'):
            self.apply(engine, request, supervisor)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_material_change_fails_checks_and_verifier_writes_all_remain_blocked(self):
        for options in ({'outcome': 'material-change'}, {'failed': True}, {'edit': True}):
            with self.subTest(options=options):
                # Each case has an independent temporary run and attempt budget.
                if hasattr(self, 'case_started'):
                    self.tearDown()
                    self.setUp()
                self.case_started = True
                engine, graph, config, request, supervisor = self.prepare()
                self.apply(engine, request, supervisor)
                engine.batch_runner, batch = self.verifier(**options)
                graph.invoke(None, config)
                self.assertEqual('blocked', engine.load_run()['status'])
                self.assertEqual(1, len(batch.assignments))
                self.assertFalse(any(a['stage'] in {'review-1', 'deliver'} for a in batch.assignments))

    def test_cli_no_drive_recovers_without_opening_or_editing_the_pending_checkpoint(self):
        engine, graph, config, request, supervisor = self.prepare()
        request_path = self.root / 'request.json'
        request_path.write_text(json.dumps(request))
        args = orchestrator.build_parser().parse_args(['recover-writer-incident', str(self.run_dir),
            '--input', str(request_path), '--request-sha256', writer_incident.digest(request), '--text', 'yes', '--no-drive'])
        checkpoint = graph.get_state(config)
        with mock.patch.object(orchestrator, 'WorkflowEngine', return_value=engine), \
             mock.patch.object(orchestrator, '_open_graph') as open_graph, \
             mock.patch.object(worker_supervisor.WorkerSupervisor, 'close_settled_incident_workers',
                               return_value=supervisor.close_settled_incident_workers.return_value):
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            open_graph.assert_not_called()
        self.assertEqual('applied', result['recovery'])
        self.assertEqual(('working', 'implement'), (result['status'], result['phase']))
        self.assertEqual(checkpoint, graph.get_state(config))

    def test_history_and_candidate_drift_is_detected_after_recovery(self):
        engine, _, _, request, supervisor = self.prepare()
        self.apply(engine, request, supervisor)
        ref = engine.load_run()['writer_incident_recoveries'][request['damaged_action_id']]
        record = json.loads(Path(ref['path']).read_text())
        candidate = Path(record['request']['result']['path'])
        candidate.write_bytes(candidate.read_bytes() + b'\n')
        with self.assertRaises(artifact_guard.ValidationError):
            engine.load_run()
