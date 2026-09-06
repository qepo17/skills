from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from langgraph.checkpoint.memory import InMemorySaver

import test_workflow_engine as fixtures


class DecisionReplanningTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    now = fixtures.WorkflowEngineTests.now
    write_spec = fixtures.WorkflowEngineTests.write_spec
    initialize = fixtures.WorkflowEngineTests.initialize

    def prepare(self, *, contract=False, multi=False, extra_blocker=False, reverse_ids=False):
        batch = fixtures.FakeSuccessfulBatch(risk_flags=['security'])
        blocked_once = False

        def decision_batch(paths, **kwargs):
            nonlocal blocked_once
            code, manifest = batch(paths, **kwargs)
            for path in paths:
                assignment = json.loads(path.read_text())
                output = Path(assignment['output_artifact'])
                artifact = json.loads(output.read_text())
                if reverse_ids:
                    artifact['created_at'] = '2026-08-22T10:00:00Z'
                if assignment['stage'] == 'contract' and multi:
                    artifact['requirement_map'] = {'REQ-001': ['api', 'core', 'ui']}
                    artifact['dependencies'] = [
                        {'from_repo_id': consumer, 'to_repo_id': producer,
                         'reason': 'Producer first.', 'evidence': 'Contract-first requirement.'}
                        for consumer, producer in [('core', 'api'), ('ui', 'core')]]
                elif assignment['stage'] == 'plan':
                    task = copy.deepcopy(artifact['tasks'][0])
                    task.update(id='API-TASK-002', depends_on=['API-TASK-001'])
                    packet = copy.deepcopy(artifact['work_packets'][0])
                    packet.update(id='API-PACKET-002', task_ids=['API-TASK-002'],
                                  depends_on=['API-PACKET-001'])
                    artifact['tasks'].append(task)
                    artifact['work_packets'].append(packet)
                    if reverse_ids:
                        names = {'API-PACKET-001': 'API-PACKET-Z', 'API-PACKET-002': 'API-PACKET-A'}
                        for packet in artifact['work_packets']:
                            packet['id'] = names[packet['id']]
                            packet['depends_on'] = [names[name] for name in packet['depends_on']]
                        artifact['work_packets'].sort(key=lambda packet: packet['id'])
                elif (assignment.get('packet_id') == ('API-PACKET-001' if multi else 'API-PACKET-A' if reverse_ids else 'API-PACKET-002')
                      and assignment['repo_id'] == ('core' if multi else 'api') and not blocked_once):
                    blocked_once = True
                    evidence = self.run_dir / 'decision.md'
                    evidence.write_text('Shared input limits need a product decision.\n')
                    artifact.update(status='blocked', blockers=[{
                        'id': 'BLOCK-DECISION', 'kind': 'decision',
                        'summary': 'Shared input limits require revised plans.',
                        'evidence_path': str(evidence),
                        'required_action': 'Choose bounded or unbounded inputs and replan.',
                    }])
                    if extra_blocker:
                        artifact['blockers'].append(dict(artifact['blockers'][0], id='BLOCK-OTHER',
                                                         kind='environment', summary='Unrelated database target issue.'))
                output.write_text(json.dumps(artifact) + '\n')
            return code, manifest

        def write_multi_spec(**kwargs):
            fixtures.WorkflowEngineTests.write_spec(self, **kwargs)
            if multi:
                spec = json.loads(self.spec.read_text())
                spec['requirements'][0]['repository_ids'] = ['api', 'core', 'ui']
                for repo_id in ('core', 'ui'):
                    root, worktree = self.root / f'{repo_id}-repo', self.root / f'{repo_id}-worktree'
                    fixtures.subprocess.run(['git', 'clone', '-q', str(self.repo), str(root)], check=True)
                    branch = f'feat/{repo_id}-test'
                    fixtures.subprocess.run(['git', 'worktree', 'add', '-qb', branch, str(worktree)], cwd=root, check=True)
                    spec['repositories'].append({'repo_id': repo_id, 'root': str(root), 'worktree': str(worktree),
                                                 'branch': branch, 'base_branch': 'master'})
                self.spec.write_text(json.dumps(spec))
        with mock.patch.object(self, 'write_spec', side_effect=write_multi_spec):
            engine = self.initialize(decision_batch, profile='full', risks=['security'])
        if contract:
            run = engine.load_run()
            run['workflow_policy']['contract_required'] = True
            engine._save_run(run)
        graph = fixtures.build_graph(engine, InMemorySaver())
        config = {'configurable': {'thread_id': 'decision-replanning'}, 'recursion_limit': 150}
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        review = engine.load_run()['plan_review']
        graph.invoke(fixtures.Command(resume={
            'decision': 'approve', 'review_sha256': review['review_sha256'],
            'text': 'I approve all plans in this exact review bundle.',
        }), config)
        run = engine.load_run()
        self.assertEqual('blocked', run['status'])
        self.assertEqual('implement', run['phase'])
        self.assertFalse(engine.resume_external_blockers())
        decision = dict(review_sha256=review['review_sha256'], blocker_id=run['blockers'][0]['id'],
                        blocker_evidence_sha256=fixtures.hashlib.sha256(Path(run['blockers'][0]['evidence_path']).read_bytes()).hexdigest(),
                        text='the first one', context='User selected explicit shared input limits; propose exact values for renewed approval.')
        return engine, graph, config, batch, decision

    def test_replans_without_rewriting_evidence_and_requires_new_approval(self):
        engine, graph, config, batch, decision = self.prepare(contract=True)
        before = engine.load_run()
        evidence = {p: p.read_bytes() for p in self.run_dir.rglob('*.json')
                    if p.name not in {'run.json', 'agents.json'} and 'supervisor' not in p.parts}
        tree = fixtures.workflow_tools.repository_state(self.worktree)
        self.assertTrue(engine.replan_decision(**decision))
        self.assertFalse(engine.replan_decision(**decision))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        run = engine.load_run()
        self.assertEqual(('awaiting-user', 'plan-review'), (run['status'], run['phase']))
        self.assertEqual(before['retry_limits'], run['retry_limits'])
        self.assertEqual(tree, fixtures.workflow_tools.repository_state(self.worktree))
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))
        for path, raw in evidence.items():
            self.assertEqual(raw, path.read_bytes(), str(path))
        feedback = json.loads(Path(run['decision_replans'][0]['path']).read_text())
        self.assertEqual(before['plan_review'], feedback['previous_plan_review'])
        self.assertEqual('the first one', feedback['text'])
        self.assertEqual(2, json.loads(Path(run['contract_path']).read_text())['revision'])
        self.assertEqual(2, json.loads(Path(run['repositories']['api']['plan_path']).read_text())['revision'])
        self.assertNotEqual(before['plan_review']['review_sha256'], run['plan_review']['review_sha256'])
        with self.assertRaises(fixtures.WorkflowError):
            engine.phase_implement()
        with self.assertRaises(fixtures.WorkflowError):
            engine.apply_plan_decision({'decision': 'approve', 'review_sha256': decision['review_sha256'], 'text': 'approved all plans'})
        self.assertIsNone(engine._current_validation('api', require_pass=True))
        graph.invoke(fixtures.Command(resume={
            'decision': 'approve', 'review_sha256': run['plan_review']['review_sha256'], 'text': 'approved all plans',
        }), config)
        self.assertEqual('complete', engine.load_run()['status'])
        writers = [a for a in batch.assignments if a['stage'] == 'implement']
        self.assertEqual(4, len(writers))
        self.assertEqual(4, len({a['action_id'] for a in writers}))
        self.assertEqual(1, sum(a['stage'] == 'review-1' for a in batch.assignments))

    def test_all_repositories_revise_and_old_upstream_packets_cannot_unlock_consumers(self):
        engine, graph, config, batch, decision = self.prepare(multi=True)
        before = engine.load_run()
        self.assertEqual(['api', 'api', 'core'], [a['repo_id'] for a in batch.assignments if a['stage'] == 'implement'])
        self.assertTrue(engine.replan_decision(**decision))
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        run = engine.load_run()
        self.assertEqual('awaiting-user', run['status'])
        for repo_id, repository in run['repositories'].items():
            self.assertEqual(before['repositories'][repo_id]['baseline'], repository['baseline'])
            self.assertEqual(2, json.loads(Path(repository['plan_path']).read_text())['revision'])
            self.assertTrue(set(before['repositories'][repo_id]['accepted_artifacts']) <= set(repository['accepted_artifacts']))
        engine.apply_plan_decision({'decision': 'approve', 'review_sha256': run['plan_review']['review_sha256'], 'text': 'approved all plans'})
        engine.phase_implement()
        engine.phase_implement()
        engine.phase_implement()
        self.assertEqual(['api', 'api', 'core'], [a['repo_id'] for a in batch.assignments if a['stage'] == 'implement'][-3:])

    def test_orphaned_intent_is_reused_after_pre_projection_crash(self):
        engine, graph, config, _, decision = self.prepare()
        with mock.patch.object(engine, '_save_run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.replan_decision(**decision)
        intent = self.run_dir / 'decision-replan-v1.json'
        original = intent.read_bytes()
        self.assertTrue(engine.replan_decision(**decision))
        self.assertEqual(original, intent.read_bytes())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('awaiting-user', engine.load_run()['status'])

    def test_exhausted_contract_budget(self):
        engine, _, _, _, decision = self.prepare(contract=True)
        run = engine.load_run()
        run['retry_limits']['contract_revisions'] = 0
        engine._save_run(run)
        before = engine.run_path.read_bytes()
        with self.assertRaisesRegex(fixtures.WorkflowError, 'contract revision limit'):
            engine.replan_decision(**decision)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_branch_drift(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(['git', 'branch', '-m', 'drift'], cwd=self.worktree, check=True))

    def assert_rejected(self, change):
        engine, _, _, _, decision = self.prepare()
        change(engine, decision)
        before = engine.run_path.read_bytes()
        with self.assertRaises((fixtures.WorkflowError, fixtures.artifact_guard.ValidationError)):
            if not engine.replan_decision(**decision):
                raise fixtures.WorkflowError('ineligible')
        self.assertEqual(before, engine.run_path.read_bytes())
        self.assertFalse(list(self.run_dir.glob('decision-replan-*.json')))

    def test_same_timestamp_reverse_lexical_packets_use_recorded_worker_order(self):
        engine, _, _, _, decision = self.prepare(reverse_ids=True)
        self.assertTrue(engine.replan_decision(**decision))

    def test_reviewed_blocker_evidence_cannot_be_freshened(self):
        self.assert_rejected(lambda *_: (self.run_dir / 'decision.md').write_text('changed after review\n'))

    def test_crash_after_planning_acceptance_does_not_relaunch_accepted_workers(self):
        engine, graph, config, batch, decision = self.prepare(contract=True)
        self.assertTrue(engine.replan_decision(**decision))
        for phase in ('contract', 'plan'):
            original = engine._run_with_replacements
            def crash(paths):
                original(paths)
                raise KeyboardInterrupt
            with mock.patch.object(engine, '_run_with_replacements', side_effect=crash):
                with self.assertRaises(KeyboardInterrupt):
                    engine.execute_phase(phase)
            outputs = {Path(a['output_artifact']): Path(a['output_artifact']).read_bytes()
                       for a in batch.assignments if a['stage'] == phase}
            count = sum(a['stage'] == phase for a in batch.assignments)
            engine.execute_phase(phase)
            self.assertEqual(count, sum(a['stage'] == phase for a in batch.assignments))
            for path, raw in outputs.items():
                self.assertEqual(raw, path.read_bytes())
        graph.invoke({'run_dir': str(self.run_dir)}, config)
        self.assertEqual('awaiting-user', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_wrong_hash(self):
        self.assert_rejected(lambda _, d: d.update(review_sha256='0' * 64))

    def test_wrong_blocker(self):
        self.assert_rejected(lambda _, d: d.update(blocker_id='BLOCK-OTHER'))

    def test_empty_feedback(self):
        self.assert_rejected(lambda _, d: d.update(text=' '))

    def test_source_drift(self):
        self.assert_rejected(lambda *_: (self.worktree / 'feature.txt').write_text('drift\n'))

    def test_head_drift(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'drift'], cwd=self.worktree, check=True))

    def test_index_drift(self):
        self.assert_rejected(lambda *_: fixtures.subprocess.run(['git', 'add', 'feature.txt'], cwd=self.worktree, check=True))

    def test_approval_drift(self):
        self.assert_rejected(lambda e, _: Path(e.load_run()['plan_review']['review_path']).write_text('drift'))

    def test_unclean_worker(self):
        def change(engine, _):
            agents = engine.load_agents()
            agents['agents'][-1]['cleanup_status'] = 'retained'
            engine._save_agents(agents)
        self.assert_rejected(change)

    def test_exhausted_revision_budget(self):
        def change(engine, _):
            run = engine.load_run()
            run['retry_limits']['plan_revision_cycles'] = 0
            engine._save_run(run)
        self.assert_rejected(change)

    def test_unrelated_blocker(self):
        def change(engine, _):
            run = engine.load_run()
            run['blockers'][0]['summary'] = 'An unrelated decision.'
            engine._save_run(run)
        self.assert_rejected(change)

    def test_crash_after_projection_and_lost_cursor_still_pause_for_approval(self):
        engine, _, _, batch, decision = self.prepare()
        with mock.patch.object(engine, '_append_event', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.replan_decision(**decision)
        self.assertFalse(engine.replan_decision(**decision))
        graph = fixtures.build_graph(engine, InMemorySaver())
        graph.invoke({'run_dir': str(self.run_dir)}, {'configurable': {'thread_id': 'lost'}, 'recursion_limit': 150})
        self.assertEqual('awaiting-user', engine.load_run()['status'])
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))

    def test_feedback_and_nested_evidence_are_hash_pinned(self):
        engine, _, _, _, decision = self.prepare()
        self.assertTrue(engine.replan_decision(**decision))
        (self.run_dir / 'decision.md').write_text('tampered\n')
        with self.assertRaises(fixtures.artifact_guard.ValidationError):
            engine.load_run()

    def test_other_worker_blockers_are_not_erased(self):
        engine, _, _, _, decision = self.prepare(extra_blocker=True)
        before = engine.run_path.read_bytes()
        with self.assertRaisesRegex(fixtures.WorkflowError, 'one accepted blocked'):
            engine.replan_decision(**decision)
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_pending_sqlite_cursor_is_refused_before_projection_changes(self):
        import orchestrator
        engine, graph, config, _, decision = self.prepare()
        args = orchestrator.build_parser().parse_args([
            'replan-decision', str(self.run_dir), '--review-sha256', decision['review_sha256'],
            '--blocker-id', decision['blocker_id'], '--text', decision['text'],
            '--blocker-evidence-sha256', decision['blocker_evidence_sha256'],
        ])
        before = engine.run_path.read_bytes()
        with mock.patch.object(orchestrator, '_open_graph') as opened, mock.patch.object(graph, 'get_state') as state:
            opened.return_value.__enter__.return_value = (engine, graph, config)
            state.return_value.next = ('implement',)
            with self.assertRaisesRegex(fixtures.WorkflowError, 'settled graph cursor'):
                orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
        self.assertEqual(before, engine.run_path.read_bytes())

    def test_cli_returns_control_to_graph(self):
        import orchestrator
        engine, graph, config, batch, decision = self.prepare()
        args = orchestrator.build_parser().parse_args([
            'replan-decision', str(self.run_dir), '--review-sha256', decision['review_sha256'],
            '--blocker-id', decision['blocker_id'], '--text', decision['text'], '--context', decision['context'],
            '--blocker-evidence-sha256', decision['blocker_evidence_sha256'],
        ])
        with mock.patch.object(orchestrator, '_open_graph') as opened:
            opened.return_value.__enter__.return_value = (engine, graph, config)
            result = orchestrator._invoke(args, {'run_dir': str(self.run_dir)})
        self.assertEqual('awaiting-user', result['status'])
        self.assertEqual(2, sum(a['stage'] == 'implement' for a in batch.assignments))
