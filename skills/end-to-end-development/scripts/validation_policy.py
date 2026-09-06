"""Pure local validation policy. Observations never become passes through policy.

The engine selects current, hash-verified artifacts. This module only evaluates
those observations against canonical definitions and authorized exclusions.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


def protected(check: Mapping[str, Any]) -> bool:
    return check['purpose'] != 'supplemental' or check['migration_capable']


def exclusions(amendments: Iterable[dict[str, Any]], *, repo_id: str,
               basis: dict[str, Any]) -> dict[str, dict[str, str]]:
    active: dict[str, dict[str, str]] = {}
    for amendment in amendments:
        if (amendment['kind'] != 'validation-exception' or amendment['repo_id'] != repo_id
                or amendment['basis'] != basis):
            continue
        for check_id in amendment['check_ids']:
            if amendment['decision'] == 'exclude':
                active[check_id] = amendment['reference']
            else:
                active.pop(check_id, None)
    return active


def effective_checks(checks: Iterable[dict[str, Any]],
                     excluded: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [check for check in checks if check['id'] not in excluded or protected(check)]


def evaluate(checks: Iterable[dict[str, Any]], records: Iterable[dict[str, Any]],
             excluded: Mapping[str, Any]) -> dict[str, Any]:
    observations = {record['id']: record for record in records}
    rows, missing, blocking = [], [], []
    for check in checks:
        check_id = check['id']
        record = observations.get(check_id)
        if record and (record['command'] != check['command'] or record['cwd'] != check['cwd']):
            record = None
        exception = excluded.get(check_id) if not protected(check) else None
        disposition = 'excluded' if exception else ('advisory' if check['gate'] == 'advisory' else 'required')
        result = record['result'] if record else 'not-run'
        if not exception:
            if record is None or result == 'not-run':
                missing.append(check_id)
            if check['gate'] == 'blocking' and result != 'pass':
                blocking.append(check_id)
        rows.append({
            'id': check_id, 'command': check['command'], 'cwd': check['cwd'],
            'purpose': check['purpose'], 'gate': check['gate'],
            'migration_capable': check['migration_capable'], 'rationale': check['rationale'],
            'disposition': disposition, 'result': result, 'exception': exception,
            'summary': record['summary'] if record else ('Not run — explicitly excluded.' if exception else 'No current execution evidence.'),
            'log_path': record.get('log_path') if record else None,
        })
    return {'satisfied': not blocking and not missing, 'coverage_complete': not missing,
            'blocking_ids': blocking, 'missing_ids': missing, 'checks': rows,
            'warnings': [row for row in rows if row['disposition'] == 'excluded'
                         or (row['disposition'] == 'advisory' and row['result'] != 'pass')]}
