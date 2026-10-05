"""
Feature Planning Workflow
=========================

An Agno `Workflow` that turns a feature request into a set of GitHub issues:
it gathers code context, drafts a breakdown, refines it in a loop, then files
the issues after human approval.

Patterns demonstrated:
    - agent steps (``Step(agent=planner)``) — the planner receives the previous
                          step's output as its message.
    - `Loop`            — refine the plan until it is marked ready or the
                          iteration budget runs out (``forward_iteration_output``
                          feeds each iteration the previous one).
    - `HumanReview`     — filing issues requires confirmation.
    - session state     — repo and request travel between steps.

Trigger:
    from coda.workflows import feature_planning_workflow
    feature_planning_workflow.print_response("add rate limiting to the API on agno", stream=True)
"""

from __future__ import annotations

from typing import Any

from agno.workflow import Loop, Step, StepInput, StepOutput, Workflow

from coda.agents.explorer import explorer
from coda.agents.planner import planner
from coda.workflows.common import (
    WORKFLOW_DB,
    as_text,
    last_output,
    parse_owner_repo,
    repo_choices,
    repo_name,
    resolve_repo,
    text_input,
)

STEP_CONTEXT = "Gather context"
STEP_DRAFT = "Draft plan"
STEP_REFINE = "Critique and refine"
STEP_CREATE = "Create issues"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def gather_context_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    """Resolve the repo and collect relevant code context for the request."""
    if session_state is None:
        session_state = {}
    request = text_input(step_input)
    repo = resolve_repo(request)
    if repo is None:
        return StepOutput(
            success=False,
            error=f"Could not resolve a repo from '{request}'. Configured: {repo_choices()}.",
            content=f"Which repo? Available: {repo_choices()}",
        )

    url = repo["url"]
    name = repo_name(url)
    session_state["repo"] = name
    session_state["owner_repo"] = parse_owner_repo(url)
    session_state["request"] = request

    prompt = (
        f"Feature request for the '{name}' repo:\n{request}\n\n"
        f"Explore the codebase and gather only the context needed to plan this work: "
        f"the modules, entry points, existing patterns to follow, and constraints. "
        f"Cite `file:line`. Be concise — this feeds a planning step, not a report."
    )
    context = explorer.run(prompt).content or ""
    return StepOutput(content=f"Feature request:\n{request}\n\nRelevant code context:\n{context}")


def refine_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    """One refinement pass over the current plan."""
    if session_state is None:
        session_state = {}
    request = session_state.get("request", "")
    current = as_text(last_output(step_input))
    prompt = (
        f"Here is the current issue breakdown for this feature request:\n{request}\n\n"
        f"---\n{current}\n---\n\n"
        f"Critique it: are the issues independently actionable, correctly ordered, and free of "
        f"overlap or missing dependencies? Tighten titles, scopes, and any code pointers. "
        f"Return the full revised breakdown.\n\n"
        f"End your reply with exactly one status line:\n"
        f"`STATUS: READY` if no further changes are needed, otherwise `STATUS: REVISE`."
    )
    refined = planner.run(prompt).content or ""
    return StepOutput(content=refined)


def plan_ready(outputs: list[StepOutput]) -> bool:
    """Stop looping once the planner marks the plan ready."""
    if not outputs:
        return False
    return "STATUS: READY" in as_text(outputs[-1].content).upper()


def create_issues_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    """File the approved plan as GitHub issues."""
    if session_state is None:
        session_state = {}
    plan = as_text(last_output(step_input))
    owner_repo = session_state.get("owner_repo", "")
    prompt = (
        f"Create GitHub issues for the following approved plan in `{owner_repo}`.\n\n"
        f"{plan}\n\n"
        f"Use the GitHub tools to open one issue per planned item, with a clear title, a body "
        f"containing the scope and code pointers, and appropriate labels. Do not create duplicates. "
        f"Return a short summary of what you created."
    )
    summary = planner.run(prompt).content or ""
    return StepOutput(content=summary)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
feature_planning_workflow = Workflow(
    id="coda-feature-planning",
    name="Coda Feature Planning",
    description=(
        "Turn a feature request into GitHub issues: gather code context, draft a breakdown, "
        "refine it in a loop, then create the issues after human approval."
    ),
    db=WORKFLOW_DB,
    steps=[
        Step(name=STEP_CONTEXT, executor=gather_context_step),
        Step(name=STEP_DRAFT, agent=planner),
        Loop(
            name="Refine plan",
            steps=[Step(name=STEP_REFINE, executor=refine_step)],
            max_iterations=2,
            end_condition=plan_ready,
            forward_iteration_output=True,
        ),
        Step(
            name=STEP_CREATE,
            executor=create_issues_step,
            requires_confirmation=True,
            confirmation_message="Create these GitHub issues? Confirm to file them, reject to stop.",
        ),
    ],
    add_session_state_to_context=True,
)
