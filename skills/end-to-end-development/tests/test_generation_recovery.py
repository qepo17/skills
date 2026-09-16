from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver
import test_workflow_engine as fixtures


class GenerationRecoveryTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    initialize = fixtures.WorkflowEngineTests.initialize

    def write_spec(self, **kwargs):
        fixtures.WorkflowEngineTests.write_spec(self, **kwargs)
        spec = json.loads(self.spec.read_text())
        spec['requirements'][0]['repository_ids'] = ['api', 'core', 'ui']
        for name in ('core', 'ui'):
            root, tree = self.root / name, self.root / (name + '-worktree')
            fixtures.subprocess.run(['git', 'clone', '-q', str(self.repo), str(root)], check=True)
            for key, value in [('user.name', 'Tests'), ('user.email', 'tests@example.com')]:
                fixtures.subprocess.run(['git', 'config', key, value], cwd=root, check=True)
            fixtures.subprocess.run(['git', 'worktree', 'add', '-qb', 'feat/' + name, str(tree)], cwd=root, check=True)
            spec['repositories'].append(dict(repo_id=name, root=str(root), worktree=str(tree),
                                             base_branch='master', branch='feat/' + name))
        (self.repo / '.git/info/exclude').write_text('dist/\n')
        self.spec.write_text(json.dumps(spec))

    def prepare(self):
        batch = fixtures.FakeSuccessfulBatch(risk_flags=['security'])
        blocked = False
        self.batches = []

        def runner(paths, **kwargs):
            nonlocal blocked
            self.batches.append([json.loads(p.read_text())['repo_id'] for p in paths])
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                a = json.loads(path.read_text())
                output = Path(a['output_artifact'])
                result = json.loads(output.read_text())
                if a['stage'] == 'contract':
                    result['requirement_map'] = {'REQ-001': ['api', 'core', 'ui']}
                    result['dependencies'] = [dict(from_repo_id=p, to_repo_id=c,
                        reason='Producer-to-consumer edge: generate from approved bundle.', evidence='Approved API-first design.')
                        for p, c in [('api', 'core'), ('api', 'ui'), ('core', 'ui')]]
                elif a['stage'] == 'plan':
                    task, packet = copy.deepcopy(result['tasks'][0]), copy.deepcopy(result['work_packets'][0])
                    task.update(id='API-TASK-002', depends_on=['API-TASK-001'])
                    packet.update(id='API-PACKET-002', task_ids=['API-TASK-002'], depends_on=['API-PACKET-001'])
                    result['tasks'].append(task)
                    result['work_packets'].append(packet)
                elif a['stage'] == 'implement' and a['repo_id'] == 'ui' and a['packet_id'] == 'API-PACKET-002' and not blocked:
                    blocked = True
                    if getattr(self, 'concealed_change', False):
                        (Path(a['cwd']) / 'hidden-change.txt').write_text('not reported in changed_files')
                    evidence = self.run_dir / 'scope.md'
                    evidence.write_text('Generator reads API and writes API dist/openapi.yaml outside UI scope.\n')
                    result.update(status='blocked', changed_files=[], blockers=[dict(id='BLOCK-SCOPE', kind='permission',
                        summary='Generation writes API dist/openapi.yaml outside assignment scope.',
                        evidence_path=str(evidence), required_action='Authorize exact API reads and generated output writes.')])
                output.write_text(json.dumps(result) + '\n')
            return code, manifest

        engine = self.initialize(runner, profile='full', risks=['security'])
        graph = fixtures.build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'generation-recovery'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume=dict(decision='approve', review_sha256=review['review_sha256'],
            text='approved all plans')), config)
        run = engine.load_run()
        self.assertEqual(('blocked', 'implement'), (run['status'], run['phase']))
        self.assertEqual(['ui', 'ui'], [a['repo_id'] for a in batch.assignments if a['stage'] == 'implement'])
        auth = self.run_dir / 'authorization.md'
        auth.write_text('Repair producer-first ordering; read API source; write only API dist/openapi.yaml. User: authorized\n')
        ref = lambda p: dict(path=str(p), sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest())
        request = dict(run_id=run['run_id'], expected_run_sha256=ref(engine.run_path)['sha256'],
            blocker_id=run['blockers'][0]['id'], blocker_evidence=ref(run['blockers'][0]['evidence_path']),
            authorization=ref(auth), contract=ref(run['contract_path']), review=ref(review['review_path']),
            producer_repo_id='api', read_consumers=['core', 'ui'], write_consumers=['ui'],
            generated_path='dist/openapi.yaml', dependency_direction='producer-to-consumer',
            repository_states={name: fixtures.workflow_tools.repository_state(Path(repo['worktree']))
                               for name, repo in run['repositories'].items()})
        return engine, graph, config, batch, request

    def recover(self, engine, request, **kwargs):
        import generation_recovery
        return generation_recovery.recover(engine, request,
            request_sha256=generation_recovery.digest(request), text='authorized', **kwargs)

    def test_recovery_uses_real_scheduler_preserves_prior_packet_and_scopes_retry(self):
        engine, graph, config, batch, request = self.prepare()
        prior = engine.load_run()
        preserved = {p: p.read_bytes() for p in self.run_dir.rglob('*.json') if p.name not in {'run.json', 'agents.json'} and 'supervisor' not in p.parts}
        self.assertEqual('applied', self.recover(engine, request))
        self.assertEqual('already-applied', self.recover(engine, request))
        self.assertEqual({'api': set(), 'core': {'api'}, 'ui': {'api', 'core'}}, engine._contract_dependencies())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        run = engine.load_run()
        self.assertEqual('complete', run['status'])
        self.assertEqual(prior['retry_limits'], run['retry_limits'])
        self.assertEqual(prior['plan_review'], run['plan_review'])
        for p, raw in preserved.items():
            self.assertEqual(raw, p.read_bytes(), str(p))
        writers = [a for a in batch.assignments if a['stage'] == 'implement']
        self.assertEqual(['ui', 'ui', 'api', 'api', 'core', 'core', 'ui'], [a['repo_id'] for a in writers])
        retry = writers[-1]
        self.assertEqual(2, retry['attempt'])
        self.assertEqual({'api': 'read', 'ui': 'write'}, {r['repo_id']: r['access'] for r in retry['repositories']})
        self.assertEqual([str(self.worktree / 'dist/openapi.yaml')], retry['generated_file_writes'])
        self.assertNotEqual(writers[1]['output_artifact'], retry['output_artifact'])
        self.assertTrue(any('implementation-api-packet-002' in r['path'] and '/api/' in r['path'] for r in retry['input_artifacts']))
        self.assertTrue(all('generated_file_writes' not in a for a in writers if a['repo_id'] == 'core'))

    def assert_rejected(self, change):
        engine, _, _, _, request = self.prepare()
        change(engine, request)
        before = engine.run_path.read_bytes()
        with self.assertRaises((fixtures.WorkflowError, fixtures.artifact_guard.ValidationError)):
            self.recover(engine, request)
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse((self.run_dir / 'generation-recovery.json').exists())

    def test_source_drift(self):
        self.assert_rejected(lambda e, r: (self.worktree / 'README.md').write_text('drift'))

    def test_stale_reviewed_evidence(self):
        self.assert_rejected(lambda e, r: Path(r['blocker_evidence']['path']).write_text('drift'))

    def test_wrong_output_path(self):
        self.assert_rejected(lambda e, r: r.update(generated_path='openapi.yaml'))

    def test_symlink_output(self):
        def change(e, r):
            (self.worktree / 'dist').symlink_to(self.root, target_is_directory=True)
        self.assert_rejected(change)

    def test_wrong_contract_direction(self):
        self.assert_rejected(lambda e, r: r.update(dependency_direction='consumer-to-producer'))

    def test_active_lease(self):
        def change(e, r):
            run = e.load_run()
            run['repositories']['ui']['active_writer'] = 'active'
            e._save_run(run)
        self.assert_rejected(change)

    def test_orphaned_intent_is_reused_without_overwriting(self):
        engine, _, _, _, request = self.prepare()
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.recover(engine, request)
        path = self.run_dir / 'generation-recovery.json'
        raw = path.read_bytes()
        self.assertEqual('applied', self.recover(engine, request))
        self.assertEqual(raw, path.read_bytes())

    def test_unrecovered_runs_keep_legacy_direction(self):
        engine, _, _, _, _ = self.prepare()
        self.assertEqual({'api': {'core', 'ui'}, 'core': {'ui'}, 'ui': set()}, engine._contract_dependencies())

    def test_cli_no_drive_and_idempotent_reapply(self):
        import generation_recovery
        engine, _, _, batch, request = self.prepare()
        path = self.root / 'recovery-request.json'
        path.write_text(json.dumps(request))
        command = [fixtures.sys.executable, str(fixtures.SCRIPTS_DIR / 'orchestrator.py'),
                   'recover-generation-scope', str(self.run_dir), '--input', str(path),
                   '--request-sha256', generation_recovery.digest(request), '--text', 'authorized', '--no-drive']
        count = len(batch.assignments)
        for expected in ('applied', 'already-applied'):
            process = fixtures.subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, process.returncode, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(expected, result['recovery'])
            self.assertEqual('working', result['status'])
        self.assertEqual(count, len(batch.assignments))
        self.assertFalse(engine.load_run()['next_actions'])

    def test_recovered_validation_uses_separate_settled_waves(self):
        engine, _, _, _, request = self.prepare()
        self.recover(engine, request)
        # Construct only the next wave; a blocked packet is not complete validation.
        self.assertEqual('again', engine._run_validation_wave(['ui', 'core', 'api'], 'test'))
        self.assertEqual(['api'], self.batches[-1])
        self.assertFalse(list((self.run_dir / 'assignments').glob('validate-core-test*.json')))
        self.assertEqual('again', engine._run_validation_wave(['ui', 'core', 'api'], 'test'))
        self.assertEqual(['core'], self.batches[-1])
        self.assertEqual('pass', engine._run_validation_wave(['ui', 'core', 'api'], 'test'))
        self.assertEqual(['ui'], self.batches[-1])

    def test_historical_assignment_tampering_is_rejected(self):
        def change(engine, request):
            path, _, _ = engine._artifacts(repo_id='ui', stage='implement', kind='result')[-1]
            assignment_path = Path(json.loads(path.read_text())['assignment_path'])
            value = json.loads(assignment_path.read_text())
            value['instructions'].append('unauthorized modified instruction')
            assignment_path.write_text(json.dumps(value))
        self.assert_rejected(change)

    def test_historical_assignment_tampering_before_replacement_is_rejected(self):
        engine, _, _, _, request = self.prepare()
        self.recover(engine, request)
        _, result, assignment = engine._artifacts(repo_id='ui', stage='implement', kind='result')[-1]
        path = Path(result['assignment_path'])
        value = json.loads(path.read_text())
        value['instructions'].append('changed after recovery')
        path.write_text(json.dumps(value))
        with self.assertRaises(fixtures.WorkflowError):
            engine._replacement(value)

    def test_pending_remediations_construct_consumers_after_upstream_settlement(self):
        engine, _, _, _, request = self.prepare()
        self.recover(engine, request)
        run = engine.load_run()
        pending = {}
        for name in ('api', 'core'):
            decision = self.root / (name + '-decision.json')
            decision.write_text(json.dumps(dict(basis='test-basis', repository_state=request['repository_states'][name],
                                               target='local', check_ids=['API-VAL-001'])))
            pending[name] = dict(path=str(decision), sha256=hashlib.sha256(decision.read_bytes()).hexdigest())
        run['pending_check_remediations'] = pending
        observations = []
        def build(**kwargs):
            observations.append((kwargs['repo_id'], fixtures.workflow_tools.repository_state(self.worktree)))
            return self.root / 'not-executed.json'
        with mock.patch.object(engine, 'load_run', return_value=run), \
             mock.patch.object(engine, '_validation_basis', return_value='test-basis'), \
             mock.patch.object(engine, '_canonical_inputs', return_value=[]), \
             mock.patch.object(engine, '_plan_validation_ids', return_value=['API-VAL-001']), \
             mock.patch.object(engine, '_plan_commands', return_value=['python -m unittest']), \
             mock.patch.object(engine, 'build_assignment', side_effect=build), \
             mock.patch.object(engine, '_run_with_replacements', return_value=[]):
            engine._run_pending_check_work()
            self.assertEqual(['api'], [name for name, _ in observations])
            # Simulate acceptance of the upstream repair before the next graph wave.
            del pending['api']
            (self.worktree / 'README.md').write_text('upstream repaired')
            engine._run_pending_check_work()
        self.assertEqual(['api', 'core'], [name for name, _ in observations])
        self.assertNotEqual(observations[0][1], observations[1][1])

    def test_concealed_source_change_is_not_no_change(self):
        self.concealed_change = True
        self.assert_rejected(lambda *_: None)

    def test_interrupted_snapshot_publication_is_retryable(self):
        import generation_recovery
        engine, _, _, _, request = self.prepare()
        with mock.patch.object(generation_recovery.os, 'replace', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.recover(engine, request)
        self.assertFalse((self.run_dir / 'generation-recovery-run-before.json').exists())
        self.assertEqual('applied', self.recover(engine, request))

    def test_retained_validation_worker_never_creates_downstream_assignment(self):
        engine, _, _, _, request = self.prepare()
        self.recover(engine, request)
        launched = []
        def retained(paths, **kwargs):
            launched.extend(paths)
            a = json.loads(paths[0].read_text())
            return 1, {'workers': [dict(action_id=a['action_id'], agent_name='retained',
                assignment_path=str(paths[0]), output_artifact=a['output_artifact'],
                started_at='2026-08-22T10:00:00Z', ended_at='2026-08-22T10:01:00Z',
                backend='test', handle_id='retained-handle', cleanup_status='retained',
                status='rejected', reason='upstream timeout') ]}
        engine.batch_runner = retained
        self.assertEqual('blocked', engine._run_validation_wave(['ui', 'core', 'api'], 'retained'))
        self.assertEqual(['api'], [json.loads(p.read_text())['repo_id'] for p in launched])
        self.assertFalse(list((self.run_dir / 'assignments').glob('validate-core-retained*.json')))

    def test_retry_budget_exhaustion_is_not_reset(self):
        def change(engine, request):
            run = engine.load_run()
            run['retry_limits']['worker_replacements_per_stage'] = 0
            engine._save_run(run)
            request['expected_run_sha256'] = hashlib.sha256(engine.run_path.read_bytes()).hexdigest()
        self.assert_rejected(change)

    def test_artifact_repair_strips_generated_write_exception(self):
        engine, _, _, _, request = self.prepare()
        self.recover(engine, request)
        path = engine.build_assignment(stage='implement', repo_id='ui', scope='repair-probe',
            task_ids=['API-TASK-002'], packet_id='API-PACKET-002', instructions=['Test scope.'],
            validation_ids=['API-VAL-001'], validation_commands=['python -m unittest'])
        assignment = json.loads(path.read_text())
        engine.batch_runner([path], run_dir=self.run_dir, worker_runtime='auto', allow_existing=False)
        output = Path(assignment['output_artifact'])
        value = json.loads(output.read_text())
        value.update(status='blocked', blockers=[dict(id='BLOCK-MISSING-KIND', summary='Permission denied.',
            evidence_path=request['blocker_evidence']['path'], required_action='Inspect scope.')])
        output.write_text(json.dumps(value))
        repair_path = engine._artifact_repair_assignment(assignment)
        repair = json.loads(repair_path.read_text())
        self.assertNotIn('generated_file_writes', repair)
        repair['generated_file_writes'] = assignment['generated_file_writes']
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            fixtures.artifact_guard.validate_assignment(repair)

    def test_assignment_rejects_widened_generated_write_and_upstream_source_drift(self):
        engine, _, _, _, request = self.prepare()
        self.recover(engine, request)
        path = engine.build_assignment(stage='implement', repo_id='ui', scope='probe',
            task_ids=['API-TASK-002'], packet_id='API-PACKET-002', instructions=['Test scope.'],
            validation_ids=['API-VAL-001'], validation_commands=['python -m unittest'])
        assignment = json.loads(path.read_text())
        bad = copy.deepcopy(assignment)
        bad['generated_file_writes'] = [str(self.worktree / 'README.md')]
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            fixtures.artifact_guard.validate_assignment(bad)
        (self.worktree / 'README.md').write_text('out-of-scope mutation')
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            fixtures.workflow_tools.normalize_worker_artifact(path, assignment, Path(assignment['output_artifact']), {})
