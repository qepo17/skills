"""Opt-in recovery of producer-edge ordering and exact OpenAPI bundle scope.

Historical contracts/assignments stay immutable. This interpretation is explicit
user authority, never inferred as a new default for other runs.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import artifact_guard
import workflow_tools

CHECK_STAGES = {'implement', 'validate', 'validation-fix', 'fix-1', 'fix-2', 'pipeline-fix', 'integrate'}
READ_STAGES = CHECK_STAGES | {'review-1', 'review-2'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def read_reference(ref):
    path = artifact_guard.hashed_file_reference(ref, '$.generation_recovery')
    return json.loads(Path(path).read_text())


def validate_record(record):
    if (record.get('schema_version') != 1 or record.get('artifact_kind') != 'generation-recovery'
            or digest(record.get('request')) != record.get('request_sha256')
            or record.get('authorization_text', '').strip().lower() not in {'authorized', 'approved'}):
        artifact_guard.fail('$.generation_recovery', 'invalid recovery identity or authority')
    request = record['request']
    expected = {'run_id', 'expected_run_sha256', 'blocker_id', 'blocker_evidence', 'authorization',
                'contract', 'review', 'producer_repo_id', 'read_consumers', 'write_consumers',
                'generated_path', 'dependency_direction', 'repository_states'}
    if (set(request) != expected or request['run_id'] != record.get('run_id')
            or request['generated_path'] != 'dist/openapi.yaml'
            or request['dependency_direction'] != 'producer-to-consumer'):
        artifact_guard.fail('$.generation_recovery', 'unsupported recovery scope')
    for key in ('blocker_evidence', 'authorization', 'contract', 'review'):
        artifact_guard.hashed_file_reference(request[key], '$.generation_recovery.' + key)
    producer = artifact_guard.repo_id(request['producer_repo_id'], '$.producer_repo_id')
    for key in ('read_consumers', 'write_consumers'):
        values = request[key]
        if (not isinstance(values, list) or not values or values != sorted(set(values))
                or producer in values or not all(isinstance(v, str) for v in values)):
            artifact_guard.fail('$.generation_recovery', 'invalid consumer scope')
    if not set(request['write_consumers']) <= set(request['read_consumers']):
        artifact_guard.fail('$.generation_recovery', 'writers must be scoped readers')
    before = read_reference(record['run_before'])
    if (reference(record['run_before']['path'])['sha256'] != request['expected_run_sha256']
            or before.get('generation_recovery') or before['run_id'] != record['run_id']
            or set(request['repository_states']) != set(before['repositories'])
            or not set(request['read_consumers']) < set(before['repositories'])
            or producer not in before['repositories']
            or before['contract_path'] != request['contract']['path']
            or before['contract_sha256'] != request['contract']['sha256']
            or before['plan_review']['review_path'] != request['review']['path']
            or before['plan_review']['review_sha256'] != request['review']['sha256']):
        artifact_guard.fail('$.generation_recovery', 'recovery differs from preserved approved run')
    return request, before


def load(run):
    if not run.get('generation_recovery'):
        return None
    record = read_reference(run['generation_recovery'])
    request, before = validate_record(record)
    if (record['run_id'] != run['run_id'] or run['plan_review'] != before['plan_review']
            or run['contract_path'] != request['contract']['path']
            or run['contract_sha256'] != request['contract']['sha256']):
        artifact_guard.fail('$.generation_recovery', 'recovery approval/contract changed')
    return request


def output_path(run, request):
    root = Path(run['repositories'][request['producer_repo_id']]['worktree'])
    output = root / request['generated_path']
    if output.resolve() != output or any(p.is_symlink() for p in (root, output.parent, output)):
        artifact_guard.fail('$.generated_file_writes', 'generated output may not traverse symlinks')
    return output


def ordered_repositories(engine, repo_ids):
    from workflow_engine import WorkflowError
    dependencies = engine._contract_dependencies()
    order = []
    while len(order) < len(dependencies):
        ready = sorted(k for k, deps in dependencies.items() if k not in order and deps <= set(order))
        if not ready:
            raise WorkflowError('cyclic generation dependencies')
        order.extend(ready)
    return [name for name in order if name in repo_ids]


def verified_writers(engine, repo_id):
    from workflow_engine import WorkflowError
    order = {a['output_artifact']: i for i, a in enumerate(engine.load_agents()['agents'])}
    writers = engine._artifacts(repo_id=repo_id, stage='implement', kind='result')
    for path, result, assignment in writers:
        if (str(path) not in order
                or reference(result['assignment_path'])['sha256'] != result['assignment_sha256']):
            raise WorkflowError('historical writer assignment or worker evidence changed')
        artifact_guard.validate_assignment(assignment)
    return sorted(writers, key=lambda item: order[str(item[0])])


def verify_replacement(engine, assignment):
    from workflow_engine import WorkflowError
    run = engine.load_run()
    refs = (run['repositories'][assignment['repo_id']]['accepted_artifacts']
            if assignment.get('repo_id') else run['accepted_artifacts'])
    if assignment['action_id'] in refs:
        result = read_reference(refs[assignment['action_id']])
        if reference(result['assignment_path'])['sha256'] != result['assignment_sha256']:
            raise WorkflowError('accepted assignment changed before replacement')


def recover(engine, request, *, request_sha256, text):
    from workflow_engine import RunLock, WorkflowError, _git
    if digest(request) != request_sha256:
        raise WorkflowError('reviewed recovery request hash changed')
    if text.strip().lower() not in {'authorized', 'approved'}:
        raise WorkflowError('requires exact affirmative user authorization and a pinned scope record')
    with RunLock(engine.run_dir):
        run = engine.load_run()
        if run.get('generation_recovery'):
            prior = read_reference(run['generation_recovery'])
            if prior['request_sha256'] != request_sha256 or prior['authorization_text'] != text:
                raise WorkflowError('conflicting one-shot generation recovery')
            return 'already-applied'
        if (run['status'] != 'blocked' or run['phase'] != 'implement' or run['profile'] != 'full'
                or run.get('validation_policy_version') != 1 or run['next_actions'] or len(run['blockers']) != 1
                or reference(engine.run_path)['sha256'] != request['expected_run_sha256']
                or run['plan_review']['status'] != 'approved' or run['plan_review']['approval_source'] != 'user'):
            raise WorkflowError('requires the exact reviewed settled user-approved implementation blocker')
        blocker = run['blockers'][0]
        if (blocker['id'] != request['blocker_id'] or blocker['kind'] != 'permission'
                or blocker['evidence_path'] != request['blocker_evidence']['path']
                or 'dist/openapi.yaml' not in blocker['summary']):
            raise WorkflowError('not the generated-bundle permission incident')
        if (any(r['active_writer'] for r in run['repositories'].values())
                or any(a['status'] not in {'closed', 'failed'} or a.get('cleanup_status') != 'complete'
                       for a in engine.load_agents()['agents'])):
            raise WorkflowError('requires closed cleaned workers and no writer leases')
        for path in (engine.run_dir / 'supervisor').glob('worker-*.json'):
            handle = json.loads(path.read_text())
            if handle.get('status') not in {'settled', 'failed'} or handle.get('cleanup_status') != 'complete':
                raise WorkflowError('requires settled cleaned supervisor handles')
        if any(run.get(k) for k in ('pending_check_remediations', 'pending_validation_refresh', 'pending_delivery_refresh')):
            raise WorkflowError('unrelated pending work prevents recovery')
        writers_by_repo = {name: verified_writers(engine, name) for name in run['repositories']}
        matches = [(p, a, assignment) for repo in run['repositories']
                   for p, a, assignment in writers_by_repo[repo]
                   if a['status'] == 'blocked' and len(a['blockers']) == 1
                   and all(a['blockers'][0][k] == blocker[k] for k in ('kind', 'summary', 'evidence_path', 'required_action'))]
        if len(matches) != 1:
            raise WorkflowError('requires one matching accepted implementation blocker')
        blocked_path, result, assignment = matches[0]
        repo = run['repositories'][assignment['repo_id']]
        if (result['changed_files'] or assignment['repo_id'] not in request['write_consumers']
                or assignment['attempt'] > run['retry_limits']['worker_replacements_per_stage']
                or not engine._assignment_pins(assignment, Path(repo['plan_path']), repo['plan_sha256'])
                or assignment.get('plan_review') != request['review']):
            raise WorkflowError('requires a no-change blocked writer with approved plan and remaining replacement budget')
        for name, repository in run['repositories'].items():
            state = workflow_tools.repository_state(Path(repository['worktree']))
            writers = writers_by_repo[name]
            if writers and writers[-1][1]['status'] != 'complete' and writers[-1][0] != blocked_path:
                raise WorkflowError('unrelated unfinished writer prevents recovery')
            if name == assignment['repo_id']:
                if not writers or writers[-1][0] != blocked_path:
                    raise WorkflowError('blocker is not the latest consumer writer')
                writers = writers[:-1]
            if writers:
                latest = writers[-1][1]
                if latest['status'] != 'complete':
                    raise WorkflowError('no completed predecessor proves the blocked packet made no changes')
                expected_head, expected_tree = latest['git']['head'], latest['tree_fingerprint']
                expected_status = Path(latest['git']['status_short_path']).read_text().strip()
            else:
                plan = engine._current_plan(name)[1]
                if reference(plan['assignment_path'])['sha256'] != plan['assignment_sha256']:
                    raise WorkflowError('historical planning assignment changed')
                expected_head = repository['baseline']
                expected_tree = json.loads(Path(plan['assignment_path']).read_text())['input_tree_fingerprint']
                expected_status = Path(repository['initial_status_path']).read_text().strip()
            if (state != request['repository_states'][name] or state['branch'] != repository['branch']
                    or state['head'] != expected_head or state['fingerprint'] != expected_tree
                    or _git(Path(repository['worktree']), 'status', '--short').strip() != expected_status
                    or _git(Path(repository['worktree']), 'diff', '--cached', '--name-only').strip()):
                raise WorkflowError('stale repository/Git evidence: ' + name)
        contract = read_reference(request['contract'])
        if (not contract['dependencies'] or any(not d['reason'].startswith('Producer-to-consumer edge:')
                                               for d in contract['dependencies'])
                or any(d['to_repo_id'] == request['producer_repo_id'] for d in contract['dependencies'])
                or not set(request['read_consumers']) <= {d['to_repo_id'] for d in contract['dependencies']
                                                          if d['from_repo_id'] == request['producer_repo_id']}):
            raise WorkflowError('contract does not explicitly describe the authorized producer-first edges')
        output_path(run, request)
        producer = Path(run['repositories'][request['producer_repo_id']]['worktree'])
        if (_git(producer, 'ls-files', '--', request['generated_path']).strip()
                or not _git(producer, 'check-ignore', '--', request['generated_path']).strip()):
            raise WorkflowError('generated output must be ignored and untracked')
        # Snapshot bytes, not a reserialization: request pins the original projection.
        before_path = engine.run_dir / 'generation-recovery-run-before.json'
        if before_path.exists() and before_path.read_bytes() != engine.run_path.read_bytes():
            raise WorkflowError('conflicting preserved run snapshot')
        before_ref = {'path': str(before_path), 'sha256': request['expected_run_sha256']}
        record = dict(schema_version=1, artifact_kind='generation-recovery', run_id=run['run_id'],
            request=request, request_sha256=request_sha256, authorization_text=text, run_before=before_ref)
        # Reject scope/evidence before creating any recovery files.
        for key in ('blocker_evidence', 'authorization', 'contract', 'review'):
            artifact_guard.hashed_file_reference(request[key], '$.' + key)
        if request['generated_path'] != 'dist/openapi.yaml' or request['dependency_direction'] != 'producer-to-consumer':
            raise WorkflowError('unsupported recovery scope')
        if not before_path.exists():
            temporary = before_path.with_name('.' + before_path.name + '.tmp')
            temporary.write_bytes(engine.run_path.read_bytes())
            os.replace(temporary, before_path)
        validate_record(record)
        path = engine.run_dir / 'generation-recovery.json'
        if path.exists():
            if json.loads(path.read_text()) != record:
                raise WorkflowError('conflicting immutable recovery intent')
        else:
            workflow_tools.atomic_write_json(path, record)
        run['generation_recovery'] = reference(path)
        run['status'], run['blockers'] = 'working', []
        for repository in run['repositories'].values():
            repository['status'] = 'pending'
        engine._save_run(run)
    engine._append_event('resumed', reason='recover-generation-scope', artifact=str(path), next_action='implement')
    return 'applied'


def decorate(engine, assignment):
    run = engine.load_run()
    request = load(run)
    if not request or assignment['stage'] not in READ_STAGES or assignment.get('execution_mode') == 'artifact-repair':
        return
    consumer = assignment['repo_id']
    if consumer not in request['read_consumers'] and not (consumer is None and assignment['stage'] == 'integrate'):
        return
    producer_id = request['producer_repo_id']
    producer = run['repositories'][producer_id]
    scoped = {r['repo_id']: r for r in assignment['repositories']}
    scoped[producer_id] = dict(repo_id=producer_id, root=producer['root'], worktree=producer['worktree'], access='read')
    assignment['repositories'] = [scoped[k] for k in sorted(scoped)]
    assignment['generation_recovery'] = run['generation_recovery']
    assignment['generation_source_state'] = workflow_tools.repository_state(Path(producer['worktree']))
    refs = {r['path']: r for r in assignment['input_artifacts']}
    refs[run['generation_recovery']['path']] = run['generation_recovery']
    upstream = engine._contract_dependencies().get(consumer, set()) | {producer_id}
    for repo_id in sorted(upstream):
        for p, _, _ in engine._artifacts(repo_id=repo_id, kind='result'):
            refs[str(p)] = reference(p)
    assignment['input_artifacts'] = [refs[k] for k in sorted(refs)]
    if assignment['stage'] in CHECK_STAGES and (consumer in request['write_consumers'] or consumer is None):
        assignment['generated_file_writes'] = [str(output_path(run, request))]
    assignment['instructions'] = list(dict.fromkeys(assignment['instructions'] + [
        'The generation recovery grants API source reads and only the listed generated_file_writes, even in check-only stages. '
        'It does not grant other producer file/Git writes or sandbox changes. Use accepted upstream artifacts; never hand-edit generated files.']))


def validate_assignment(assignment):
    if 'generation_recovery' not in assignment:
        if 'generated_file_writes' in assignment or 'generation_source_state' in assignment:
            artifact_guard.fail('$.generated_file_writes', 'requires pinned recovery authority')
        return
    record = read_reference(assignment['generation_recovery'])
    request, before = validate_record(record)
    source = before['repositories'][request['producer_repo_id']]
    expected = dict(repo_id=request['producer_repo_id'], root=source['root'], worktree=source['worktree'], access='read')
    if (assignment['run_id'] != record['run_id'] or assignment['stage'] not in READ_STAGES
            or expected not in assignment['repositories'] or assignment['generation_recovery'] not in assignment['input_artifacts']
            or not isinstance(assignment.get('generation_source_state'), dict)
            or assignment['repo_id'] not in request['read_consumers'] and not (assignment['repo_id'] is None and assignment['stage'] == 'integrate')):
        artifact_guard.fail('$.generation_recovery', 'invalid assignment authority')
    if 'generated_file_writes' in assignment:
        if (assignment['stage'] not in CHECK_STAGES or assignment.get('execution_mode') in {'artifact-repair', 'packet-verification'}
                or assignment['repo_id'] not in request['write_consumers'] and assignment['repo_id'] is not None
                or assignment['generated_file_writes'] != [str(output_path(before, request))]):
            artifact_guard.fail('$.generated_file_writes', 'only the authorized generated output is writable')


def verify_source(assignment):
    if 'generation_recovery' not in assignment:
        return
    validate_assignment(assignment)
    request, before = validate_record(read_reference(assignment['generation_recovery']))
    tree = Path(before['repositories'][request['producer_repo_id']]['worktree'])
    if workflow_tools.repository_state(tree) != assignment['generation_source_state']:
        artifact_guard.fail('$.generation_source_state', 'consumer changed or read stale producer source/Git state')
