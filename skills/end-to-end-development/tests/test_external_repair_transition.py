from __future__ import annotations

import unittest

import test_workflow_engine as fixtures
import external_repair
import test_external_repair as recovery_tests


class SourceTransitionTests(unittest.TestCase):
    setUp = fixtures.WorkflowEngineTests.setUp
    tearDown = fixtures.WorkflowEngineTests.tearDown
    git = recovery_tests.ExternalRepairTests.git
    tree = recovery_tests.ExternalRepairTests.tree

    def prepare(self):
        base = [f'line {i}\n' for i in range(30)]
        (self.worktree / 'module.py').write_text(''.join(base))
        (self.worktree / 'test_fixture.py').write_text('obsolete = True\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'foundation')
        old = self.git('rev-parse', 'HEAD')
        local = list(base)
        local[1] = 'local feature work\n'
        (self.worktree / 'module.py').write_text(''.join(local))
        before_tree = self.tree()
        self.git('checkout', '-qb', 'upstream', old, cwd=self.repo)
        upstream = list(base)
        upstream[25] = 'upstream fix\n'
        (self.repo / 'module.py').write_text(''.join(upstream))
        self.git('add', '.', cwd=self.repo)
        self.git('commit', '-qm', 'upstream fix', cwd=self.repo)
        new = self.git('rev-parse', 'HEAD', cwd=self.repo)
        self.git('update-ref', 'refs/remotes/origin/main', new)
        self.git('reset', '--mixed', new)
        local[25] = upstream[25]
        (self.worktree / 'module.py').write_text(''.join(local))
        (self.worktree / 'test_fixture.py').write_text('obsolete = False\n')
        self.transition = {'before_head': old, 'before_tree': before_tree, 'after_head': new,
                           'after_tree': self.tree(), 'target_ref': 'refs/remotes/origin/main',
                           'repair_paths': ['test_fixture.py']}
        self.original = {'git': {'head': old}, 'tree_fingerprint': external_repair.tree_fingerprint(before_tree),
                         'changed_files': ['module.py']}
        self.repository = {'baseline': old, 'branch': self.git('branch', '--show-current')}

    def verify(self):
        return external_repair.validate_transition(self.worktree, self.transition, self.original, self.repository,
                                                   fixtures.workflow_tools.repository_state(self.worktree))

    def test_conflict_free_three_way_base_merge_preserves_task_content(self):
        self.prepare()
        before_index = self.git('ls-files', '--stage')
        before_head = self.git('rev-parse', 'HEAD')
        self.assertEqual(['module.py', 'test_fixture.py'], self.verify())
        self.assertEqual(before_index, self.git('ls-files', '--stage'))
        self.assertEqual(before_head, self.git('rev-parse', 'HEAD'))

    def test_reviewed_after_tree_does_not_authorize_arbitrary_merge_resolution(self):
        self.prepare()
        (self.worktree / 'module.py').write_text('lost task work\n')
        self.transition['after_tree'] = self.tree()
        with self.assertRaisesRegex(ValueError, 'unauthorized rebase resolution'):
            self.verify()

    def test_remote_target_movement_is_not_freshened(self):
        self.prepare()
        self.git('update-ref', self.transition['target_ref'], self.transition['before_head'])
        with self.assertRaisesRegex(ValueError, 'target moved'):
            self.verify()

    def test_active_git_operation_is_refused(self):
        self.prepare()
        marker = self.worktree / self.git('rev-parse', '--git-path', 'MERGE_HEAD')
        marker.write_text(self.transition['before_head'] + '\n')
        with self.assertRaisesRegex(ValueError, 'settled Git operations'):
            self.verify()

    def test_rewritten_base_commit_is_refused(self):
        self.prepare()
        # Same tree, unrelated parent: a rebase grant is not arbitrary commit replacement.
        new = self.git('commit-tree', self.transition['after_tree'], '-m', 'unrelated history')
        self.git('reset', '--mixed', new)
        self.git('update-ref', self.transition['target_ref'], new)
        self.transition['after_head'] = new
        with self.assertRaisesRegex(ValueError, 'Git inspection failed'):
            self.verify()
