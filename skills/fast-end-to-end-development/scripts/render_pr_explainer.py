#!/usr/bin/env python3
"""Render a self-contained HTML PR explainer from a small JSON summary."""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a self-contained HTML PR explainer from JSON."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the summary JSON, or '-' to read JSON from stdin.",
    )
    parser.add_argument("--output", required=True, help="Destination HTML path.")
    return parser.parse_args()


def load_summary(input_path: str) -> dict[str, Any]:
    if input_path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(input_path).read_text(encoding="utf-8")

    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("summary JSON must contain an object at the top level")

    for field in ("title", "summary", "repository", "pr_url"):
        if not str(value.get(field, "")).strip():
            raise ValueError(f"summary JSON requires a non-empty '{field}' field")
    return value


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def safe_url(value: Any) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return esc(candidate)
    return "#"


def display(value: Any, fallback: str = "Not recorded") -> str:
    text = str(value or "").strip()
    return esc(text) if text else esc(fallback)


def list_items(values: Any, empty: str = "None recorded.") -> str:
    if not isinstance(values, list) or not values:
        return f'<p class="muted">{esc(empty)}</p>'

    rendered: list[str] = []
    for value in values:
        if isinstance(value, dict):
            label = value.get("id") or value.get("command") or value.get("name")
            detail = value.get("summary") or value.get("notes") or value.get("result")
            if label and detail:
                rendered.append(f"<li><code>{esc(label)}</code> — {esc(detail)}</li>")
            elif label:
                rendered.append(f"<li><code>{esc(label)}</code></li>")
            elif detail:
                rendered.append(f"<li>{esc(detail)}</li>")
            else:
                rendered.append(f"<li><code>{esc(json.dumps(value, sort_keys=True))}</code></li>")
        else:
            rendered.append(f"<li>{esc(value)}</li>")
    return "<ul>" + "".join(rendered) + "</ul>"


