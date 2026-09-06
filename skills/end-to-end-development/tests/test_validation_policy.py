"""Workflow regressions for explicit local gates, tested at the engine/graph seam."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver

import test_workflow_engine as fixtures
from workflow_engine import WorkflowEngine, WorkflowError, build_graph


class PolicyBatch(fixtures.FakeSuccessfulBatch):
    def __init__(self, *, advisory=True, protected=False):
        super().__init__()
        self.advisory = advisory
        self.protected = protected

    def __call__(self, paths, **kwargs):
        code, manifest = super().__call__(paths, **kwargs)
        for path in paths:
            assignment = json.loads(path.read_text())
            output = Path(assignment['output_artifact'])
            artifact = json.loads(output.read_text())
            if assignment['stage'] == 'plan' and assignment['repo_id'] == 'api':
                artifact['validations'][0].update(
                    purpose='acceptance', gate='blocking', rationale='Verifies REQ-001.')
                artifact['validations'].append({
                    'id': 'API-VAL-002', 'command': 'python unrelated-check.py',
                    'cwd': assignment['cwd'], 'scope': 'broad', 'migration_capable': False,
                    'purpose': 'repository-required' if self.protected else 'supplemental',
                    'gate': 'advisory' if self.advisory else 'blocking',
                    'rationale': 'Additional unrelated regression observation.',
                })
            elif assignment['stage'] in {'implement', 'validate', 'fix-1'}:
                for record in artifact.get('validations', []):
                    if record['id'] == 'API-VAL-002':
                        record.update(result='fail', exit_code=1, summary="Unrelated checker: KeyError('fleetId').")
                        Path(record['log_path']).write_text("KeyError('fleetId')\n")
            output.write_text(json.dumps(artifact) + '\n')
        return code, manifest


class ChainBatch(PolicyBatch):
    """The existing fake worker, with an API → Core → UI contract and owned drafts."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prs = {}
        self.forge_writes = []

    def __call__(self, paths, **kwargs):
        code, manifest = super().__call__(paths, **kwargs)
        for path in paths:
            assignment = json.loads(path.read_text())
            output = Path(assignment['output_artifact'])
            value = json.loads(output.read_text())
            repo = assignment.get('repo_id')
            if assignment['stage'] == 'contract':
                value['requirement_map'] = {'REQ-001': ['api', 'core', 'ui']}
                value['dependencies'] = [{'from_repo_id': consumer, 'to_repo_id': producer,
                    'reason': 'Acceptance prerequisite.', 'evidence': 'Contract-first requirement.'}
                    for consumer, producer in [('core', 'api'), ('ui', 'core')]]
            elif assignment['stage'] == 'plan' and repo == 'api':
                for number in (3, 4, 5):
                    check = copy.deepcopy(value['validations'][0])
                    check.update(id=f'API-VAL-{number:03d}', command=f'python acceptance-{number}.py')
                    value['validations'].append(check)
                    value['tasks'][0]['validation_ids'].append(check['id'])
            elif assignment['stage'] == 'deliver':
                if repo not in self.prs:
                    self.prs[repo] = True
                    self.forge_writes.append(('create-draft', repo))
                if value['status'] == 'complete' and self.prs[repo]:
                    if assignment.get('verify_only'):
                        value.update(status='blocked', delivery_outcome='pending', reason_code='publication-required',
                            blockers=[{'id': 'BLOCK-PUBLISH', 'kind': 'infrastructure', 'summary': 'Owned draft requires publication.',
                                'evidence_path': value['checks'][0]['evidence_path'], 'required_action': 'Normal authorized delivery.'}])
                    else:
                        self.prs[repo] = False
                        self.forge_writes.append(('publish', repo))
                value.update(pr_url=f'https://example.test/{repo}/pull/1', pr_draft=self.prs[repo], pr_owned=True)
                import delivery_tools
                pin = assignment['pr_ownership']
                helper = delivery_tools.Delivery({'worktree': assignment['cwd'], 'log_dir': assignment['log_dir'],
                    'pr_intent_path': pin['intent_path'], 'repository': pin['repository'], 'branch': pin['branch'],
                    'base_branch': pin['base_branch'], 'run_id': assignment['run_id']})
                helper.load_creation_intent()
                helper.create_intent()
                observation = Path(assignment['log_dir']) / 'ownership.json'
                observation.write_text(json.dumps({'url': value['pr_url'], 'state': 'OPEN', 'headRefName': pin['branch'],
                    'baseRefName': pin['base_branch'], 'isDraft': value['pr_draft'],
                    'body': helper.body_with_managed_section('Fixture PR', 'Fixture observations.')}))
                value.update(creation_intent=delivery_tools.reference(helper.intent_path), ownership_observation=delivery_tools.reference(observation))
                if not value['pr_draft']:
                    helper.persist_once(helper.ready_path, {'creation_intent': value['creation_intent'], 'pr_url': value['pr_url']})
            output.write_text(json.dumps(value) + '\n')
        return code, manifest


class ValidationPolicyTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize
    github_engine = fixtures.WorkflowEngineTests.github_engine

    def start(self, batch, **kwargs):
        engine = self.initialize(batch, **kwargs)
        graph = build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'validation-policy'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        return engine, graph, config

    def start_chain(self, batch):
        def write_multi(**kwargs):
            fixtures.WorkflowEngineTests.write_spec(self, **kwargs)
            spec = json.loads(self.spec.read_text())
            spec['requirements'][0]['repository_ids'] = ['api', 'core', 'ui']
            for repo in ('core', 'ui'):
                root, worktree = self.root / (repo + '-repo'), self.root / (repo + '-worktree')
                fixtures.subprocess.run(['git', 'clone', '-q', str(self.repo), str(root)], check=True)
                for key, value in (('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid'), ('commit.gpgsign', 'false')):
                    fixtures.subprocess.run(['git', '-C', str(root), 'config', key, value], check=True)
                branch = 'feat/' + repo
                fixtures.subprocess.run(['git', 'worktree', 'add', '-qb', branch, str(worktree)], cwd=root, check=True)
                spec['repositories'].append({'repo_id': repo, 'root': str(root), 'worktree': str(worktree), 'branch': branch, 'base_branch': 'master'})
            self.spec.write_text(json.dumps(spec))
        with mock.patch.object(self, 'write_spec', side_effect=write_multi):
            return self.start(batch, profile='standard')

    def test_chain_advisory_handoff_preserves_all_acceptance_observations(self):
        batch = ChainBatch()
        engine, _, _ = self.start_chain(batch)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(['api', 'core', 'ui'], [a['repo_id'] for a in batch.assignments if a['stage'] == 'implement'])
        self.assertFalse([a for a in batch.assignments if a['stage'] in {'validation-fix', 'pipeline-fix'}])
        self.assertEqual(4, sum(r['result'] == 'pass' for r in engine.validation_summary('api')['checks']))

    def test_chain_exclusion_to_blocked_draft_to_verified_delivery(self):
        import orchestrator
        batch = ChainBatch(advisory=False)
        engine, graph, config = self.start_chain(batch)
        self.assertEqual(['api'], [a['repo_id'] for a in batch.assignments if a['stage'] == 'implement'])
        source = engine.validation_summary('api')['source_artifact']
        before = Path(source['path']).read_bytes()
        batch.delivery_code_failures = 1
        engine.apply_amendment(self.decision(engine))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(['api', 'core', 'ui'], [a['repo_id'] for a in batch.assignments if a['stage'] == 'implement'])
        self.assertEqual(3, len(orchestrator._result(engine)['pr_urls']))
        self.assertTrue(batch.prs['api'])
        self.assertTrue(engine.resume_delivery_checks())
        before_refresh = list(batch.forge_writes)
        engine.reconcile(refresh_completed=False)
        self.assertEqual(before_refresh, batch.forge_writes)
        self.assertEqual('publication-required', engine._artifacts(repo_id='api', kind='delivery')[-1][1]['reason_code'])
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(before, Path(source['path']).read_bytes())
        self.assertFalse(batch.prs['api'])
        self.assertEqual(3, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertFalse([a for a in batch.assignments if a['stage'] in {'validation-fix', 'pipeline-fix'}])

    def test_chain_protected_failure_cannot_release_downstream_packets(self):
        batch = ChainBatch(advisory=False, protected=True)
        engine, _, _ = self.start_chain(batch)
        self.assertEqual('blocked', engine.load_run()['status'])
        with self.assertRaisesRegex(WorkflowError, 'protected'):
            engine.apply_amendment(self.decision(engine))
        self.assertEqual(['api'], [a['repo_id'] for a in batch.assignments if a['stage'] == 'implement'])

    def test_advisory_failure_does_not_launch_an_unrelated_fix(self):
        batch = PolicyBatch()
        engine, _, _ = self.start(batch)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertFalse([a for a in batch.assignments if a['stage'] == 'validation-fix'])
        observations = [json.loads(Path(a['output_artifact']).read_text())
                        for a in batch.assignments if a['stage'] == 'implement']
        self.assertEqual('fail', observations[0]['validations'][1]['result'])
        self.assertEqual('advisory', engine.validation_summary('api')['checks'][1]['disposition'])

    def decision(self, engine, *, decision='exclude', ids=None):
        return {'kind': 'validation-exception', 'decision': decision, 'repo_id': 'api',
                'target': 'local', 'check_ids': ids or ['API-VAL-002'], 'authority': 'user',
                'text': 'Skip the unrelated allocation checker for this run.' if decision == 'exclude' else 'Restore that check.',
                'rationale': 'Explicit scoped user instruction; no claim of baseline proof.',
                'expected_context': engine.amendment_context('api')['sha256'], 'evidence': []}

    def test_exclusion_resumes_without_replaying_implementation(self):
        batch = PolicyBatch(advisory=False)
        engine, graph, config = self.start(batch)
        self.assertEqual(('blocked', 'implement'), (engine.load_run()['status'], engine.load_run()['phase']))
        self.assertFalse([a for a in batch.assignments if a['stage'] == 'validation-fix'])
        before = engine.load_run()
        source = next(Path(a['output_artifact']) for a in batch.assignments if a['stage'] == 'implement')
        original = source.read_bytes()
        request = self.decision(engine)
        self.assertEqual('applied', engine.apply_amendment(request)['status'])
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertEqual(original, source.read_bytes())
        self.assertEqual(before['plan_review'], engine.load_run()['plan_review'])
        self.assertEqual(before['retry_limits'], engine.load_run()['retry_limits'])
        self.assertEqual('excluded', engine.validation_summary('api')['checks'][1]['disposition'])
        final = engine.run_path.read_bytes()
        self.assertEqual('already-applied', engine.apply_amendment(request)['status'])
        self.assertEqual(final, engine.run_path.read_bytes())

    def test_protected_check_cannot_be_excluded(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False, protected=True))
        before = engine.run_path.read_bytes()
        with self.assertRaisesRegex(WorkflowError, 'protected'):
            engine.apply_amendment(self.decision(engine))
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(list(self.run_dir.glob('run-amendment-*.json')))

    def test_stale_decision_and_unfinished_work_are_not_repaired_by_policy(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        request = self.decision(engine)
        (self.worktree / 'feature.txt').write_text('unvalidated external edit\n')
        before = engine.run_path.read_bytes()
        with self.assertRaisesRegex(WorkflowError, 'stale'):
            engine.apply_amendment(request)
        request['expected_context'] = engine.amendment_context('api')['sha256']
        with self.assertRaisesRegex(WorkflowError, 'accepted evidence'):
            engine.apply_amendment(request)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_orphan_intent_and_post_projection_retry_are_idempotent(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        request = self.decision(engine)
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.apply_amendment(request)
        intent = self.run_dir / 'run-amendment-v1.json'
        original = intent.read_bytes()
        self.assertEqual('applied', engine.apply_amendment(request)['status'])
        self.assertEqual(original, intent.read_bytes())
        self.assertEqual('already-applied', engine.apply_amendment(request)['status'])
        self.assertEqual(1, len(engine.load_run()['run_amendments']))

    def test_restore_rechecks_without_replaying_a_source_packet(self):
        batch = PolicyBatch(advisory=False)
        engine, graph, config = self.start(batch)
        engine.apply_amendment(self.decision(engine))
        engine.apply_amendment(self.decision(engine, decision='restore'))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'validate' for a in batch.assignments))
        self.assertFalse(engine.load_run().get('pending_validation_refresh'))
        self.assertEqual('required', engine.validation_summary('api')['checks'][1]['disposition'])

    def test_related_remediation_uses_the_existing_single_fix_allowance(self):
        batch = PolicyBatch(advisory=False)
        engine, graph, config = self.start(batch)
        source = engine.validation_summary('api')['source_artifact']
        request = self.decision(engine) | {'kind': 'check-remediation', 'decision': 'fix-related',
                  'authority': 'coordinator', 'text': None, 'rationale': 'Task change caused this failure; repair stays in approved scope.',
                  'evidence': [source]}
        engine.apply_amendment(request)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        fixes = [a for a in batch.assignments if a['stage'] == 'validation-fix']
        self.assertEqual(1, len(fixes))
        self.assertEqual(['API-VAL-002'], fixes[0]['failed_validation_ids'])
        self.assertEqual(2, len(fixes[0]['validation_ids']))
        self.assertFalse(engine.load_run().get('pending_check_remediations'))

    def test_source_change_keeps_exclusion_but_not_observation_and_escapes_report(self):
        import orchestrator
        batch = PolicyBatch(advisory=False)
        batch.round_one_finding = True
        engine, graph, config = self.start(batch, report_requested=True)
        request = self.decision(engine)
        request['text'] = 'Exclude <img src=x onerror=alert(1)> for this approved run.'
        engine.apply_amendment(request)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        status = orchestrator._result(engine)
        self.assertEqual('complete', status['status'])
        self.assertIn('warnings/exclusions', status['summary'])
        row = status['local_gates']['api']['checks'][1]
        self.assertEqual(('excluded', 'not-run'), (row['disposition'], row['result']))
        self.assertEqual(1, len(engine.load_run()['run_amendments']))
        fixes = [a for a in batch.assignments if a['stage'] == 'fix-1']
        self.assertEqual(['API-VAL-001'], fixes[0]['validation_ids'])
        self.assertEqual(["python -m unittest"], fixes[0]['validation_commands'])
        self.assertTrue(status['local_gates']['api']['historical_failures'])
        rendered = Path(status['report_paths'][0]).read_text()
        self.assertIn('Active exclusions', rendered)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', rendered)
        self.assertNotIn('<img src=x', rendered)
        self.assertIn('Historical failures — not current observations', rendered)

    def test_newer_failed_observation_never_reuses_an_older_pass(self):
        batch = PolicyBatch(advisory=False)
        engine, _, _ = self.start(batch)
        engine.apply_amendment(self.decision(engine))
        self.assertIsNotNone(engine._current_validation('api', require_pass=True))
        batch.always_fail_validation = True
        assignment = engine._validation_assignment('api', 'newer-observation')
        engine._run_with_replacements([assignment])
        self.assertIsNone(engine._current_validation('api', require_pass=True))
        self.assertEqual('fail', engine.validation_summary('api')['checks'][0]['result'])

    def test_tampered_current_log_cannot_be_waived(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        log = Path(engine.validation_summary('api')['checks'][1]['log_path'])
        log.write_text('fabricated passing output\n')
        before = engine.run_path.read_bytes()
        with self.assertRaisesRegex(WorkflowError, 'invalid accepted evidence'):
            engine.apply_amendment(self.decision(engine))
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(list(self.run_dir.glob('run-amendment-*.json')))

    def test_protected_and_unknown_sets_are_rejected_atomically(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        before = engine.run_path.read_bytes()
        for ids in (['API-VAL-001', 'API-VAL-002'], ['API-VAL-002', 'API-VAL-999']):
            with self.subTest(ids=ids), self.assertRaises(WorkflowError):
                engine.apply_amendment(self.decision(engine, ids=ids))
        with self.assertRaises(WorkflowError):
            engine.apply_amendment(self.decision(engine) | {'target': 'ci'})
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(list(self.run_dir.glob('run-amendment-*.json')))

    def test_unfinished_work_and_untargeted_blockers_are_never_cleared(self):
        batch = PolicyBatch(advisory=False)
        def incomplete(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment['stage'] == 'implement':
                    output = Path(assignment['output_artifact'])
                    result = json.loads(output.read_text())
                    result.update(status='blocked', blockers=[{'id': 'BLOCK-WORK', 'kind': 'code',
                        'summary': 'Implementation work unfinished.', 'evidence_path': result['validations'][0]['log_path'],
                        'required_action': 'Finish the assigned source work.'}])
                    output.write_text(json.dumps(result))
            return code, manifest
        engine, _, _ = self.start(incomplete)
        before = engine.run_path.read_bytes()
        with self.assertRaisesRegex(WorkflowError, 'unfinished'):
            engine.apply_amendment(self.decision(engine))
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse([a for a in batch.assignments if a['stage'] == 'review-1'])

    def test_scoped_exception_preserves_a_separate_settled_blocker(self):
        engine, graph, config = self.start(PolicyBatch(advisory=False))
        run = engine.load_run()
        other = {key: value for key, value in run['blockers'][0].items() if key != 'gate'}
        other.update(id='BLOCK-OTHER', kind='environment', summary='Separate external obligation.')
        run['blockers'].append(other)
        engine._save_run(run)
        engine.apply_amendment(self.decision(engine))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual([other], engine.load_run()['blockers'])
        self.assertEqual('blocked', engine.load_run()['status'])

    def test_changed_semantic_basis_expires_but_preserves_the_decision(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        engine.apply_amendment(self.decision(engine))
        basis = engine._validation_basis('api')
        before = engine.run_path.read_bytes()
        for key in ('plan_sha256', 'requirements_sha256', 'contract_sha256', 'review_sha256'):
            with self.subTest(key=key), mock.patch.object(engine, '_validation_basis', return_value=basis | {key: 'f' * 64}):
                self.assertEqual({}, engine._exclusions('api'))
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertIn('API-VAL-002', engine._exclusions('api'))

    def test_cli_sqlite_amendment_is_idempotent_without_opening_a_cursor_again(self):
        import orchestrator
        batch = PolicyBatch(advisory=False)
        engine, _, _ = self.start(batch)
        path = self.root / 'decision.json'
        path.write_text(json.dumps(self.decision(engine)))
        args = orchestrator.build_parser().parse_args(['amend', str(self.run_dir), '--input', str(path)])
        with mock.patch('orchestrator.WorkflowEngine', return_value=engine):
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            self.assertEqual('complete', result['status'])
            before = {p: p.read_bytes() for p in self.run_dir.rglob('*') if p.is_file()}
            with mock.patch('orchestrator._open_graph', side_effect=AssertionError('must remain read-only')), mock.patch('orchestrator._execution_lock', side_effect=AssertionError('no lock creation')):
                result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            self.assertEqual('already-applied', result['amendment']['status'])
            self.assertEqual(before, {p: p.read_bytes() for p in self.run_dir.rglob('*') if p.is_file()})
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_cli_refuses_an_interrupted_sqlite_cursor_before_applying(self):
        import orchestrator
        engine = self.initialize(PolicyBatch(advisory=False))
        append = engine._append_event
        def crash(event, **kwargs):
            append(event, **kwargs)
            if event == 'artifact-accepted' and kwargs.get('action_id', '').startswith('implement:'):
                raise KeyboardInterrupt('accepted result with unsettled graph cursor')
        with mock.patch('orchestrator.WorkflowEngine', return_value=engine):
            with orchestrator._open_graph(self.run_dir, worker_runtime='auto', report_root=None) as (_, graph, config):
                with mock.patch.object(engine, '_append_event', side_effect=crash), self.assertRaises(KeyboardInterrupt):
                    graph.invoke({'run_dir': str(self.run_dir)}, config)
                self.assertTrue(graph.get_state(config).next)
            path = self.root / 'decision.json'
            path.write_text(json.dumps(self.decision(engine)))
            args = orchestrator.build_parser().parse_args(['amend', str(self.run_dir), '--input', str(path)])
            before = engine.run_path.read_bytes()
            with self.assertRaisesRegex(WorkflowError, 'settled graph cursor'):
                orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            self.assertEqual(before, engine.run_path.read_bytes())
            self.assertFalse(list(self.run_dir.glob('run-amendment-*.json')))

    def test_pipeline_revision_refreshes_required_integration_without_an_extra_review_round(self):
        batch = ChainBatch(advisory=False)
        engine, graph, config = self.start_chain(batch)
        batch.delivery_code_failures = 1
        engine.apply_amendment(self.decision(engine))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        old = engine._current_integration()
        before = old[0].read_bytes()
        fixtures.WorkflowEngineTests.authorize_related(engine, 'ci')
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'integrate' for a in batch.assignments))
        self.assertEqual(3, sum(a['stage'] == 'review-1' for a in batch.assignments))
        self.assertFalse(any(a['stage'] == 'review-2' for a in batch.assignments))
        self.assertNotEqual(old[0], engine._current_integration()[0])
        self.assertEqual(before, old[0].read_bytes())
        self.assertEqual('historical review with accepted bounded revisions', engine._review_basis('api'))

    def test_partial_packet_failure_is_current_not_historical(self):
        batch = PolicyBatch(advisory=False)
        def packets(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment['stage'] == 'plan':
                    output = Path(assignment['output_artifact'])
                    value = json.loads(output.read_text())
                    value['tasks'][0]['validation_ids'].append('API-VAL-002')
                    check = copy.deepcopy(value['validations'][0])
                    check.update(id='API-VAL-003', command='python future-acceptance.py')
                    value['validations'].append(check)
                    task = copy.deepcopy(value['tasks'][0])
                    task.update(id='API-TASK-002', depends_on=['API-TASK-001'], validation_ids=['API-VAL-003'])
                    value['tasks'].append(task)
                    packet = copy.deepcopy(value['work_packets'][0])
                    packet.update(id='API-PACKET-002', task_ids=['API-TASK-002'], depends_on=['API-PACKET-001'])
                    value['work_packets'].append(packet)
                    output.write_text(json.dumps(value))
            return code, manifest
        engine, _, _ = self.start(packets)
        summary = engine.validation_summary('api')
        self.assertEqual('fail', summary['checks'][1]['result'])
        self.assertEqual('not-run', summary['checks'][2]['result'])
        self.assertEqual([], summary['historical_failures'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        actions = engine.status_details()['eligible_actions']
        fixes = [a for a in actions if a.get('decision') == 'fix-related']
        self.assertEqual(['API-VAL-002'], fixes[0]['check_ids'])

    def test_worker_log_outside_assigned_directory_is_rejected_before_reading(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        source = Path(engine.validation_summary('api')['source_artifact']['path'])
        data = json.loads(source.read_text())
        assignment_path = Path(data['assignment_path'])
        assignment = json.loads(assignment_path.read_text())
        outside = self.root / 'unrelated-private-fixture.txt'
        outside.write_text('private fixture content')
        data['validations'][1]['log_path'] = str(outside)
        before = source.read_bytes()
        read_bytes = Path.read_bytes
        accessed = []
        def read(path):
            accessed.append(path)
            return read_bytes(path)
        with mock.patch.object(Path, 'read_bytes', read), self.assertRaisesRegex(fixtures.artifact_guard.ValidationError, 'assigned run log directory'):
            fixtures.workflow_tools.normalize_worker_artifact(assignment_path, assignment, source, data)
        self.assertNotIn(outside, accessed)
        self.assertEqual(before, source.read_bytes())

    def test_reviewed_evidence_changed_inside_transaction_is_not_snapshotted(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        diagnostic = self.run_dir / 'logs/diagnostic.md'
        diagnostic.write_text('Reviewed diagnosis.')
        request = self.decision(engine) | {'evidence': [{'path': str(diagnostic), 'sha256': hashlib.sha256(diagnostic.read_bytes()).hexdigest()}]}
        context = engine.amendment_context
        def changed(repo):
            value = context(repo)
            diagnostic.write_text('Different evidence, not reviewed.')
            return value
        before = engine.run_path.read_bytes()
        with mock.patch.object(engine, 'amendment_context', side_effect=changed), self.assertRaisesRegex(WorkflowError, 'evidence changed'):
            engine.apply_amendment(request)
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse((self.run_dir / 'amendment-evidence').exists())
        self.assertFalse(list(self.run_dir.glob('run-amendment-*.json')))

    def test_amendment_size_limit_precedes_snapshot_and_intent_persistence(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        request = self.decision(engine)
        before = engine.run_path.read_bytes()
        with mock.patch.dict(fixtures.artifact_guard.MAX_BYTES, {'run-amendment': 1500}), self.assertRaisesRegex(WorkflowError, 'size limit'):
            engine.apply_amendment(request)
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse((self.run_dir / 'amendment-evidence').exists())
        self.assertFalse(list(self.run_dir.glob('run-amendment-*.json')))

    def test_remediation_targets_and_restore_references_are_structurally_bound(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        fixtures.WorkflowEngineTests.authorize_related(engine, 'local')
        with mock.patch.object(engine, '_run_with_replacements', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            engine._run_pending_check_work()
        path = next(p for p in (self.run_dir / 'assignments').glob('*.json') if json.loads(p.read_text()).get('stage') == 'validation-fix')
        assignment = json.loads(path.read_text())
        with self.assertRaisesRegex(fixtures.artifact_guard.ValidationError, 'authorized repair targets'):
            fixtures.artifact_guard.validate_assignment(assignment | {'failed_validation_ids': ['API-VAL-001']})
        with self.assertRaisesRegex(fixtures.artifact_guard.ValidationError, 'repository/stage amendment'):
            fixtures.artifact_guard.validate_assignment(assignment | {'validation_refresh': assignment['remediation']})

    def test_unknown_policy_is_refused_before_cli_lock_or_checkpoint_creation(self):
        import orchestrator
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        request = self.decision(engine)
        run = engine.load_run()
        run['validation_policy_version'] = 999
        engine.run_path.write_text(json.dumps(run))
        path = self.root / 'decision.json'
        path.write_text(json.dumps(request))
        args = orchestrator.build_parser().parse_args(['amend', str(self.run_dir), '--input', str(path)])
        before = {p: p.read_bytes() for p in self.run_dir.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(fixtures.artifact_guard.ValidationError, 'unsupported policy version'):
            orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
        self.assertEqual(before, {p: p.read_bytes() for p in self.run_dir.rglob('*') if p.is_file()})

    def test_supplemental_migration_capability_cannot_be_excluded(self):
        batch = PolicyBatch(advisory=False)
        batch.risk_flags = ['database-migration']
        def migration(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment['stage'] == 'plan':
                    output = Path(assignment['output_artifact'])
                    value = json.loads(output.read_text())
                    value['validations'][1]['migration_capable'] = True
                    output.write_text(json.dumps(value))
            return code, manifest
        engine = self.initialize(migration, profile='full', risks=['database-migration'])
        graph = build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'protected-migration'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume={'decision': 'approve', 'review_sha256': review['review_sha256'],
            'text': 'Approve the plan; database execution still needs isolated target evidence.'}), config)
        before = engine.run_path.read_bytes()
        with self.assertRaisesRegex(WorkflowError, 'protected'):
            engine.apply_amendment(self.decision(engine))
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(any(a['stage'] == 'implement' for a in batch.assignments))

    def test_all_advisory_acceptance_is_rejected_before_implementation(self):
        batch = PolicyBatch()
        def advisory(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment['stage'] == 'plan':
                    output = Path(assignment['output_artifact'])
                    value = json.loads(output.read_text())
                    value['validations'][0].update(purpose='supplemental', gate='advisory')
                    output.write_text(json.dumps(value))
            return code, manifest
        engine, _, _ = self.start(advisory)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertFalse(any(a['stage'] == 'implement' for a in batch.assignments))

    def test_remediation_acceptance_crash_does_not_repeat_the_source_fixer(self):
        batch = PolicyBatch(advisory=False)
        engine, graph, config = self.start(batch)
        fixtures.WorkflowEngineTests.authorize_related(engine, 'local')
        append = engine._append_event
        def crash(event, **kwargs):
            append(event, **kwargs)
            if event == 'artifact-accepted' and kwargs.get('action_id', '').startswith('validation-fix:'):
                raise KeyboardInterrupt('accepted fix before graph checkpoint')
        with mock.patch.object(engine, '_append_event', side_effect=crash), self.assertRaises(KeyboardInterrupt):
            graph.invoke({'run_dir': str(self.run_dir)}, config)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))

    def test_repeated_related_failure_does_not_replenish_the_fix_allowance(self):
        batch = PolicyBatch(advisory=False)
        def failing_fix(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment['stage'] == 'validation-fix':
                    output = Path(assignment['output_artifact'])
                    value = json.loads(output.read_text())
                    value['validations'][1].update(result='fail', exit_code=1, summary='The targeted fixture still fails.')
                    Path(value['validations'][1]['log_path']).write_text('Still failing.\n')
                    output.write_text(json.dumps(value))
            return code, manifest
        engine, graph, config = self.start(failing_fix)
        fixtures.WorkflowEngineTests.authorize_related(engine, 'local')
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        with self.assertRaisesRegex(WorkflowError, 'allowance exhausted'):
            fixtures.WorkflowEngineTests.authorize_related(engine, 'local')
        self.assertFalse([a for a in engine.status_details()['eligible_actions'] if a.get('decision') == 'fix-related'])
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))

    def test_pr_body_conflict_can_be_reobserved_without_silent_publication(self):
        batch = fixtures.FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch, state='failure')
        graph = build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'body-conflict'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        original = forge.pr['body']
        forge.pr['body'] = original.replace('delivery remains blocked.', 'Human-maintained explanation.')
        forge.check_state = 'success'
        self.assertTrue(engine.resume_delivery_checks())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('delivery-state', engine.load_run()['blockers'][0]['gate']['type'])
        self.assertEqual(0, forge.ready_count)
        forge.pr['body'] = original
        self.assertTrue(engine.resume_delivery_checks())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, forge.ready_count)
        self.assertEqual(1, forge.create_count)

    def test_late_amendment_retargets_delivery_and_refreshes_report_after_other_blocker(self):
        import orchestrator
        batch = PolicyBatch()
        engine = self.initialize(batch, report_requested=True)
        graph = build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'late-exclusion'}, 'recursion_limit': 150}
        def blocked_audit():
            engine._block(summary='External cleanup fixture pending.', evidence_path=self.run_dir / 'logs/cleanup.log',
                          required_action='Restore the fixture external condition.', kind='infrastructure')
            return 'blocked'
        with mock.patch.object(engine, 'phase_complete', side_effect=blocked_audit):
            graph.invoke({'run_dir': str(self.run_dir)}, config)
        old = engine._current_report()
        raw, html = old[0].read_bytes(), Path(old[1]['html_path']).read_bytes()
        engine.apply_amendment(self.decision(engine))
        self.assertEqual(('blocked', 'deliver'), (engine.load_run()['status'], engine.load_run()['phase']))
        self.assertIsNone(engine._latest_delivery('api'))
        self.assertIsNone(engine._current_report())
        self.assertEqual('historical review with authorized policy amendments', engine._review_basis('api'))
        self.assertTrue(engine.resume_external_blockers())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        status = orchestrator._result(engine)
        self.assertEqual('complete', status['status'])
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        self.assertEqual(2, sum(a['stage'] == 'deliver' for a in batch.assignments))
        self.assertEqual(raw, old[0].read_bytes())
        self.assertEqual(html, Path(old[1]['html_path']).read_bytes())
        self.assertEqual([old[1]['html_path']], status['historical_report_paths'])
        rendered = Path(status['report_paths'][0]).read_text()
        self.assertIn('Active exclusions', rendered)
        self.assertIn('This immutable report is not live run status', rendered)
        self.assertNotIn('>working</span>', rendered)

    def test_fallback_ownership_requires_matching_nonce_and_observation(self):
        import artifact_guard
        import delivery_tools
        engine, _, _ = self.start_chain(ChainBatch())
        path, artifact, assignment = engine._artifacts(repo_id='api', kind='delivery')[-1]
        artifact_guard.CURRENT_ARTIFACT_PATH = path
        missing = copy.deepcopy(artifact)
        missing.pop('creation_intent')
        with self.assertRaises(artifact_guard.ValidationError):
            artifact_guard.validate_delivery(missing)
        spoof = Path(assignment['log_dir']) / 'spoofed-observation.json'
        observed = json.loads(Path(artifact['ownership_observation']['path']).read_text())
        observed['body'] = 'A human-owned PR without the private creation marker.'
        spoof.write_text(json.dumps(observed))
        with self.assertRaisesRegex(artifact_guard.ValidationError, 'nonce-bound'):
            artifact_guard.validate_delivery(artifact | {'ownership_observation': delivery_tools.reference(spoof)})
        artifact_guard.validate_delivery(artifact)

    def test_assignment_rejects_omitted_and_mispaired_effective_checks(self):
        import artifact_guard
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        original = json.loads(engine._validation_assignment('api', 'coverage-audit').read_text())
        for change in ({'validation_commands': list(reversed(original['validation_commands']))},
                       {'validation_ids': original['validation_ids'][:1], 'validation_commands': original['validation_commands'][:1]}):
            with self.assertRaisesRegex(artifact_guard.ValidationError, 'canonical effective'):
                artifact_guard.validate_assignment(original | change)
        original.pop('delivery_policy_version')
        with self.assertRaisesRegex(artifact_guard.ValidationError, 'pinned together'):
            artifact_guard.validate_assignment(original)

    def test_amendment_shape_and_run_policy_pair_are_enforced(self):
        import artifact_guard
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        applied = engine.apply_amendment(self.decision(engine))
        value = json.loads(Path(applied['path']).read_text())
        for key in ('basis', 'repository_state'):
            malformed = value | {key: {}}
            with self.assertRaises(artifact_guard.ValidationError):
                artifact_guard.validate_run_amendment(malformed)
        run = engine.load_run()
        run.pop('delivery_policy_version')
        with self.assertRaisesRegex(artifact_guard.ValidationError, 'pinned together'):
            artifact_guard.validate_run(run)

    def test_status_does_not_offer_amendments_after_external_drift(self):
        engine, _, _ = self.start(PolicyBatch(advisory=False))
        (self.worktree / 'feature.txt').write_text('External unvalidated drift.\n')
        self.assertEqual([], engine.status_details()['eligible_actions'])

    def test_revalidated_external_content_cannot_inherit_ci_failure_or_review(self):
        batch = fixtures.FakeSuccessfulBatch()
        engine, _ = self.github_engine(batch, state='failure')
        graph = build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'stale-ci-source'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        (self.worktree / 'feature.txt').write_text('Externally changed content, not the delivered tree.\n')
        engine._run_with_replacements([engine._validation_assignment('api', 'external-observation')])
        self.assertIsNone(engine._review_basis('api'))
        with self.assertRaisesRegex(WorkflowError, 'unchanged delivered content'):
            fixtures.WorkflowEngineTests.authorize_related(engine, 'ci')
        self.assertEqual([], engine.status_details()['eligible_actions'])

    def test_protected_advisory_plan_is_rejected_before_source_work(self):
        batch = PolicyBatch(advisory=True, protected=True)
        engine, _, _ = self.start(batch)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertFalse([a for a in batch.assignments if a['stage'] == 'implement'])

    def test_red_required_ci_keeps_a_visible_draft_without_an_unrelated_fixer(self):
        import orchestrator
        batch = fixtures.FakeSuccessfulBatch()
        engine, forge = self.github_engine(batch, state='failure')
        graph = build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'draft-delivery'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        status = orchestrator._result(engine)
        self.assertEqual('blocked', status['status'])
        self.assertEqual(['https://github.com/example/task/pull/1'], status['pr_urls'])
        self.assertTrue(forge.pr['isDraft'])
        self.assertFalse([a for a in batch.assignments if a['stage'] == 'pipeline-fix'])
        before = {p: p.read_bytes() for p in (self.run_dir / 'repos/api').glob('delivery-*.json')}
        forge.check_state = 'success'
        self.assertTrue(engine.resume_delivery_checks())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertFalse(forge.pr['isDraft'])
        self.assertEqual(1, forge.create_count)
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))
        for path, raw in before.items():
            self.assertEqual(raw, path.read_bytes())

    def test_cli_amendment_and_status_are_scoped_and_read_only_on_legacy_runs(self):
        import orchestrator
        batch = PolicyBatch(advisory=False)
        engine, _, _ = self.start(batch)
        status = orchestrator._result(engine)
        self.assertIn('api', status['amendment_contexts'])
        self.assertTrue(any(a.get('decision') == 'exclude' for a in status['eligible_actions']))
        path = self.root / 'decision.json'
        path.write_text(json.dumps(self.decision(engine)))
        args = orchestrator.build_parser().parse_args(['amend', str(self.run_dir), '--input', str(path)])
        self.assertEqual('amend', args.command)
        run = engine.load_run()
        run.pop('validation_policy_version')
        run.pop('delivery_policy_version')
        engine._save_run(run)
        before = {p: p.read_bytes() for p in self.run_dir.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(WorkflowError, 'legacy'):
            orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
        self.assertEqual(before, {p: p.read_bytes() for p in self.run_dir.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
