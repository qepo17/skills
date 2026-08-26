#!/usr/bin/env python3
"""Run one headless worker and durably record its exit status."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a worker command is required after --")

    args.stdout.parent.mkdir(parents=True, exist_ok=True)
    args.stderr.parent.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        record = {}
    record.update(
        {
            "handle_id": str(os.getpid()),
            "status": "working",
            "details": {"pid": os.getpid()},
        }
    )
    atomic_write(args.record, record)
    try:
        with args.stdout.open("wb") as stdout, args.stderr.open("wb") as stderr:
            process = subprocess.run(
                command,
                cwd=args.cwd,
                check=False,
                stdout=stdout,
                stderr=stderr,
            )
        exit_code = process.returncode
        error = None
    except OSError as exc:
        exit_code = 127
        error = str(exc)
    atomic_write(
        args.status,
        {
            "schema_version": 1,
            "started_at": started_at,
            "finished_at": utc_now(),
            "exit_code": exit_code,
            "error": error,
        },
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
