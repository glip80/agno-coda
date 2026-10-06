"""
Issue Triage Workflow
=====================

An Agno `Workflow` that triages Jira tasks with the Jira Triager agent and
routes the outcome to Slack.

Patterns demonstrated:
    - async function executor — MCP tools connect only on the async path, so the
                          triage step is ``async`` and runs the agent with
                          ``arun``.
    - `Router`          — a deterministic selector chooses between a quiet report
                          (nothing to triage) and a full summary branch.
    - `Steps` container — the summary branch bundles posting.

The triager reads, labels, and comments on Jira tasks but never closes them in
an automated run.

Trigger:
    from coda.workflows import issue_triage_workflow
    issue_triage_workflow.print_response("triage the open tasks", stream=True)
"""

from __future__ import annotations

from os import getenv
from typing import Any

from agno.workflow import Router, Step, StepInput, StepOutput, Workflow

from coda.workflows.atlassian import jira_triager
from coda.workflows.common import WORKFLOW_DB, as_text, last_output, now_utc, post_to_slack, text_input

STEP_TRIAGE = "Triage Jira tasks"
CHOICE_QUIET = "Quiet report"
CHOICE_SUMMARY = "Post summary"
NO_TASKS = "NO_TASKS"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
async def triage_jira_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    """Run the Jira Triager agent over recent tasks via the MCP server."""
    if session_state is None:
        session_state = {}
    request = text_input(step_input).strip()
    project = getenv("JIRA_PROJECT_KEY", "")
    scope = request or (f"the {project} project" if project else "all open tasks")

    prompt = (
        f"Triage the most recent open Jira tasks in {scope}.\n\n"
        f"Read each task, categorise and label it, and comment only where it adds value. "
        f"Do NOT close or delete any task. Finish with a Slack-ready summary."
    )
    response = await jira_triager.arun(prompt)
    summary = (response.content or "").strip()
    session_state["summary"] = summary
    return StepOutput(content=summary)


def quiet_step(step_input: StepInput) -> StepOutput:
    message = f"No Jira tasks to triage.\n———\n{now_utc()}"
    post_to_slack(message, "TRIAGE_CHANNEL", header="Coda Jira Triage")
    return StepOutput(content=message)


def post_summary_step(step_input: StepInput) -> StepOutput:
    summary = as_text(last_output(step_input, STEP_TRIAGE))
    post_to_slack(summary, "TRIAGE_CHANNEL", header=f"Coda Jira Triage — {now_utc()}")
    return StepOutput(content=summary)


def triage_selector(step_input: StepInput) -> list[Any]:
    """Route to the summary branch only when the triager found something."""
    summary = as_text(last_output(step_input, STEP_TRIAGE)).strip()
    return [_QUIET_STEP] if not summary or summary.upper() == NO_TASKS else [_SUMMARY_STEP]


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
_QUIET_STEP = Step(name=CHOICE_QUIET, executor=quiet_step)
_SUMMARY_STEP = Step(name=CHOICE_SUMMARY, executor=post_summary_step)

issue_triage_workflow = Workflow(
    id="coda-issue-triage",
    name="Coda Jira Triage",
    description=(
        "Triage recent Jira tasks with the Jira Triager agent (label + comment, never close), "
        "then route the result to Slack."
    ),
    db=WORKFLOW_DB,
    steps=[
        Step(name=STEP_TRIAGE, executor=triage_jira_step),
        Router(name="Route by activity", choices=[_QUIET_STEP, _SUMMARY_STEP], selector=triage_selector),
    ],
    add_session_state_to_context=True,
)
