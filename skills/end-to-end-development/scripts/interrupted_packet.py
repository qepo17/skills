"""Opt-in recovery of a lost later-packet intent after a proven local host reboot.

This restores unfinished approved work, never accepts the initializer as a result.
All scheduling, validation, review and delivery still belong to the existing graph.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import artifact_guard
import validation_policy
import worker_supervisor
import workflow_tools
from writer_incident import digest, preserve, reference, validate_history


HOST_CONFIRMATION_QUESTION = (
    "Can you confirm that the interrupted worker ran only on this machine "
    "and was not resumed or moved elsewhere?"
)


def machine_id_sha256() -> str:
    return hashlib.sha256(Path('/etc/machine-id').read_bytes()).hexdigest()


def prove_boots(boots: list[dict[str, Any]], current: str, started_at: str,
               expected: dict[str, str]) -> dict[str, Any]:
    """A missing pane alone is not proof that its verifier descendants stopped."""
    started = int(datetime.fromisoformat(started_at.replace('Z', '+00:00')).timestamp() * 1_000_000)
    original = [boot for boot in boots if boot['first_entry'] <= started <= boot['last_entry']]
    latest = [boot for boot in boots if boot['boot_id'] == current and boot['index'] == 0]
    if (len(original) != 1 or len(latest) != 1 or original[0]['index'] >= 0
            or original[0]['boot_id'] == current
            or original[0]['last_entry'] >= latest[0]['first_entry']
            or expected != {'worker': original[0]['boot_id'], 'current': current}):
        raise ValueError('a different, unambiguous historical host boot must contain the original worker launch')
    return {'worker_boot': original[0], 'current_boot_id': current,
            'current_boot_first_entry': latest[0]['first_entry']}


def inspect_process(process: Path, worktree: Path) -> None:
    unknown = (f'cannot inspect process {process.name}; worker settlement is unknown. '
               'No replacement is authorized. Obtain separately authorized trusted inspection; '
               'do not exclude protected processes or elevate the recovery runner.')
    try:
        if process.stat().st_uid != os.getuid():
            return
        descriptor = os.open(process, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except (FileNotFoundError, ProcessLookupError):
        return
    except OSError as error:
        raise ValueError(unknown) from error
    try:
        # Pin the proc directory: a recycled numeric PID must not stand in for exit evidence.
        if os.fstat(descriptor).st_uid != os.getuid():
            raise ValueError(unknown)
        try:
            cwd = os.readlink('cwd', dir_fd=descriptor)
            # Kernel deleted-path text is ambiguous and may collide with a real outside alias.
            if not os.path.isabs(cwd) or cwd.endswith(' (deleted)'):
                raise ValueError(unknown)
            resolved = Path(cwd).resolve(strict=True)
            if os.readlink('cwd', dir_fd=descriptor) != cwd:
                raise ValueError(unknown)
            if resolved.is_relative_to(worktree):
                raise ValueError('a process is still using the task worktree; settlement is not exclusive')
        except (FileNotFoundError, ProcessLookupError) as error:
            # Missing cwd can mean a deleted directory or an exited main thread, not process exit.
            try:
                os.stat('stat', dir_fd=descriptor)
            except (FileNotFoundError, ProcessLookupError):
                try:
                    process.stat()
                except (FileNotFoundError, ProcessLookupError):
                    return
            raise ValueError(unknown) from error
    except OSError as error:
        raise ValueError(unknown) from error
    finally:
        os.close(descriptor)


def settlement(record: dict[str, Any], expected: dict[str, str], confirmation: dict[str, str]) -> dict[str, Any]:
    # Older supervisor records did not pin their host. Journal timestamps cannot
    # repair that missing identity: explicit local-operator confirmation is required.
    if confirmation['machine_id_sha256'] != machine_id_sha256():
        raise ValueError('the operator-confirmed local host differs from this machine')
    def query(args: list[str]) -> Any:
        result = subprocess.run(args, text=True, capture_output=True, check=True, timeout=15)
        return json.loads(result.stdout)
    current = Path('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-', '')
    proof = prove_boots(query(['journalctl', '--list-boots', '--output=json', '--no-pager']),
                       current, record['started_at'], expected)
    binary = os.environ.get('E2E_HERDR_BINARY', 'herdr')
    agents = query([binary, 'agent', 'list'])
    workspaces = query([binary, 'workspace', 'list'])
    listed = agents.get('result', {}).get('agents')
    spaces = workspaces.get('result', {}).get('workspaces')
    if not isinstance(listed, list) or not isinstance(spaces, list):
        raise ValueError('unrecognized live Herdr inventory')
    if (any(a.get('cwd') == record['cwd'] or a.get('name') == record['agent_name']
            or a.get('pane_id') == record['details']['pane_id'] for a in listed)
            or any(w.get('workspace_id') == record['details']['workspace_id']
                   or w.get('label') == record['agent_name'] for w in spaces)):
        raise ValueError('the original worker or another task session has been restored; settle it first')
    worktree = Path(record['cwd']).resolve()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        inspect_process(process, worktree)
    return {**proof, 'host_confirmation': confirmation, 'herdr_binary': binary,
            'agents': agents, 'workspaces': workspaces}


def recover(engine: Any, request: dict[str, Any], *, request_sha256: str,
            text: str, context: str = '') -> str:
    """Called with both execution/projection locks; never starts a worker here."""
    if not re.fullmatch(r'yes+|approved|authorized', text.strip().lower()) or digest(request) != request_sha256:
        raise ValueError('the exact reviewed request and explicit user recovery authorization are required')
    required = {'run_id', 'repo_id', 'run_sha256', 'agents_sha256', 'assignment', 'worker',
                'output', 'repository_state', 'boot_ids', 'local_host_confirmation'}
    if set(request) != required:
        raise ValueError('interrupted packet request must contain exactly the documented fields')
    confirmation = request['local_host_confirmation']
    if (not isinstance(confirmation, dict) or set(confirmation) != {'authority', 'question', 'text', 'machine_id_sha256'}
            or confirmation['authority'] != 'user' or confirmation['question'] != HOST_CONFIRMATION_QUESTION
            or not isinstance(confirmation['text'], str) or not isinstance(confirmation['machine_id_sha256'], str)
            or not re.fullmatch(r'yes+|confirmed', confirmation['text'].strip().lower())
            or not re.fullmatch(r'[a-f0-9]{64}', confirmation['machine_id_sha256'])):
        raise ValueError('separate explicit local-host confirmation is required; repair approval alone is insufficient')
    run = engine.load_run()
    for ref in run.get('interrupted_packet_recoveries', {}).values():
        if json.loads(Path(ref['path']).read_text())['request_sha256'] == request_sha256:
            return 'already-applied'
    if (reference(engine.run_path)['sha256'] != request['run_sha256']
            or reference(engine.agents_path)['sha256'] != request['agents_sha256']):
        raise ValueError('run or agent history changed after inspection')
    repo_id = request['repo_id']
    if (run['run_id'] != request['run_id'] or set(run['repositories']) != {repo_id}
            or run['status'] != 'blocked' or run['phase'] != 'implement'
            or run['next_actions'] or len(run['blockers']) != 1
            or run.get('validation_policy_version') != 1 or run.get('interrupted_packet_recoveries')
            or (run.get('worker_execution') or {}).get('backend') != 'herdr'
            or (run.get('worker_execution') or {}).get('runtime') != 'pi'
            or (run.get('plan_review') or {}).get('status') != 'approved'):
        raise ValueError('not the single-repository lost implementation intent condition')
    repo = run['repositories'][repo_id]
    if repo['active_writer'] or any(a.get('cleanup_status') != 'complete' for a in engine.load_agents()['agents']):
        raise ValueError('all recorded writers and agent handles must be settled first')
    paths = {}
    for key in ('assignment', 'worker', 'output'):
        path = Path(request[key]['path'])
        if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(engine.run_dir):
            raise ValueError('recovery files must be regular files confined to this run')
        artifact_guard.hashed_file_reference(request[key], f'$.{key}')
        paths[key] = path
    assignment = json.loads(paths['assignment'].read_text())
    artifact_guard.validate_assignment(assignment)
    action_id = assignment['action_id']
    slug = re.sub(r'[^A-Za-z0-9_.-]+', '-', action_id).strip('-').lower()
    if (assignment['run_id'] != run['run_id'] or assignment['repo_id'] != repo_id
            or assignment['stage'] != 'implement' or assignment['attempt'] != 1
            or assignment.get('execution_mode', 'worker') != 'worker'
            or assignment['project_file_access'] != 'write' or assignment['cwd'] != repo['worktree']
            or assignment['baseline'] != repo['baseline'] or action_id in repo['accepted_artifacts']
            or assignment['plan_review'] != {'path': run['plan_review']['review_path'], 'sha256': run['plan_review']['review_sha256']}
            or paths['assignment'] != engine.run_dir / 'assignments' / f'{slug}.json'
            or paths['output'] != Path(assignment['output_artifact'])
            or paths['worker'] != engine.run_dir / 'supervisor' / worker_supervisor.WorkerSupervisor.record_name(action_id)
            or run['retry_limits']['worker_replacements_per_stage'] < assignment['attempt']):
        raise ValueError('only the original, approved and unaccepted packet within its replacement budget is recoverable')
    worker = json.loads(paths['worker'].read_text())
    if (worker.get('action_id') != action_id or worker.get('assignment_path') != str(paths['assignment'])
            or worker.get('cwd') != repo['worktree'] or worker.get('backend') != 'herdr'
            or worker.get('runtime') != 'pi' or worker.get('status') != 'settled'
            or worker.get('cleanup_status') != 'complete'):
        raise ValueError('original supervisor must positively record settled and cleaned identity')
    output = json.loads(paths['output'].read_text())
    if (output.get('assignment_path') != str(paths['assignment'])
            or output.get('assignment_sha256') != request['assignment']['sha256']
            or any(output.get(k) != assignment.get(k) for k in ('run_id', 'repo_id', 'stage', 'attempt', 'packet_id', 'task_ids'))
            or output.get('status') != 'complete' or output.get('summary') != 'TODO'
            or output.get('next_action') is not None
            or any(output.get(k) != [] for k in ('changed_files', 'validations', 'decisions', 'resolutions', 'blockers'))):
        raise ValueError('only an unfinished initialization placeholder is eligible; real results are never replayed')
    plan_path, plan = engine._current_plan(repo_id)
    writers = [item for item in engine._artifacts(repo_id=repo_id, stage='implement', kind='result')
               if engine._assignment_pins(item[2], plan_path, reference(plan_path)['sha256'])]
    completed = {a['packet_id'] for _, a, _ in writers if a.get('status') == 'complete'}
    eligible = sorted(p['id'] for p in plan['work_packets']
                      if p['id'] not in completed and set(p['depends_on']) <= completed)
    if not writers or not eligible or eligible[0] != assignment['packet_id']:
        raise ValueError('the interrupted packet must be the next approved dependency-eligible packet')
    packet = next(p for p in plan['work_packets'] if p['id'] == assignment['packet_id'])
    validation_ids = ({v['id'] for v in plan['validations']} if len(completed) + 1 == len(plan['work_packets'])
                      else {v for t in plan['tasks'] if t['id'] in packet['task_ids'] for v in t['validation_ids']})
    selected = [c for c in engine._effective_checks(repo_id) if c['id'] in validation_ids]
    if (not engine._assignment_pins(assignment, plan_path, reference(plan_path)['sha256'])
            or assignment['task_ids'] != sorted(packet['task_ids'])
            or assignment['validation_ids'] != sorted(c['id'] for c in selected)
            or assignment['validation_commands'] != list(dict.fromkeys(c['command'] for c in selected))):
        raise ValueError('the unfinished intent must retain exact current plan tasks and mandatory checks')
    predecessor, result, previous_assignment = writers[-1]
    ids = set(previous_assignment['validation_ids'])
    checks = [c for c in plan['validations'] if c['id'] in ids]
    blocker = run['blockers'][0]
    if (result.get('status') != 'complete'
            or blocker.get('gate') != {'type': 'local-validation', 'repo_id': repo_id,
                                      'artifact': reference(predecessor), 'check_ids': sorted(ids)}
            or not validation_policy.evaluate(checks, result['validations'], engine._exclusions(repo_id))['satisfied']
            or engine._current_validation(repo_id, require_pass=False, check_ids=ids) is not None):
        raise ValueError('only the stale predecessor gate is recoverable, never a real failing check')
    state = workflow_tools.repository_state(Path(repo['worktree']))
    if state != request['repository_state'] or state['head'] != repo['baseline'] or state['branch'] != repo['branch']:
        raise ValueError('preserved source/HEAD/branch/index changed after inspection')
    replacement_id = re.sub(r':attempt-1$', ':attempt-2', action_id)
    for path in (engine.run_dir / 'assignments').glob('*.json'):
        candidate = json.loads(path.read_text())
        if (candidate['project_file_access'] == 'write' and candidate['action_id'] not in repo['accepted_artifacts']
                and candidate['action_id'] not in {action_id, replacement_id}):
            raise ValueError('another unaccepted writer intent exists')
    for path in (engine.run_dir / 'supervisor').glob('worker-*.json'):
        if json.loads(path.read_text()).get('cleanup_status') != 'complete':
            raise ValueError('another supervisor handle has unproven cleanup')
    history = validate_history(run)
    proof = settlement(worker, request['boot_ids'], confirmation)
    directory = engine.run_dir / 'logs' / 'incidents' / f'interrupted-packet-{request_sha256[:16]}'
    snapshots = [preserve(directory / 'run-before.json', engine.run_path.read_bytes()),
                 preserve(directory / 'agents-before.json', engine.agents_path.read_bytes())]
    resumed = {**assignment, 'instructions': sorted(set(assignment['instructions'] + [artifact_guard.INTERRUPTED_PACKET_INSTRUCTION]))}
    replacement_path = engine._replacement(resumed)
    replacement = json.loads(replacement_path.read_text())
    mutable = {'attempt', 'created_at', 'action_id', 'output_artifact', 'log_dir'}
    old_output = Path(assignment['output_artifact'])
    stem = re.sub(r'-attempt-[0-9]+$', '', old_output.stem)
    expected_output = old_output.with_name(f'{stem}-attempt-2{old_output.suffix}')
    expected_logs = engine.run_dir / 'repos' / repo_id / 'logs' / re.sub(r'[^A-Za-z0-9_.-]+', '-', replacement_id).strip('-').lower()
    if (any(replacement.get(k) != v for k, v in resumed.items() if k not in mutable)
            or replacement['action_id'] != replacement_id or replacement['attempt'] != 2
            or replacement['output_artifact'] != str(expected_output)
            or replacement['log_dir'] != str(expected_logs) or expected_logs.resolve() != expected_logs
            or replacement_path.is_symlink() or expected_output.is_symlink()
            or Path(replacement['output_artifact']).exists()
            or (engine.run_dir / 'supervisor' / worker_supervisor.WorkerSupervisor.record_name(replacement_id)).exists()):
        raise ValueError('replacement must be a new unlaunched intent, never a reused worker')
    # Recheck mutable facts after local system observations and intent creation.
    if (reference(engine.run_path)['sha256'] != request['run_sha256']
            or workflow_tools.repository_state(Path(repo['worktree'])) != state
            or any(reference(paths[k]) != request[k] for k in paths)):
        raise ValueError('recovery context changed before projection')
    record = {'schema_version': 1, 'artifact_kind': 'interrupted-packet-recovery', 'run_id': run['run_id'],
              'request': request, 'request_sha256': request_sha256, 'text': text, 'context': context,
              'created_at': engine.now(), 'replacement': reference(replacement_path),
              'evidence': history + snapshots + [request[k] for k in paths], 'settlement': proof}
    record_path = directory / 'recovery.json'
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        if any(previous.get(k) != v for k, v in record.items() if k not in {'created_at', 'settlement'}):
            raise ValueError('pre-projection recovery intent differs from this request')
        record = previous  # Reuse its immutable observation, after the fresh settlement check above.
    record_ref = preserve(record_path, (json.dumps(record, indent=2) + '\n').encode())
    run.setdefault('interrupted_packet_recoveries', {})[action_id] = record_ref
    run['status'], run['blockers'], repo['status'] = 'working', [], 'pending'
    run['next_actions'] = [{'order': 1, 'action_id': replacement_id, 'phase': 'implement', 'repo_id': repo_id,
                           'attempt': 2, 'input_artifacts': sorted(r['path'] for r in replacement['input_artifacts']),
                           'output_artifact': replacement['output_artifact'], 'status': 'pending',
                           'assignment_path': str(replacement_path)}]
    engine._save_run(run)
    engine._append_event('resumed', reason='recover-interrupted-packet', artifact=record_ref['path'], next_action=replacement_id)
    return 'applied'
