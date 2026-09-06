from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver

import test_workflow_engine as fixtures


class PacketBuildDependencyTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def prepare(self, *, late_build_failure=False, extra_failure=False, independent_provider=False,
                provider_without_build=False, extra_blocker=False, omit_check=False, extra_check=False, multi=False,
                chain_failure=False, mixed_compile_failure=False, chain_migration=False, late_test_failure=False,
                chain_command='go test -race ./internal/api/handlers/admin'):
        batch = fixtures.FakeSuccessfulBatch(migration_capable=chain_migration)

        def dependency_batch(paths, **kwargs):
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                output = Path(assignment['output_artifact'])
                artifact = json.loads(output.read_text())
                if assignment['stage'] == 'contract' and multi:
                    artifact['requirement_map'] = {'REQ-001': ['api', 'core']}
                    artifact['dependencies'] = []
                elif assignment['stage'] == 'plan':
                    artifact['validations'].append({
                        'id': 'API-VAL-002', 'command': 'make build', 'cwd': assignment['cwd'],
                        'scope': 'broad', 'migration_capable': False,
                    })
                    original = artifact['tasks'][0]
                    original['validation_ids'].append('API-VAL-002')
                    for number in (2, 3):
                        task = copy.deepcopy(original)
                        task.update(id=f'API-TASK-00{number}', depends_on=[f'API-TASK-00{number-1}'])
                        # The intermediate packet also requests the full build:
                        # it must receive focused checks until the provider exists.
                        artifact['tasks'].append(task)
                        packet = copy.deepcopy(artifact['work_packets'][0])
                        packet.update(id=f'API-PACKET-00{number}', task_ids=[task['id']],
                                      depends_on=[f'API-PACKET-00{number-1}'])
                        artifact['work_packets'].append(packet)
                    if independent_provider:
                        artifact['tasks'][-1]['depends_on'] = []
                        artifact['work_packets'][-1]['depends_on'] = []
                    if provider_without_build:
                        artifact['tasks'][-1]['validation_ids'] = ['API-VAL-001']
                    if chain_failure:
                        artifact['validations'][0]['command'] = chain_command
                        artifact['validations'].append(dict(artifact['validations'][0], id='API-VAL-003',
                                                             command='python -m unittest'))
                        for task in artifact['tasks']:
                            task['validation_ids'].append('API-VAL-003')
                        # The handler task already requires the full build, but
                        # not the premature admin-package test from task two.
                        artifact['tasks'][-1]['validation_ids'] = ['API-VAL-002', 'API-VAL-003']
                elif artifact['artifact_kind'] == 'result':
                    for index, record in enumerate(artifact['validations']):
                        log = Path(assignment['log_dir']) / f"{output.stem}-check-{index}.log"
                        # Unique immutable evidence, including the failed build.
                        log.write_text(Path(record['log_path']).read_text())
                        record['log_path'] = str(log)
                        if record['id'] == 'API-VAL-002' and (
                            assignment.get('packet_id') == 'API-PACKET-001' or late_build_failure
                        ):
                            record.update(result='fail', exit_code=2, summary='Generated interface needs later handlers.')
                            log.write_text('server.go:1: apiHandler does not implement api.StrictServerInterface '
                                           '(missing method CreateSurcharge)\nmake: build failed\n')
                    if late_test_failure and (assignment.get('packet_id') == 'API-PACKET-003'
                                              or assignment['stage'] == 'validate'):
                        check = next(v for v in artifact['validations'] if v['id'] == 'API-VAL-001')
                        check.update(result='fail', exit_code=1, summary='Handler tests still fail after provider.')
                        Path(check['log_path']).write_text('--- FAIL: HandlerTest\nFAIL\n')
                    if assignment.get('packet_id') == 'API-PACKET-001':
                        build = next(v for v in artifact['validations'] if v['id'] == 'API-VAL-002')
                        artifact.update(status='blocked', blockers=[{
                            'id': 'BLOCK-BUILD', 'kind': 'dependency',
                            'summary': 'API-VAL-002 build requires the API-TASK-003 handlers in a later packet.',
                            'evidence_path': build['log_path'],
                            'required_action': 'Preserve foundation and implement API-TASK-003 before the full build.',
                        }])
                        if extra_failure:
                            artifact['validations'][0].update(result='fail', exit_code=1, summary='Unrelated failure.')
                        if extra_blocker:
                            artifact['blockers'].append(dict(artifact['blockers'][0], id='BLOCK-OTHER',
                                                             kind='code', summary='Unrelated code issue.'))
                        if omit_check:
                            artifact['validations'] = [build]
                        if extra_check:
                            artifact['validations'].append(dict(artifact['validations'][0], id='API-VAL-003'))
                    elif chain_failure and assignment.get('packet_id') == 'API-PACKET-002':
                        check = next(v for v in artifact['validations'] if v['id'] == 'API-VAL-001')
                        check.update(result='fail', exit_code=1, summary='Same missing generated handler during test compilation.')
                        Path(check['log_path']).write_text(
                            '# example/internal/api/server\nserver.go:1: apiHandler does not implement '
                            'api.StrictServerInterface (missing method CreateSurcharge)\n'
                            'FAIL\texample/internal/api/handlers/admin [build failed]\n'
                            'ok  \texample/internal/service/allocation 1.01s\nFAIL\n'
                            + ('other.go:3: undefined: unrelated\n' if mixed_compile_failure else ''))
                        artifact.update(status='blocked', blockers=[{
                            'id': 'BLOCK-CHECK', 'kind': 'dependency',
                            'summary': 'API-VAL-001 test compilation also needs API-TASK-003 handlers.',
                            'evidence_path': check['log_path'],
                            'required_action': 'Preserve service progress and rerun checks after API-TASK-003.',
                        }])
                output.write_text(json.dumps(artifact) + '\n')
            return code, manifest

        def write_multi_spec(**kwargs):
            fixtures.WorkflowEngineTests.write_spec(self, **kwargs)
            if multi:
                spec = json.loads(self.spec.read_text())
                spec['requirements'][0]['repository_ids'] = ['api', 'core']
                root, worktree = self.root / 'core-repo', self.root / 'core-worktree'
                fixtures.subprocess.run(['git', 'clone', '-q', str(self.repo), str(root)], check=True)
                branch = 'feat/core-test'
                fixtures.subprocess.run(['git', 'worktree', 'add', '-qb', branch, str(worktree)], cwd=root, check=True)
                spec['repositories'].append({'repo_id': 'core', 'root': str(root), 'worktree': str(worktree),
                                             'branch': branch, 'base_branch': 'master'})
                self.spec.write_text(json.dumps(spec))
        with mock.patch.object(self, 'write_spec', side_effect=write_multi_spec):
            engine = self.initialize(dependency_batch, profile='full')
        if chain_migration:
            engine.record_database_target(repo_id='api', classification='isolated-test',
                                          description='Injected isolated fixture; fake worker executes no commands.')
        graph = fixtures.build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'packet-build'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume={
            'decision': 'approve', 'review_sha256': review['review_sha256'], 'text': 'approved all plans',
        }), config)
        run = engine.load_run()
        self.assertEqual(('blocked', 'implement'), (run['status'], run['phase']))
        self.assertFalse(engine.resume_external_blockers())
        arguments = {
            'repo_id': 'api', 'blocker_id': run['blockers'][0]['id'],
            'review_sha256': review['review_sha256'], 'validation_id': 'API-VAL-002',
            'until_task': 'API-TASK-003', 'text': 'just continue the work',
            'evidence_sha256': hashlib.sha256(Path(run['blockers'][0]['evidence_path']).read_bytes()).hexdigest(),
        }
        return engine, graph, config, batch, arguments

    def test_continues_later_packets_without_rewriting_failure_or_weakening_final_build(self):
        engine, graph, config, batch, arguments = self.prepare()
        before = engine.load_run()
        source = fixtures.workflow_tools.repository_state(self.worktree)
        original = next(a for a in batch.assignments if a['stage'] == 'implement')
        output = Path(original['output_artifact'])
        raw = output.read_bytes()
        self.assertTrue(engine.continue_packet_build(**arguments))
        self.assertFalse(engine.continue_packet_build(**arguments))
        self.assertEqual(source, fixtures.workflow_tools.repository_state(self.worktree))
        self.assertEqual(before['plan_review'], engine.load_run()['plan_review'])
        self.assertEqual(before['retry_limits'], engine.load_run()['retry_limits'])
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        run = engine.load_run()
        self.assertEqual('complete', run['status'])
        self.assertEqual(raw, output.read_bytes())
        self.assertEqual('blocked', json.loads(output.read_text())['status'])
        writers = [a for a in batch.assignments if a['stage'] == 'implement']
        self.assertEqual(['API-PACKET-001', 'API-PACKET-002', 'API-PACKET-003'], [a['packet_id'] for a in writers])
        self.assertEqual(['API-VAL-001'], writers[1]['validation_ids'])
        self.assertEqual(['API-VAL-001', 'API-VAL-002'], writers[2]['validation_ids'])
        self.assertIsNotNone(engine._current_validation('api', require_pass=True))
        self.assertEqual(1, sum(a['stage'] == 'review-1' for a in batch.assignments))
        intent = run['packet_build_dependencies']['api']
        self.assertTrue(any(ref == intent for ref in writers[1]['input_artifacts']))
        self.assertEqual('just continue the work', json.loads(Path(intent['path']).read_text())['authorization_text'])

    def test_failure_after_provider_stays_failed_and_blocks_delivery_after_bounded_fix(self):
        engine, graph, config, batch, arguments = self.prepare(late_build_failure=True)
        self.assertTrue(engine.continue_packet_build(**arguments))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))
        self.assertFalse(any(a['stage'] in {'review-1', 'deliver'} for a in batch.assignments))
        self.assertFalse(engine.continue_packet_build(**arguments))

    def assert_rejected(self, change, **prepare_kwargs):
        engine, _, _, _, arguments = self.prepare(**prepare_kwargs)
        change(engine, arguments)
        before = engine.run_path.read_bytes()
        with self.assertRaises((fixtures.WorkflowError, fixtures.artifact_guard.ValidationError, ValueError)):
            if not engine.continue_packet_build(**arguments):
                raise fixtures.WorkflowError('ineligible')
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_other_failed_checks_prevent_continuation(self):
        self.assert_rejected(lambda *_: None, extra_failure=True)

    def test_stale_review_is_rejected(self):
        self.assert_rejected(lambda _, a: a.update(review_sha256='0' * 64))

    def test_wrong_blocker_is_rejected(self):
        self.assert_rejected(lambda _, a: a.update(blocker_id='BLOCK-OTHER'))

    def test_unknown_provider_is_rejected(self):
        self.assert_rejected(lambda _, a: a.update(until_task='API-TASK-999'))

    def test_current_packet_cannot_be_its_own_provider(self):
        self.assert_rejected(lambda _, a: a.update(until_task='API-TASK-001'))

    def test_source_drift_is_rejected(self):
        self.assert_rejected(lambda *_: (self.worktree / 'feature.txt').write_text('drift\n'))

    def test_reviewed_evidence_drift_is_rejected(self):
        self.assert_rejected(lambda engine, _: Path(engine.load_run()['blockers'][0]['evidence_path']).write_text('drift\n'))

    def test_uncleaned_worker_is_rejected(self):
        def change(engine, _):
            agents = engine.load_agents()
            agents['agents'][-1]['cleanup_status'] = 'retained'
            engine._save_agents(agents)
        self.assert_rejected(change)

    def test_intent_and_nested_failure_evidence_are_immutable(self):
        engine, _, _, _, arguments = self.prepare()
        log = Path(engine.load_run()['blockers'][0]['evidence_path'])
        self.assertTrue(engine.continue_packet_build(**arguments))
        log.write_text('tampered\n')
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            engine.load_run()

    def test_crash_after_projection_recovers_without_replaying_foundation(self):
        engine, _, _, batch, arguments = self.prepare()
        with mock.patch.object(engine, '_append_event', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.continue_packet_build(**arguments)
        graph = fixtures.build_graph(engine, InMemorySaver())
        graph.invoke({'run_dir': str(self.run_dir)}, {'configurable': {'thread_id': 'lost'}, 'recursion_limit': 150})
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a.get('packet_id') == 'API-PACKET-001' for a in batch.assignments))

    def prepare_chain(self, **kwargs):
        engine, graph, config, batch, arguments = self.prepare(chain_failure=True, **kwargs)
        self.assertTrue(engine.continue_packet_build(**arguments))
        basis = engine.load_run()['packet_build_dependencies']['api']
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        run = engine.load_run()
        self.assertEqual('blocked', run['status'])
        arguments.update(validation_id='API-VAL-001', blocker_id=run['blockers'][0]['id'],
                         evidence_sha256=hashlib.sha256(Path(run['blockers'][0]['evidence_path']).read_bytes()).hexdigest())
        return engine, graph, config, batch, arguments, basis

    def test_same_provider_chain_preserves_both_failures_and_requires_both_checks(self):
        engine, graph, config, batch, arguments, basis = self.prepare_chain()
        before = engine.load_run()
        results = {Path(a['output_artifact']): Path(a['output_artifact']).read_bytes()
                   for a in batch.assignments if a['stage'] == 'implement'}
        self.assertTrue(engine.continue_packet_build(**arguments))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        run = engine.load_run()
        self.assertEqual('complete', run['status'])
        self.assertEqual(basis, run['packet_build_dependencies']['api'])
        self.assertEqual(before['plan_review'], run['plan_review'])
        self.assertEqual(before['retry_limits'], run['retry_limits'])
        for path, raw in results.items():
            self.assertEqual(raw, path.read_bytes())
            self.assertEqual('blocked', json.loads(raw)['status'])
        writers = [a for a in batch.assignments if a['stage'] == 'implement']
        self.assertEqual(3, len(writers))
        self.assertEqual(['API-VAL-001', 'API-VAL-002', 'API-VAL-003'], writers[-1]['validation_ids'])
        progress = run['packet_build_progress']['api']
        self.assertEqual(1, len(progress))
        self.assertIn(progress[0], writers[-1]['input_artifacts'])
        self.assertEqual(basis, json.loads(Path(progress[0]['path']).read_text())['basis'])

    def test_chain_does_not_waive_failing_tests_after_provider(self):
        engine, graph, config, batch, arguments, _ = self.prepare_chain(late_test_failure=True)
        self.assertTrue(engine.continue_packet_build(**arguments))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(1, sum(a['stage'] == 'validation-fix' for a in batch.assignments))
        self.assertFalse(any(a['stage'] in {'review-1', 'deliver'} for a in batch.assignments))
        self.assertFalse(engine.continue_packet_build(**arguments))

    def test_chain_retains_isolated_database_gate(self):
        engine, graph, config, _, arguments, _ = self.prepare_chain(chain_migration=True)
        target = engine.load_run()['repositories']['api']['database_target_evidence']
        self.assertTrue(engine.continue_packet_build(**arguments))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(target, engine.load_run()['repositories']['api']['database_target_evidence'])

    def test_chain_requires_classification_for_migration_capable_check(self):
        engine, _, _, _, arguments, _ = self.prepare_chain(chain_migration=True)
        run = engine.load_run()
        del run['repositories']['api']['database_target_evidence']
        engine._save_run(run)
        before = engine.run_path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError):
            engine.continue_packet_build(**arguments)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_chain_rejects_different_receiver_and_runtime_failure(self):
        engine, _, _, _, arguments, _ = self.prepare_chain()
        log = Path(engine.load_run()['blockers'][0]['evidence_path'])
        original = log.read_text()
        for text in (original.replace('apiHandler does', 'otherHandler does'), original + '--- FAIL: TestOther\n'):
            log.write_text(text)
            arguments['evidence_sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
            with self.assertRaises(fixtures.WorkflowError):
                engine.continue_packet_build(**arguments)

    def test_chain_cannot_readmit_a_packet(self):
        engine, _, _, _, arguments, _ = self.prepare_chain()
        before = engine.load_run()
        self.assertTrue(engine.continue_packet_build(**arguments))
        # Simulate a stale blocker projection, not another source attempt.
        run = engine.load_run()
        run.update(status='blocked', blockers=before['blockers'])
        engine._save_run(run)
        raw = engine.run_path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError):
            engine.continue_packet_build(**arguments)
        self.assertEqual(raw, engine.run_path.read_bytes())

    def assert_chain_command_rejected(self, command):
        engine, _, _, _, arguments, _ = self.prepare_chain(chain_command=command)
        before = engine.run_path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError):
            engine.continue_packet_build(**arguments)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_chain_rejects_attached_and_operator(self):
        self.assert_chain_command_rejected('go test ./...&&printf chained')

    def test_chain_rejects_attached_or_operator(self):
        self.assert_chain_command_rejected('go test ./...||printf chained')

    def test_chain_rejects_attached_pipe(self):
        self.assert_chain_command_rejected('go test ./...|printf chained')

    def test_chain_rejects_newline_separator(self):
        self.assert_chain_command_rejected('go test ./...\nprintf chained')

    def test_chain_accepts_quoted_regex_operators_and_dollar_anchor(self):
        engine, graph, config, _, arguments, _ = self.prepare_chain(
            chain_command="go test ./... -run '^Test(Handler|Other)$'")
        self.assertTrue(engine.continue_packet_build(**arguments))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])

    def test_chain_rejects_database_classification_hash_drift(self):
        engine, _, _, _, arguments, _ = self.prepare_chain(chain_migration=True)
        target = Path(engine.load_run()['repositories']['api']['database_target_evidence']['path'])
        target.write_text(target.read_text().replace('Injected isolated fixture', 'Changed classification description'))
        before = engine.run_path.read_bytes()
        with self.assertRaises((fixtures.WorkflowError, fixtures.artifact_guard.ValidationError)):
            engine.continue_packet_build(**arguments)
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(list((self.run_dir / 'repos/api').glob('packet-build-progress-*.json')))

    def test_chain_cannot_hide_an_unrelated_compiler_error(self):
        engine, _, _, _, arguments, _ = self.prepare_chain(mixed_compile_failure=True)
        before = engine.run_path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError):
            engine.continue_packet_build(**arguments)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_chain_cannot_move_its_original_provider(self):
        engine, _, _, _, arguments, _ = self.prepare_chain()
        before = engine.run_path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError):
            engine.continue_packet_build(**dict(arguments, until_task='API-TASK-999'))
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_chain_recovery_survives_projection_crash_without_replay(self):
        engine, _, _, batch, arguments, _ = self.prepare_chain()
        with mock.patch.object(engine, '_append_event', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.continue_packet_build(**arguments)
        graph = fixtures.build_graph(engine, InMemorySaver())
        graph.invoke({'run_dir': str(self.run_dir)}, {'configurable': {'thread_id': 'chain-crash'}, 'recursion_limit': 150})
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(3, len([a for a in batch.assignments if a['stage'] == 'implement']))

    def test_chain_evidence_is_immutable(self):
        engine, _, _, _, arguments, _ = self.prepare_chain()
        log = Path(engine.load_run()['blockers'][0]['evidence_path'])
        self.assertTrue(engine.continue_packet_build(**arguments))
        log.write_text('tampered\n')
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            engine.load_run()

    def test_omitted_assigned_check_is_not_treated_as_passing(self):
        self.assert_rejected(lambda *_: None, omit_check=True)

    def test_unassigned_check_cannot_substitute_for_exact_assigned_suite(self):
        self.assert_rejected(lambda *_: None, extra_check=True)

    def test_concurrently_accepted_blocked_peer_is_not_replayed(self):
        engine, _, _, batch, arguments = self.prepare(multi=True)
        self.assertEqual('pending', engine.load_run()['repositories']['core']['status'])
        self.assertEqual(2, len([a for a in batch.assignments if a['stage'] == 'implement']))
        before = engine.run_path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError):
            engine.continue_packet_build(**arguments)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_independent_packet_is_not_a_downstream_provider(self):
        self.assert_rejected(lambda *_: None, independent_provider=True)

    def test_provider_must_require_the_deferred_build(self):
        self.assert_rejected(lambda *_: None, provider_without_build=True)

    def test_additional_worker_blockers_prevent_continuation(self):
        self.assert_rejected(lambda *_: None, extra_blocker=True)

    def test_another_validation_cannot_be_deferred(self):
        self.assert_rejected(lambda _, a: a.update(validation_id='API-VAL-001'))

    def test_empty_authorization_is_rejected(self):
        self.assert_rejected(lambda _, a: a.update(text=' '))

    def test_head_drift_is_rejected(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(
            ['git', 'commit', '--allow-empty', '-qm', 'drift'], cwd=self.worktree, check=True))

    def test_index_drift_is_rejected(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(
            ['git', 'add', 'feature.txt'], cwd=self.worktree, check=True))

    def test_branch_drift_is_rejected(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(
            ['git', 'branch', '-m', 'drift'], cwd=self.worktree, check=True))

    def test_crash_before_projection_reuses_only_identical_intent(self):
        engine, graph, config, _, arguments = self.prepare()
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.continue_packet_build(**arguments)
        path = self.run_dir / 'repos/api/packet-build-dependency.json'
        before = path.read_bytes()
        with self.assertRaises(fixtures.WorkflowError):
            engine.continue_packet_build(**dict(arguments, text='different authorization'))
        self.assertTrue(engine.continue_packet_build(**arguments))
        self.assertEqual(before, path.read_bytes())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])

    def test_cli_dispatches_back_to_graph(self):
        import orchestrator
        engine, graph, config, _, arguments = self.prepare()
        args = orchestrator.build_parser().parse_args([
            'continue-packet-build', str(self.run_dir), '--repository', 'api',
            '--blocker-id', arguments['blocker_id'], '--review-sha256', arguments['review_sha256'],
            '--validation-id', arguments['validation_id'], '--until-task', arguments['until_task'],
            '--evidence-sha256', arguments['evidence_sha256'], '--text', arguments['text'],
        ])
        with mock.patch.object(orchestrator, '_open_graph') as opened:
            opened.return_value.__enter__.return_value = (engine, graph, config)
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
        self.assertEqual('complete', result['status'])
