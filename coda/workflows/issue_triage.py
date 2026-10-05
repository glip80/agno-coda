"""
Issue Triage Workflow
=====================

An Agno `Workflow` that fetches recent GitHub issues, runs the Triager agent to
categorise and label them, and routes the outcome to Slack.

Patterns demonstrated:
    - `Router`          — a deterministic selector chooses between a quiet report
                          (nothing new) and a full triage branch based on the
                          previous step's output.
    - `Steps` container — the triage branch bundles triage + posting as one
                          sequential choice.
    - function executors reuse the exact triage prompt the scheduled task uses,
                          so interactive and automated runs never diverge.

Trigger:
    from coda.workflows import issue_triage_workflow
    issue_triage_workflow.print_response("triage agno", stream=True)
"""

from __future__ import annotations

from typing import Any

from agno.workflow import Router, Step, StepInput, StepOutput, Steps, Workflow

from coda.workflows.common import (
    WORKFLOW_DB,
    as_text,
    last_output,
    now_utc,
    parse_owner_repo,
    post_to_slack,
    repo_choices,
    repo_name,
    resolve_repo,
    text_input,
)
from tasks.review_issues import fetch_recent_issues, triage_issues

STEP_FETCH = "Fetch issues"
CHOICE_QUIET = "Quiet report"
CHOICE_TRIAGE = "Triage issues"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def fetch_issues_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    """Fetch recent open issues for the resolved repo."""
    if session_state is None:
        session_state = {}
    text = text_input(step_input)
    repo = resolve_repo(text)
    if repo is None:
        return StepOutput(
            success=False,
            error=f"Could not resolve a repo from '{text}'. Configured: {repo_choices()}.",
            content=f"Which repo? Available: {repo_choices()}",
        )

    url = repo["url"]
    issues = fetch_recent_issues(url)
    session_state["repo"] = repo_name(url)
    session_state["owner_repo"] = parse_owner_repo(url)
    session_state["issues"] = issues

    if not issues:
        return StepOutput(content="")

    lines = [
        f"- #{i['number']}: {i['title']} (by @{i['user']}, labels: {', '.join(i['labels']) or 'none'})" for i in issues
    ]
    return StepOutput(content="\n".join(lines))


def quiet_step(step_input: StepInput) -> StepOutput:
    message = f"No new issues in the last 24h. Nothing to triage.\n———\n{now_utc()}"
    post_to_slack(message, "TRIAGE_CHANNEL", header="Coda Issue Triage")
    return StepOutput(content=message)


def triage_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    session_state = session_state or {}
    issues = session_state.get("issues") or []
    owner_repo = session_state.get("owner_repo", "")
    if not issues:
        return quiet_step(step_input)
    summary = triage_issues(issues, owner_repo)
    return StepOutput(content=summary)


def post_triage_step(step_input: StepInput) -> StepOutput:
    """Post the triage branch's summary (the most recent step output) to Slack."""
    summary = as_text(last_output(step_input))
    header = f"Coda Issue Triage — {now_utc()}"
    post_to_slack(summary, "TRIAGE_CHANNEL", header=header)
    return StepOutput(content=summary)


def triage_selector(step_input: StepInput) -> list[Any]:
    """Route to triage only when the fetch step found issues."""
    fetched = as_text(last_output(step_input, STEP_FETCH)).strip()
    return [_QUIET_STEP] if not fetched else [_TRIAGE_BRANCH]


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
_QUIET_STEP = Step(name=CHOICE_QUIET, executor=quiet_step)
_TRIAGE_BRANCH = Steps(
    name=CHOICE_TRIAGE,
    steps=[
        Step(name="Triage", executor=triage_step),
        Step(name="Post triage", executor=post_triage_step),
    ],
)

issue_triage_workflow = Workflow(
    id="coda-issue-triage",
    name="Coda Issue Triage",
    description=(
        "Fetch recent issues, triage and label them with the Triager agent, then route "
        "the result to Slack — quiet when there is nothing new, a full summary otherwise."
    ),
    db=WORKFLOW_DB,
    steps=[
        Step(name=STEP_FETCH, executor=fetch_issues_step),
        Router(
            name="Route by activity",
            choices=[_QUIET_STEP, _TRIAGE_BRANCH],
            selector=triage_selector,
        ),
    ],
    add_session_state_to_context=True,
)
