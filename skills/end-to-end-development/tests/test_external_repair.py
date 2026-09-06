from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

import test_workflow_engine as fixtures
import external_repair
import orchestrator


class ExternalRepairTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def git(self, *args, cwd=None):
        return fixtures.subprocess.check_output(['git', '-C', str(cwd or self.worktree), *args]).decode().strip()

    def tree(self):
        index = self.root / 'scratch-index'
        index.unlink(missing_ok=True)
        env = {**os.environ, 'GIT_INDEX_FILE': str(index)}
        for args in (['read-tree', 'HEAD'], ['add', '--all']):
            fixtures.subprocess.run(['git', *args], cwd=self.worktree, env=env, check=True)
        return fixtures.subprocess.check_output(['git', 'write-tree'], cwd=self.worktree, env=env).decode().strip()

    def reference(self, path):
        return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def prepare(self, *, failed=False, material=False, modern=False, migration=False, later_packet=False, multi=False):
        (self.worktree / 'test_fixture.py').write_text('obsolete = True\n')
        self.git('add', 'test_fixture.py')
        self.git('commit', '-qm', 'fixture foundation')
        batch = fixtures.FakeSuccessfulBatch(migration_capable=migration)
        rejected = False

        def worker(paths, **kwargs):
            nonlocal rejected
            if any(json.loads(path.read_text())['stage'] == 'deliver' for path in paths):
                self.git('add', 'test_fixture.py')
            if any(json.loads(path.read_text()).get('execution_mode') == 'packet-verification' for path in paths):
                # Extend the generic fake payload before the real engine acceptance seam validates it.
                with mock.patch.dict(fixtures.artifact_guard.VALIDATORS, result=lambda _: None):
                    code, manifest = batch(paths, **kwargs)
            else:
                code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                output = Path(assignment['output_artifact'])
                artifact = json.loads(output.read_text())
                if assignment['stage'] == 'contract' and multi:
                    artifact['requirement_map'] = {'REQ-001': ['api', 'core']}
                if assignment['stage'] == 'plan' and later_packet:
                    artifact['validations'].append(dict(artifact['validations'][0], id='API-VAL-002',
                                                        command='python -m unittest discover', scope='broad'))
                    task = dict(artifact['tasks'][0], id='API-TASK-002', depends_on=['API-TASK-001'],
                                validation_ids=['API-VAL-002'])
                    artifact['tasks'].append(task)
                    artifact['work_packets'].append(dict(artifact['work_packets'][0], id='API-PACKET-002',
                        task_ids=['API-TASK-002'], depends_on=['API-PACKET-001']))
                if assignment.get('execution_mode') == 'packet-verification':
                    evidence = Path(assignment['log_dir']) / 'scope.md'
                    evidence.write_text('Independent current-tree packet and scope inspection.\n')
                    artifact['changed_files'] = ['feature.txt', 'test_fixture.py']
                    artifact['packet_verification'] = {'outcome': 'material-change' if material else 'compatible',
                        'summary': 'Inspected existing packet against the approved plan.', 'evidence_path': str(evidence)}
                    if failed:
                        artifact['validations'][0].update(result='fail', exit_code=1)
                    if material:
                        artifact.update(status='blocked', blockers=[{'id': 'BLOCK-SCOPE', 'kind': 'decision',
                            'summary': 'Material contract change requires a new approved plan.', 'evidence_path': str(evidence),
                            'required_action': 'Replan through normal bounded planning and renew full-bundle approval.'}])
                elif assignment['stage'] == 'implement' and not rejected:
                    rejected = True
                    evidence = Path(assignment['log_dir']) / 'failure.md'
                    evidence.write_text('Full test failed in obsolete test fixtures.\n')
                    artifact['validations'][0].update(result='fail', exit_code=1)
                    scope_log = Path(assignment['log_dir']) / 'original-scope.log'
                    scope_log.write_text('Original packet scope inspection.\n')
                    artifact['decisions'][0]['evidence'] = str(scope_log)
                    artifact.update(status='blocked', next_action='Preserve failed evidence and await scoped repair. ' * 15,
                        blockers=[{'id': 'BLOCK-TEST', 'kind': 'code', 'summary': 'Obsolete fixture fails full test.',
                                   'evidence_path': str(evidence), 'required_action': 'Repair the fixture only.'}])
                    worker = next(w for w in manifest['workers'] if w['action_id'] == assignment['action_id'])
                    worker.update(status='rejected', cleanup_status='complete', error_code='invalid-evidence',
                        error_path='$.next_action', reason='$.next_action: must be at most 300 characters',
                        output_artifact=str(output), assignment_path=str(path))
                    code = 1
                output.write_text(json.dumps(artifact) + '\n')
                if assignment['stage'] == 'implement' and assignment.get('execution_mode') != 'packet-verification':
                    fixtures.workflow_tools.normalize_worker_artifact(path, assignment, output, artifact)
            return code, manifest

        def write_multi_spec(**kwargs):
            fixtures.WorkflowEngineTests.write_spec(self, **kwargs)
            spec = json.loads(self.spec.read_text())
            spec['requirements'][0]['repository_ids'] = ['api', 'core']
            peer = self.root / 'core-worktree'
            self.git('worktree', 'add', '-qb', 'feat/core', str(peer), cwd=self.repo)
            spec['repositories'].append({'repo_id': 'core', 'root': str(self.repo), 'worktree': str(peer),
                                         'base_branch': 'master', 'branch': 'feat/core'})
            self.spec.write_text(json.dumps(spec))
        if multi:
            with mock.patch.object(self, 'write_spec', side_effect=write_multi_spec):
                engine = self.initialize(worker, profile='full', legacy=not modern)
        else:
            engine = self.initialize(worker, profile='full', legacy=not modern)
        if migration:
            engine.record_database_target(repo_id='api', classification='isolated-test',
                description='Synthetic fixture only. No commands or databases are executed.')
        graph = fixtures.build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'external-repair'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume={'decision': 'approve', 'review_sha256': review['review_sha256'],
                    'text': 'approved all plans'}), config)
        before = engine.load_run()
        self.assertEqual(('blocked', 'implement'), (before['status'], before['phase']))
        assignment = next(a for a in batch.assignments if a['stage'] == 'implement')
        output = Path(assignment['output_artifact'])
        original = json.loads(output.read_text())
        old_head, old_tree = self.git('rev-parse', 'HEAD'), self.tree()
        # A real forward base update in a disposable repository; never a product checkout.
        (self.worktree / 'upstream.txt').write_text('merged fixture fix\n')
        self.git('add', 'upstream.txt')
        self.git('commit', '-qm', 'upstream fixture fix')
        new_head = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/main', new_head)
        (self.worktree / 'test_fixture.py').write_text('obsolete = False\n')
        evidence = {Path(review['review_path']), output, Path(original['assignment_path']),
                    Path(before['blockers'][0]['evidence_path'])}
        artifacts = [item for key in before['repositories'] for item in engine._artifacts(repo_id=key)]
        for path, artifact, _ in [*artifacts, *engine._artifacts(), (output, original, assignment)]:
            evidence.update({path, Path(artifact['assignment_path'])})
            evidence.update(fixtures.workflow_tools.artifact_evidence_paths(artifact))
        evidence.add(Path(original['decisions'][0]['evidence']))
        target = before['repositories']['api'].get('database_target_evidence')
        if target:
            evidence.add(Path(target['path']))
        approval = self.root / 'external-authorization.md'
        approval.write_text('Rebase only this repository and repair test_fixture.py without production changes.\n')
        external_log = self.root / 'external-passing.log'
        external_log.write_text('External checks passed, NOT workflow evidence.\n')
        evidence.add(external_log)
        request = {'run_id': before['run_id'], 'repo_id': 'api', 'blocker_id': before['blockers'][0]['id'],
            'expected_run_sha256': self.reference(engine.run_path)['sha256'], 'result': self.reference(output),
            'assignment': self.reference(Path(original['assignment_path'])),
            'rejection': self.reference(Path(before['blockers'][0]['evidence_path'])),
            'transition': {'before_head': old_head, 'before_tree': old_tree, 'after_head': new_head,
                'after_tree': self.tree(), 'target_ref': 'refs/remotes/origin/main', 'repair_paths': ['test_fixture.py']},
            'external_authorization': {'text': approval.read_text(), 'evidence': [self.reference(approval)]},
            'reviewed_evidence': [self.reference(p) for p in sorted(evidence)], 'database_target': target}
        decision = {'request_sha256': external_repair.digest(request),
                    'text': 'Authorize fresh read-only verification of this reviewed recovery request.',
                    'context': 'External checks are preservation evidence, not accepted passes.'}
        return engine, graph, config, batch, request, decision

    def test_success_preserves_history_and_runs_remaining_gates(self):
        engine, graph, config, batch, request, decision = self.prepare(later_packet=True)
        before = engine.load_run()
        evidence = {Path(r['path']): Path(r['path']).read_bytes() for r in request['reviewed_evidence']}
        source = fixtures.workflow_tools.repository_state(self.worktree)
        self.assertEqual('applied', engine.recover_external_repair(request, **decision))
        self.assertIsNone(engine._current_validation('api', require_pass=True))
        self.assertEqual(source, fixtures.workflow_tools.repository_state(self.worktree))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        after = engine.load_run()
        self.assertEqual('complete', after['status'])
        for key in ('retry_limits', 'plan_review', 'artifact_repairs'):
            self.assertEqual(before.get(key), after.get(key))
        self.assertEqual(before['repositories']['api']['baseline'], after['repositories']['api']['baseline'])
        for path, raw in evidence.items():
            self.assertEqual(raw, path.read_bytes(), str(path))
        self.assertNotIn(json.loads(Path(request['assignment']['path']).read_text())['action_id'],
                         after['repositories']['api']['accepted_artifacts'])
        verify = [a for a in batch.assignments if a.get('execution_mode') == 'packet-verification']
        self.assertEqual(1, len(verify))
        self.assertEqual('none', verify[0]['project_file_access'])
        self.assertEqual(['API-VAL-001'], verify[0]['validation_ids'])
        final_writer = next(a for a in batch.assignments if a.get('packet_id') == 'API-PACKET-002')
        self.assertEqual(['API-VAL-001', 'API-VAL-002'], final_writer['validation_ids'])
        self.assertEqual(['API-PACKET-001', 'API-PACKET-002'],
                         [a['packet_id'] for a in batch.assignments if a['stage'] == 'implement' and a not in verify])
        self.assertEqual(1, sum(a['stage'] == 'review-1' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'deliver' for a in batch.assignments))
        self.assertEqual('already-applied', engine.recover_external_repair(request, **decision))

    def test_fresh_failures_are_not_passes_or_implicit_repairs(self):
        engine, graph, config, batch, request, decision = self.prepare(failed=True)
        engine.recover_external_repair(request, **decision)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertIn('Fresh external-repair verification failed', engine.load_run()['blockers'][0]['summary'])
        self.assertFalse(engine.resume_external_blockers())
        self.assertFalse(any(a['stage'] in {'validation-fix', 'review-1', 'deliver'} for a in batch.assignments))
        self.assertIsNone(engine._current_validation('api', require_pass=True))
        before = engine.run_path.read_bytes()
        self.assertEqual('already-applied', engine.recover_external_repair(request, **decision))
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_new_policy_uses_same_narrow_recovery_without_policy_retrofit(self):
        engine, graph, config, _, request, decision = self.prepare(modern=True)
        engine.recover_external_repair(request, **decision)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])

    def test_material_change_requires_normal_replanning_and_renewed_approval(self):
        engine, graph, config, batch, request, decision = self.prepare(material=True)
        engine.recover_external_repair(request, **decision)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        run = engine.load_run()
        self.assertEqual('decision', run['blockers'][0]['kind'])
        blocker = run['blockers'][0]
        engine.replan_decision(review_sha256=run['plan_review']['review_sha256'], blocker_id=blocker['id'],
            blocker_evidence_sha256=self.reference(Path(blocker['evidence_path']))['sha256'],
            text='Revise the plans for the discovered contract change.')
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('awaiting-user', engine.load_run()['status'])
        self.assertFalse(any(a['stage'] in {'review-1', 'deliver'} for a in batch.assignments))

    def assert_rejected(self, change, *, refresh_request=False, refresh_run=False, **kwargs):
        engine, _, _, _, request, decision = self.prepare(**kwargs)
        change(engine, request, decision)
        if refresh_run:
            request['expected_run_sha256'] = self.reference(engine.run_path)['sha256']
        if refresh_request or refresh_run:
            decision['request_sha256'] = external_repair.digest(request)
        before = engine.run_path.read_bytes()
        with self.assertRaises((fixtures.WorkflowError, fixtures.artifact_guard.ValidationError, ValueError, OSError)):
            engine.recover_external_repair(request, **decision)
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(list(self.run_dir.glob('external-repair-*.json')))

    def test_generic_continuation_is_not_recovery_authorization(self):
        self.assert_rejected(lambda _, __, decision: decision.update(text='continue'))

    def test_negated_authorization_is_rejected(self):
        self.assert_rejected(lambda _, __, decision: decision.update(text='Do not authorize recovery.'))

    def test_stale_request_hash(self):
        self.assert_rejected(lambda _, r, __: r.update(blocker_id='other'))

    def test_wrong_blocker(self):
        self.assert_rejected(lambda _, r, __: r.update(blocker_id='other'), refresh_request=True)

    def test_omitted_auxiliary_scope_evidence_is_rejected(self):
        self.assert_rejected(lambda _, r, __: r.update(reviewed_evidence=[ref for ref in r['reviewed_evidence']
            if not ref['path'].endswith('original-scope.log')]), refresh_request=True)

    def test_tampered_rejected_result(self):
        self.assert_rejected(lambda _, r, __: Path(r['result']['path']).write_text('{}'))

    def test_tampered_original_failed_log(self):
        def change(_, request, __):
            original = json.loads(Path(request['result']['path']).read_text())
            Path(original['validations'][0]['log_path']).write_text('manufactured pass\n')
        self.assert_rejected(change)

    def test_stale_approval(self):
        self.assert_rejected(lambda e, *_: Path(e.load_run()['plan_review']['review_path']).write_text('different plan'))

    def test_approval_text_tampering(self):
        def change(e, *_):
            run = e.load_run()
            run['plan_review']['approval_text'] = 'different approval'
            e._save_run(run)
        self.assert_rejected(change)

    def test_unauthorized_source_change_even_with_reviewed_after_tree(self):
        def change(_, request, __):
            (self.worktree / 'feature.txt').write_text('lost existing work\n')
            request['transition']['after_tree'] = self.tree()
        self.assert_rejected(change, refresh_request=True)

    def test_production_path_cannot_be_allowlisted_as_fixture_repair(self):
        self.assert_rejected(lambda _, r, __: r['transition'].update(repair_paths=['feature.txt']), refresh_request=True)

    def test_before_tree_cannot_be_freshened(self):
        self.assert_rejected(lambda _, r, __: r['transition'].update(before_tree=r['transition']['after_tree']), refresh_request=True)

    def test_branch_drift(self):
        self.assert_rejected(lambda *_: self.git('branch', '-m', 'other'))

    def test_head_drift(self):
        self.assert_rejected(lambda *_: self.git('commit', '--allow-empty', '-qm', 'other'))

    def test_index_drift(self):
        self.assert_rejected(lambda *_: self.git('add', 'feature.txt'))

    def test_live_or_unclean_handle(self):
        def change(e, *_):
            agents = e.load_agents()
            agents['agents'][-1].update(status='working', cleanup_status='retained')
            e._save_agents(agents)
        self.assert_rejected(change)

    def test_active_supervisor_handle_even_when_agent_projection_is_clean(self):
        def change(e, *_):
            (e.run_dir / 'supervisor/worker-orphan.json').write_text(json.dumps({'status': 'working', 'cleanup_status': 'pending'}))
        self.assert_rejected(change)

    def test_lease_and_active_action(self):
        def change(e, request, _):
            e._install_actions([Path(request['assignment']['path'])])
        self.assert_rejected(change, refresh_run=True)

    def test_database_target_hash_is_mandatory(self):
        self.assert_rejected(lambda _, r, __: r.update(database_target=None), migration=True, refresh_request=True)

    def test_isolated_database_evidence_preserved_without_accessing_database(self):
        engine, graph, config, _, request, decision = self.prepare(migration=True)
        engine.recover_external_repair(request, **decision)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])

    def test_pre_projection_crash_reuses_only_identical_intent(self):
        engine, _, _, _, request, decision = self.prepare()
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.recover_external_repair(request, **decision)
        intent = next(self.run_dir.glob('external-repair-*.json'))
        before = intent.read_bytes()
        with self.assertRaisesRegex(fixtures.WorkflowError, 'intent differs'):
            engine.recover_external_repair(request, **dict(decision, text='I authorize recovery of this reviewed request.'))
        engine.recover_external_repair(request, **decision)
        self.assertEqual(before, intent.read_bytes())

    def test_post_projection_crash_recovers_via_graph_without_source_replay(self):
        engine, _, _, batch, request, decision = self.prepare()
        with mock.patch.object(engine, '_append_event', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.recover_external_repair(request, **decision)
        graph = fixtures.build_graph(engine, InMemorySaver())
        graph.invoke({'run_dir': str(self.run_dir)}, {'configurable': {'thread_id': 'lost'}, 'recursion_limit': 150})
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_acceptance_crash_does_not_relaunch_verification(self):
        engine, graph, config, batch, request, decision = self.prepare()
        engine.recover_external_repair(request, **decision)
        execute = engine._execute_assignments
        def crash(paths):
            execute(paths)
            raise KeyboardInterrupt
        with mock.patch.object(engine, '_execute_assignments', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                engine.phase_implement()
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a.get('execution_mode') == 'packet-verification' for a in batch.assignments))

    def test_indeterminate_launch_is_not_repeated(self):
        engine, graph, config, batch, request, decision = self.prepare()
        engine.recover_external_repair(request, **decision)
        with mock.patch.object(engine, '_execute_assignments', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.phase_implement()
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(0, sum(a.get('execution_mode') == 'packet-verification' for a in batch.assignments))

    def test_request_and_nested_evidence_remain_pinned_after_application(self):
        engine, _, _, _, request, decision = self.prepare()
        engine.recover_external_repair(request, **decision)
        Path(request['external_authorization']['evidence'][0]['path']).write_text('different authorization')
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            engine.load_run()

    def test_multiple_repositories_retain_integration_and_independent_reviews(self):
        engine, graph, config, batch, request, decision = self.prepare(multi=True)
        engine.recover_external_repair(request, **decision)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'], engine.load_run()['blockers'])
        self.assertEqual(2, sum(a['stage'] == 'review-1' for a in batch.assignments))
        self.assertEqual(1, sum(a['stage'] == 'integrate' for a in batch.assignments))

    def test_unauthorized_peer_changes(self):
        self.assert_rejected(lambda e, *_: (Path(e.load_run()['repositories']['core']['worktree']) / 'feature.txt').write_text('drift'), multi=True)

    def test_unrelated_failure_is_not_cleared(self):
        def change(engine, *_):
            run = engine.load_run()
            run['blockers'].append(dict(run['blockers'][0], id='BLOCK-OTHER', summary='Another failure'))
            engine._save_run(run)
        self.assert_rejected(change, refresh_run=True)

    def test_bare_writer_lease_is_not_cleared(self):
        def change(engine, *_):
            run = engine.load_run()
            run['repositories']['api']['active_writer'] = 'unrelated-writer'
            engine._save_run(run)
        self.assert_rejected(change, refresh_run=True)

    def test_result_complete_is_not_recoverable(self):
        def change(_, request, __):
            path = Path(request['result']['path'])
            data = json.loads(path.read_text())
            data.update(status='complete', blockers=[])
            path.write_text(json.dumps(data))
            ref = self.reference(path)
            request['result'] = ref
            request['reviewed_evidence'] = [ref if item['path'] == str(path) else item for item in request['reviewed_evidence']]
        self.assert_rejected(change, refresh_request=True)

    def test_old_check_cwd_cannot_be_relabelled(self):
        def change(_, request, __):
            path = Path(request['result']['path'])
            data = json.loads(path.read_text())
            data['validations'][0]['cwd'] = str(self.repo)
            path.write_text(json.dumps(data))
            ref = self.reference(path)
            request['result'] = ref
            request['reviewed_evidence'] = [ref if item['path'] == str(path) else item for item in request['reviewed_evidence']]
        self.assert_rejected(change, refresh_request=True)

    def test_current_tree_drift_after_authorization_never_launches(self):
        engine, _, _, batch, request, decision = self.prepare()
        engine.recover_external_repair(request, **decision)
        (self.worktree / 'feature.txt').write_text('unauthorized\n')
        with self.assertRaisesRegex(fixtures.WorkflowError, 'state changed'):
            engine.phase_implement()
        self.assertEqual(1, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_current_tree_drift_after_verification_never_schedules_next_packet(self):
        engine, _, _, batch, request, decision = self.prepare(later_packet=True)
        engine.recover_external_repair(request, **decision)
        engine.phase_implement()
        (self.worktree / 'feature.txt').write_text('unauthorized\n')
        with self.assertRaisesRegex(fixtures.WorkflowError, 'unauthorized source change'):
            engine.phase_implement()
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_fresh_scope_and_check_evidence_cannot_be_tampered(self):
        engine, _, _, _, request, decision = self.prepare()
        engine.recover_external_repair(request, **decision)
        engine.phase_implement()
        result = engine._artifacts(repo_id='api', stage='implement')[-1][1]
        for key in (result['packet_verification']['evidence_path'], result['validations'][0]['log_path']):
            path = Path(key)
            raw = path.read_bytes()
            path.write_text('tampered\n')
            with self.assertRaises(fixtures.artifact_guard.ValidationError):
                engine.load_run()
            path.write_bytes(raw)

    def test_worker_cannot_reuse_external_passing_log(self):
        engine, graph, config, batch, request, decision = self.prepare()
        worker = engine.batch_runner
        def reuse(paths, **kwargs):
            code, manifest = worker(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                if assignment.get('execution_mode') == 'packet-verification':
                    output = Path(assignment['output_artifact'])
                    data = json.loads(output.read_text())
                    data['validations'][0]['log_path'] = str(self.root / 'external-passing.log')
                    output.write_text(json.dumps(data))
            return code, manifest
        engine.batch_runner = reuse
        engine.recover_external_repair(request, **decision)
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('blocked', engine.load_run()['status'])
        self.assertEqual(1, sum(a.get('execution_mode') == 'packet-verification' for a in batch.assignments))
        self.assertFalse(any(a['stage'] == 'review-1' for a in batch.assignments))

    def test_unclean_verifier_cannot_unlock_a_later_writer(self):
        engine, _, _, batch, request, decision = self.prepare(later_packet=True)
        engine.recover_external_repair(request, **decision)
        engine.phase_implement()
        agents = engine.load_agents()
        agents['agents'][-1].update(status='idle', cleanup_status='failed')
        engine._save_agents(agents)
        self.assertEqual('blocked', engine.phase_implement())
        self.assertIn('handle is not closed', engine.load_run()['blockers'][0]['summary'])
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_output_capture_crash_is_reconciled_once(self):
        engine, graph, config, batch, request, decision = self.prepare()
        engine.recover_external_repair(request, **decision)
        with mock.patch.object(engine, '_record_accepted_reference', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.phase_implement()
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('complete', engine.load_run()['status'], engine.load_run()['blockers'])
        self.assertEqual(1, sum(a.get('execution_mode') == 'packet-verification' for a in batch.assignments))

    def test_sqlite_checkpoint_restart_reuses_accepted_verification(self):
        engine, _, config, batch, request, decision = self.prepare()
        engine.recover_external_repair(request, **decision)
        execute = engine._execute_assignments
        def crash(paths):
            execute(paths)
            raise KeyboardInterrupt
        checkpoint = str(self.run_dir / 'synthetic-checkpoint.sqlite')
        with SqliteSaver.from_conn_string(checkpoint) as saver:
            graph = fixtures.build_graph(engine, saver)
            with mock.patch.object(engine, '_execute_assignments', side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):
                    graph.invoke({'run_dir': str(self.run_dir)}, config)
            self.assertTrue(graph.get_state(config).next)
        with SqliteSaver.from_conn_string(checkpoint) as saver:
            graph = fixtures.build_graph(engine, saver)
            graph.invoke(None, config)
        self.assertEqual('complete', engine.load_run()['status'])
        self.assertEqual(1, sum(a.get('execution_mode') == 'packet-verification' for a in batch.assignments))

    def test_cli_cursor_guard_dispatch_and_duplicate(self):
        engine, graph, config, batch, request, decision = self.prepare()
        path = self.root / 'request.json'
        path.write_text(json.dumps(request))
        args = orchestrator.build_parser().parse_args(['recover-external-repair', str(self.run_dir), '--input', str(path),
            '--request-sha256', decision['request_sha256'], '--text', decision['text'], '--context', decision['context']])
        with mock.patch.object(orchestrator, '_open_graph') as opened:
            opened.return_value.__enter__.return_value = (engine, graph, config)
            with mock.patch.object(graph, 'get_state') as state:
                state.return_value.next = ('implement',)
                with self.assertRaisesRegex(fixtures.WorkflowError, 'settled graph cursor'):
                    orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            self.assertEqual('complete', result['status'])
            count = len(batch.assignments)
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
            self.assertEqual('already-applied', result['recovery'])
            self.assertEqual(count, len(batch.assignments))
