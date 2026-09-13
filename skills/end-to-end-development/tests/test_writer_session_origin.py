from __future__ import annotations

import json
import unittest

import test_worker_supervisor as fixtures
import writer_incident


class SessionOriginTests(unittest.TestCase):
    setUp = fixtures.WorkerCommandTests.setUp
    tearDown = fixtures.WorkerCommandTests.tearDown

    def fixture(self, *, cwd=None, prompt=None, timestamp='2026-09-12T15:01:00Z'):
        assignment = self.root / 'assignment.json'
        assignment.write_text(json.dumps({'cwd': str(self.root)}))
        session_path = self.root / 'session.jsonl'
        entries = [{'type': 'session', 'id': 'original-session', 'cwd': cwd or str(self.root), 'timestamp': timestamp},
                   {'type': 'message', 'message': {'role': 'user', 'content': [
                       {'type': 'text', 'text': prompt or f'Execute immutable assignment: {assignment}'}]}}]
        session_path.write_text(''.join(json.dumps(e) + '\n' for e in entries))
        session = {'agent': 'pi', 'kind': 'path', 'source': 'herdr:pi', 'value': str(session_path)}
        timeout = {'started_at': '2026-09-12T15:00:00Z', 'ended_at': '2026-09-12T16:00:00Z'}
        return session, assignment, timeout

    def test_original_launch_binding_is_stable_after_session_appends(self):
        session, assignment, timeout = self.fixture()
        binding = writer_incident.session_launch_binding(session, assignment, timeout)
        with (self.root / 'session.jsonl').open('a') as handle:
            handle.write(json.dumps({'type': 'message', 'message': {'role': 'assistant', 'content': 'private later activity'}}) + '\n')
        self.assertEqual(binding, writer_incident.session_launch_binding(session, assignment, timeout))
        self.assertNotIn('private later activity', json.dumps(binding))
        self.assertEqual(str(assignment), binding['assignment_path'])

    def test_unrelated_or_replacement_sessions_cannot_prove_original_identity(self):
        for options in ({'cwd': '/unrelated'}, {'prompt': 'Do a different task'},
                        {'timestamp': '2026-09-12T16:30:00Z'}, {'timestamp': '2026-09-12T14:30:00Z'}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    writer_incident.session_launch_binding(*self.fixture(**options))

    def test_finished_turn_binding_rejects_initial_idle_pending_tools_and_reused_session(self):
        session, assignment, timeout = self.fixture()
        path = self.root / 'session.jsonl'
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            writer_incident.session_finished_binding(session)
        initial = path.read_text()
        finished = {'type': 'message', 'timestamp': '2026-09-12T17:00:00Z',
                    'message': {'role': 'assistant', 'stopReason': 'stop',
                                'content': [{'type': 'text', 'text': 'Original task finished.'}]}}
        path.write_text(initial + json.dumps(finished) + '\n')
        binding = writer_incident.session_finished_binding(session)
        self.assertEqual(1, binding['user_message_count'])
        self.assertNotIn('Original task finished.', json.dumps(binding))
        with path.open('a') as handle:
            handle.write(json.dumps({'type': 'custom', 'data': 'restored session metadata'}) + '\n')
        self.assertEqual(binding, writer_incident.session_finished_binding(session))
        finished['message']['stopReason'] = 'toolUse'
        path.write_text(initial + json.dumps(finished) + '\n')
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            writer_incident.session_finished_binding(session)
        finished['message']['stopReason'] = 'stop'
        extra = {'type': 'message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'A different task'}]}}
        path.write_text(initial + json.dumps(extra) + '\n' + json.dumps(finished) + '\n')
        with self.assertRaisesRegex(ValueError, 'reused'):
            writer_incident.session_finished_binding(session)

    def test_missing_session_and_symlink_origin_are_refused(self):
        session, assignment, timeout = self.fixture()
        with self.assertRaises(ValueError):
            writer_incident.session_launch_binding({}, assignment, timeout)
        link = self.root / 'session-link.jsonl'
        link.symlink_to(session['value'])
        with self.assertRaisesRegex(ValueError, 'regular local file'):
            writer_incident.session_launch_binding(dict(session, value=str(link)), assignment, timeout)
