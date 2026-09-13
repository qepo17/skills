from __future__ import annotations

import json
import unittest
from unittest import mock

import test_worker_supervisor as fixtures
import worker_supervisor


class WriterHandleTests(unittest.TestCase):
    setUp = fixtures.WorkerCommandTests.setUp
    tearDown = fixtures.WorkerCommandTests.tearDown
    request = fixtures.WorkerCommandTests.request

    def supervisor(self):
        return worker_supervisor.WorkerSupervisor(self.run_dir,
            worker_supervisor.ExecutionContext('herdr', 'pi', 'test', {}))

    def backend(self, agent):
        closed = False
        def query(command):
            nonlocal closed
            if command[1:3] == ['agent', 'list']:
                return {'result': {'agents': [] if closed else [agent]}}
            if command[1:3] == ['workspace', 'list']:
                return {'result': {'workspaces': [] if closed else [{'label': 'test-worker', 'workspace_id': 'w-original', 'pane_count': 1, 'tab_count': 1}]}}
            if command[1:3] == ['agent', 'get']:
                return {'result': {'agent': dict(agent)}}
            raise AssertionError(command)
        def cleanup(handle, *, settled):
            nonlocal closed
            self.assertTrue(settled)
            self.assertEqual('w-original', handle.details['workspace_id'])
            closed = True
            return 'complete', None
        return query, cleanup

    def identity(self):
        return {'name': 'test-worker', 'agent_status': 'done', 'cwd': str(self.root),
                'workspace_id': 'w-original', 'pane_id': 'w-original:p1',
                'agent_session': {'value': 'original-session'}}

    def test_cleanup_uses_live_exact_original_identity_not_reused_record(self):
        supervisor = self.supervisor()
        record = self.run_dir / 'supervisor' / supervisor.record_name('validate:api:one')
        record.parent.mkdir()
        before = b'{"handle_id":"test-worker","details":{"workspace_id":"wrong-reused-workspace"}}\n'
        record.write_bytes(before)
        query, cleanup = self.backend(self.identity())
        with mock.patch.object(supervisor, '_checked_json', side_effect=query), \
             mock.patch.object(supervisor, '_cleanup', side_effect=cleanup) as close:
            proof = supervisor.close_settled_incident_workers({'test-worker': self.identity()},
                        cwd=str(self.root), known_names={'test-worker'})
        self.assertEqual([], proof['after']['result']['agents'])
        close.assert_called_once()
        self.assertEqual(before, record.read_bytes())

    def test_restored_idle_original_requires_pinned_finished_turn_proof(self):
        for proven in (False, True):
            with self.subTest(proven=proven):
                supervisor = self.supervisor()
                query, cleanup = self.backend({**self.identity(), 'agent_status': 'idle'})
                expected = self.identity()
                if proven:
                    expected['finished_binding_sha256'] = 'f' * 64
                with mock.patch.object(supervisor, '_checked_json', side_effect=query), \
                     mock.patch.object(supervisor, '_cleanup', side_effect=cleanup) as close:
                    if proven:
                        supervisor.close_settled_incident_workers({'test-worker': expected},
                            cwd=str(self.root), known_names={'test-worker'})
                        close.assert_called_once()
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'mismatched'):
                            supervisor.close_settled_incident_workers({'test-worker': expected},
                                cwd=str(self.root), known_names={'test-worker'})
                        close.assert_not_called()

    def test_working_unknown_or_mismatched_handles_never_close(self):
        for changes in ({'agent_status': 'working'}, {'name': 'someone-else'},
                        {'workspace_id': 'w-other'}, {'pane_id': 'w-other:p1'}, {'cwd': '/unrelated'},
                        {'agent_session': None}, {'agent_session': {'value': 'consistently-substituted-session'}}):
            with self.subTest(changes=changes):
                supervisor = self.supervisor()
                query, _ = self.backend({**self.identity(), **changes})
                with mock.patch.object(supervisor, '_checked_json', side_effect=query), \
                     mock.patch.object(supervisor, '_cleanup') as close:
                    with self.assertRaisesRegex(RuntimeError, 'mismatched'):
                        supervisor.close_settled_incident_workers({'test-worker': self.identity()},
                            cwd=str(self.root), known_names={'test-worker'})
                    close.assert_not_called()

    def test_identity_change_between_preflight_and_close_aborts(self):
        supervisor = self.supervisor()
        query, _ = self.backend(self.identity())
        def changed(command):
            response = query(command)
            if command[1:3] == ['agent', 'get']:
                response['result']['agent']['agent_session'] = {'value': 'replacement-session'}
            return response
        with mock.patch.object(supervisor, '_checked_json', side_effect=changed), \
             mock.patch.object(supervisor, '_cleanup') as close:
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                supervisor.close_settled_incident_workers({'test-worker': self.identity()},
                    cwd=str(self.root), known_names={'test-worker'})
            close.assert_not_called()

    def test_shared_workspace_or_unknown_pane_never_closes(self):
        for shared in ('agent', 'pane', 'tab', 'unknown-count'):
            with self.subTest(shared=shared):
                supervisor = self.supervisor()
                query, _ = self.backend(self.identity())
                def response(command):
                    result = query(command)
                    if shared == 'agent' and command[1:3] == ['agent', 'list']:
                        result['result']['agents'].append({'name': 'unrelated', 'cwd': '/unrelated',
                            'workspace_id': 'w-original', 'pane_id': 'w-original:p2', 'agent_status': 'working'})
                    if command[1:3] == ['workspace', 'list']:
                        workspace = result['result']['workspaces'][0]
                        if shared in {'pane', 'tab'}:
                            workspace[shared + '_count'] = 2
                        elif shared == 'unknown-count':
                            workspace.pop('pane_count')
                    return result
                with mock.patch.object(supervisor, '_checked_json', side_effect=response), \
                     mock.patch.object(supervisor, '_cleanup') as close:
                    with self.assertRaisesRegex(RuntimeError, 'shared|exclusive'):
                        supervisor.close_settled_incident_workers({'test-worker': self.identity()},
                            cwd=str(self.root), known_names={'test-worker'})
                    close.assert_not_called()

    def test_late_herdr_done_probe_cleans_only_matching_retained_pane(self):
        for pane, closes in [('w-original:p1', True), ('w-other:p1', False)]:
            with self.subTest(pane=pane):
                supervisor = self.supervisor()
                request = self.request()
                paths = supervisor._worker_paths(request)
                record = supervisor._starting_record(request, paths)
                record.update(status='timeout', cleanup_status='retained', handle_id='test-worker',
                              details={'workspace_id': 'w-original', 'pane_id': 'w-original:p1'})
                paths['record'].parent.mkdir(parents=True, exist_ok=True)
                paths['record'].write_text(json.dumps(record))
                response = {'result': {'agent': {'agent_status': 'done', 'pane_id': pane}}}
                with mock.patch.object(supervisor, '_checked_json', return_value=response), \
                     mock.patch.object(supervisor, '_cleanup', return_value=('complete', None)) as close:
                    outcomes = supervisor.retry_cleanups()
                    self.assertEqual(closes, bool(outcomes))
                    self.assertEqual(int(closes), close.call_count)
