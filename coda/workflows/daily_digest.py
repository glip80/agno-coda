"""
Daily Digest Workflow
=====================

An Agno `Workflow` that gathers repository activity in parallel and posts a
morning digest to Slack.

Patterns demonstrated (see the Agno workflow examples):
    - `Parallel`   — fetch merged PRs, open PRs, new issues, and stale issues
                     concurrently instead of one after another.
    - `Steps`      — a deterministic format step turns the four result sets
                     into a Slack-ready message.
    - function executors — each step is a plain function over `StepInput`.

Reuses the GitHub fetchers from `tasks.daily_digest` so the scheduled task and
the workflow always report the same numbers.

Trigger:
    from coda.workflows import daily_digest_workflow
    daily_digest_workflow.print_response("agno", stream=True)
"""

from __future__ import annotations

from typing import Any

from agno.workflow import Parallel, Step, StepInput, StepOutput, Workflow

from coda.workflows.common import (
    WORKFLOW_DB,
    configured_repos,
    last_output,
    now_utc,
    parse_owner_repo,
    post_to_slack,
    repo_choices,
    repo_name,
    resolve_repo,
    text_input,
)
from tasks.daily_digest import fetch_merged_prs, fetch_new_issues, fetch_open_prs, fetch_stale_issues

STEP_MERGED = "Merged PRs"
STEP_OPEN = "Open PRs"
STEP_NEW = "New Issues"
STEP_STALE = "Stale Issues"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _target_repos(text: str) -> list[dict[str, Any]]:
    """Repos to digest: the one named in the input, or all configured repos."""
    repos = configured_repos()
    if not repos:
        return []
    named = resolve_repo(text) if text.strip() else None
    if named is not None and len(repos) > 1:
        return [named]
    return repos


def _rows_for(repos: list[dict[str, Any]], fetch: Any) -> list[dict[str, Any]]:
    """Run a fetch function per repo, skipping entries without a URL."""
    rows: list[dict[str, Any]] = []
    for repo in repos:
        url = repo.get("url")
        if not url:
            continue
        rows.append({"repo": repo_name(url), "items": fetch(parse_owner_repo(url))})
    return rows


def _by_repo(rows: Any) -> dict[str, list[dict[str, Any]]]:
    """Turn [{'repo': name, 'items': [...]}] into {name: [...]}."""
    result: dict[str, list[dict[str, Any]]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                result[str(row.get("repo", ""))] = list(row.get("items") or [])
    return result


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def fetch_merged_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content=_rows_for(_target_repos(text_input(step_input)), fetch_merged_prs))


def fetch_open_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content=_rows_for(_target_repos(text_input(step_input)), fetch_open_prs))


def fetch_new_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content=_rows_for(_target_repos(text_input(step_input)), fetch_new_issues))


def fetch_stale_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content=_rows_for(_target_repos(text_input(step_input)), fetch_stale_issues))


def format_step(step_input: StepInput) -> StepOutput:
    """Combine the four parallel result sets into one Slack digest."""
    merged = _by_repo(last_output(step_input, STEP_MERGED))
    open_prs = _by_repo(last_output(step_input, STEP_OPEN))
    new_issues = _by_repo(last_output(step_input, STEP_NEW))
    stale = _by_repo(last_output(step_input, STEP_STALE))

    names = list(dict.fromkeys([*merged, *open_prs, *new_issues, *stale]))
    if not names:
        return StepOutput(content=f"No repositories configured (available: {repo_choices()}).")

    blocks: list[str] = []
    for name in names:
        sections: list[str] = []

        if items := merged.get(name):
            lines = [f"• <{pr['url']}|#{pr['number']}> {pr['title']} — @{pr['user']}" for pr in items]
            sections.append(f":white_check_mark: *Merged* ({len(items)})\n" + "\n".join(lines))

        if items := open_prs.get(name):
            lines = []
            for pr in items:
                age = pr.get("age_days", 0)
                age_str = "today" if age == 0 else f"{age}d"
                lines.append(f"• <{pr['url']}|#{pr['number']}> {pr['title']} — @{pr['user']} ({age_str})")
            sections.append(f":eyes: *Waiting for Review* ({len(items)})\n" + "\n".join(lines))

        if items := new_issues.get(name):
            lines = []
            for issue in items:
                labels = f" [{', '.join(issue['labels'])}]" if issue.get("labels") else ""
                lines.append(f"• <{issue['url']}|#{issue['number']}> {issue['title']}{labels} — @{issue['user']}")
            sections.append(f":new: *New Issues* ({len(items)})\n" + "\n".join(lines))

        if items := stale.get(name):
            lines = [f"• <{i['url']}|#{i['number']}> {i['title']} ({i['days_stale']}d)" for i in items[:10]]
            header = f":hourglass: *Stale* ({len(items)})"
            if len(items) > 10:
                header += f" — showing 10 of {len(items)}"
            sections.append(header + "\n" + "\n".join(lines))

        body = "\n\n".join(sections) if sections else "All quiet — no activity in the last 24h."
        blocks.append(f"*{name}*\n{body}")

    return StepOutput(content="\n\n———\n\n".join(blocks) + f"\n———\n{now_utc()}")


def post_step(step_input: StepInput) -> StepOutput:
    message = str(last_output(step_input, "Format digest") or "")
    post_to_slack(message, "DIGEST_CHANNEL", header="Coda Daily Digest")
    return StepOutput(content=message)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
# Kept as a list so they can be splatted into `Parallel`, whose varargs
# signature the Agno stubs do not model.
_gather_steps: list[Any] = [
    Step(name=STEP_MERGED, executor=fetch_merged_step),
    Step(name=STEP_OPEN, executor=fetch_open_step),
    Step(name=STEP_NEW, executor=fetch_new_step),
    Step(name=STEP_STALE, executor=fetch_stale_step),
]

daily_digest_workflow = Workflow(
    id="coda-daily-digest",
    name="Coda Daily Digest",
    description=(
        "Gather merged PRs, open PRs, new issues, and stale issues across configured repos "
        "in parallel, then post a morning digest to Slack."
    ),
    db=WORKFLOW_DB,
    steps=[
        Parallel(*_gather_steps, name="Gather repo activity"),
        Step(name="Format digest", executor=format_step),
        Step(name="Post digest", executor=post_step),
    ],
    add_session_state_to_context=True,
)