def files_list(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return '<p class="muted">No changed files recorded.</p>'
    return "<ul>" + "".join(f"<li><code>{esc(value)}</code></li>" for value in values) + "</ul>"


def checks_table(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return '<p class="muted">No validation commands recorded.</p>'
    rows: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            item = {"command": item}
        status = str(item.get("status") or "unknown")
        exit_code = item.get("exit_code", "—")
        rows.append(
            "<tr>"
            f"<td><code>{esc(item.get('command', ''))}</code></td>"
            f"<td><span class=\"status status-{esc(status.lower())}\">{esc(status)}</span></td>"
            f"<td>{esc(exit_code)}</td>"
            f"<td>{display(item.get('notes') or item.get('result'), '—')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Command</th><th>Status</th><th>Exit</th><th>Notes</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def findings_table(review: Any) -> str:
    if not isinstance(review, dict):
        return '<p class="muted">No review record found.</p>'
    findings = review.get("findings")
    if not isinstance(findings, list) or not findings:
        return '<p class="muted">No findings recorded.</p>'

    rows: list[str] = []
    for item in findings:
        if not isinstance(item, dict):
            item = {"summary": item}
        rows.append(
            "<tr>"
            f"<td><code>{display(item.get('id'), '—')}</code></td>"
            f"<td>{display(item.get('severity'), '—')}</td>"
            f"<td>{display(item.get('disposition') or item.get('status'), '—')}</td>"
            f"<td>{display(item.get('summary') or item.get('evidence'), '—')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>ID</th><th>Severity</th><th>Disposition</th><th>Finding</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def section(title: str, body: str) -> str:
    return f'<section><h2>{esc(title)}</h2>{body}</section>'


def render(summary: dict[str, Any]) -> str:
    generated_at = summary.get("generated_at") or datetime.now(timezone.utc).isoformat()
    pr_url = str(summary.get("pr_url", "")).strip()
    implementation = summary.get("implementation")
    if not isinstance(implementation, dict):
        implementation = {}
    review = summary.get("review")
    if not isinstance(review, dict):
        review = {}
    revision = summary.get("revision")
    if not isinstance(revision, dict):
        revision = {}
    delivery = summary.get("delivery")
    if not isinstance(delivery, dict):
        delivery = {}

    metadata = (
        '<dl class="meta">'
        f"<div><dt>Repository</dt><dd>{display(summary.get('repository'))}</dd></div>"
        f"<div><dt>Branch</dt><dd><code>{display(summary.get('branch'))}</code></dd></div>"
        f"<div><dt>Base</dt><dd><code>{display(summary.get('base'))}</code></dd></div>"
        f"<div><dt>Generated</dt><dd>{display(generated_at)}</dd></div>"
        "</dl>"
    )

    pr_link = f'<a href="{safe_url(pr_url)}">{esc(pr_url)}</a>' if safe_url(pr_url) != "#" else esc(pr_url)
    review_status = review.get("status") or "not recorded"
    revision_status = revision.get("status") or "not recorded"
    delivery_status = delivery.get("status") or "created"
    headline = (
        f'<span class="status status-{esc(str(delivery_status).lower())}">{esc(delivery_status)}</span>'
        f'<span class="status status-{esc(str(review_status).lower())}">review: {esc(review_status)}</span>'
        f'<span class="status status-{esc(str(revision_status).lower())}">revision: {esc(revision_status)}</span>'
    )

    implementation_body = (
        f"<p>{display(summary.get('summary'))}</p>"
        f"<h3>Changed files</h3>{files_list(implementation.get('changed_files'))}"
        f"<h3>Implementation notes</h3>{list_items(implementation.get('notes'))}"
    )
    review_body = (
        f"<p>{display(review.get('summary'), 'One independent review was completed.')}</p>"
        f"<p class=\"muted\">Baseline: <code>{display(review.get('baseline'))}</code> · "
        f"Head: <code>{display(review.get('head'))}</code></p>"
        f"{findings_table(review)}"
    )
    revision_body = (
        f"<p>{display(revision.get('summary'), 'The single revision gate was completed.')}</p>"
        f"<h3>Resolved findings</h3>{list_items(revision.get('resolved_findings'))}"
        f"<h3>Revision notes</h3>{list_items(revision.get('notes'))}"
    )
    delivery_body = (
        f"<p><strong>PR:</strong> {pr_link}</p>"
        f"<p><strong>Commit:</strong> <code>{display(delivery.get('commit'))}</code></p>"
        f"<p><strong>Checks:</strong> {display(delivery.get('checks'), 'Status recorded in delivery artifact.')}</p>"
        f"<p>{display(delivery.get('notes'), '')}</p>"
    )

    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(summary["title"])}</title>
  <style>
    :root {{ color-scheme: light; --ink: #172033; --muted: #667085; --line: #e4e7ec; --wash: #f8fafc; --accent: #635bff; --good: #067647; --warn: #b54708; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #f3f5f9; color: var(--ink); font: 15px/1.55 Inter, ui-sans-serif, system-ui, -apple-system, sans-serif; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 36px 20px 64px; }}
    header, section {{ background: white; border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 4px 16px rgba(16, 24, 40, .04); }}
    header {{ padding: 28px; margin-bottom: 18px; }}
    section {{ padding: 22px 24px; margin: 18px 0; }}
    h1 {{ margin: 0 0 10px; font-size: clamp(25px, 4vw, 38px); letter-spacing: -.03em; }}
    h2 {{ margin: 0 0 13px; font-size: 20px; }}
    h3 {{ margin: 18px 0 7px; font-size: 14px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }}
    p {{ margin: 8px 0; }}
    ul {{ margin: 8px 0 0; padding-left: 22px; }}
    li + li {{ margin-top: 5px; }}
    code {{ background: var(--wash); border-radius: 5px; padding: 2px 5px; font-size: .92em; overflow-wrap: anywhere; }}
    a {{ color: var(--accent); overflow-wrap: anywhere; }}
    .subtitle {{ color: var(--muted); font-size: 17px; max-width: 75ch; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 22px 0 0; }}
    .meta div {{ background: var(--wash); border-radius: 10px; padding: 11px 13px; }}
    dt {{ color: var(--muted); font-size: 12px; }}
    dd {{ margin: 2px 0 0; font-weight: 600; overflow-wrap: anywhere; }}
    .statuses {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 18px; }}
    .status {{ display: inline-block; border-radius: 999px; padding: 3px 9px; background: #eef2ff; color: #3730a3; font-size: 12px; font-weight: 700; }}
    .status-passed, .status-resolved, .status-created, .status-complete {{ background: #ecfdf3; color: var(--good); }}
    .status-advisory, .status-pending, .status-open, .status-unknown {{ background: #fffaeb; color: var(--warn); }}
    .status-blocked, .status-failed, .status-must-fix {{ background: #fef3f2; color: #b42318; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
    .muted {{ color: var(--muted); }}
    footer {{ color: var(--muted); text-align: center; font-size: 12px; padding-top: 24px; }}
    @media (max-width: 680px) {{ table {{ display: block; overflow-x: auto; white-space: nowrap; }} section, header {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{esc(summary["title"])}</h1>
      <p class="subtitle">{esc(summary["summary"])}</p>
      <div class="statuses">{headline}</div>
      {metadata}
    </header>
    {section("Plan", f"<h3>Acceptance criteria</h3>{list_items(summary.get('acceptance_criteria'))}<h3>Implementation slices</h3>{list_items(summary.get('plan'))}<h3>Non-goals</h3>{list_items(summary.get('non_goals'))}")}
    {section("Implementation", implementation_body)}
    {section("Validation", checks_table(summary.get("validation")))}
    {section("Independent review", review_body)}
    {section("Single revision gate", revision_body)}
    {section("Delivery", delivery_body)}
    {section("Risks and remaining notes", f"<h3>Risks</h3>{list_items(summary.get('risks'))}<h3>Notes</h3>{list_items(summary.get('remaining_notes'))}")}
    <footer>Generated by fast-end-to-end-development from sanitized run artifacts.</footer>
  </main>
</body>
</html>
'''


def main() -> int:
    args = parse_args()
    try:
        summary = load_summary(args.input)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render(summary), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
