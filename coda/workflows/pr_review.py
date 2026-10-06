"""
PR Review Workflow
==================

An Agno `Workflow` that reviews a pull request from three angles in parallel,
synthesises the findings, and — after a human approval gate — posts the review
back to GitHub.

Patterns demonstrated:
    - function executor — fetch PR metadata and diff summary via the GitHub API.
    - `Parallel`        — Explorer reviews correctness, conventions, and
                          security/test coverage concurrently.
    - `HumanReview`     — the posting step requires confirmation before it runs.
    - session state     — repo, PR number, and the drafted review travel between
                          steps without re-parsing the input.

Trigger:
    from coda.workflows import pr_review_workflow
    pr_review_workflow.print_response("review PR #42 on agno", stream=True)
"""

from __future__ import annotations

import re
from typing import Any

from agno.workflow import Parallel, Step, StepInput, StepOutput, Workflow

from coda.agents.explorer import explorer
from coda.workflows.common import (
    WORKFLOW_DB,
    as_text,
    github_get,
    github_post,
    last_output,
    parse_owner_repo,
    repo_choices,
    repo_name,
    resolve_repo,
    text_input,
)

STEP_FETCH = "Fetch PR"
STEP_CORRECTNESS = "Correctness & Architecture"
STEP_CONVENTIONS = "Conventions & Learnings"
STEP_SECURITY = "Security & Tests"
STEP_SYNTHESIZE = "Synthesize review"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def fetch_pr_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    """Resolve the repo + PR number and pull a review brief from GitHub."""
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

    numbers = re.findall(r"\d+", text)
    pr_number = numbers[0] if numbers else None
    if pr_number is None:
        return StepOutput(
            success=False,
            error="No PR number found in the input.",
            content="Tell me which PR to review, e.g. 'review PR #42 on agno'.",
        )

    url = repo["url"]
    owner_repo = parse_owner_repo(url)
    pr = github_get(f"/repos/{owner_repo}/pulls/{pr_number}")
    if not isinstance(pr, dict):
        return StepOutput(
            success=False,
            error=f"GitHub returned no PR #{pr_number} for {owner_repo}.",
            content=f"Could not fetch PR #{pr_number} from {owner_repo}.",
        )

    files = github_get(f"/repos/{owner_repo}/pulls/{pr_number}/files", {"per_page": 100}) or []
    file_lines: list[str] = []
    if isinstance(files, list):
        for item in files[:60]:
            file_lines.append(f"- {item.get('filename')} (+{item.get('additions', 0)}/-{item.get('deletions', 0)})")

    brief = (
        f"PR #{pr_number} in {owner_repo}\n"
        f"Title: {pr.get('title')}\n"
        f"Author: {(pr.get('user') or {}).get('login')}\n"
        f"Base: {pr.get('base', {}).get('ref')} ← Head: {pr.get('head', {}).get('ref')}\n"
        f"URL: {pr.get('html_url')}\n"
        f"Description:\n{as_text(pr.get('body'))[:1500]}\n\n"
        f"Changed files ({len(files) if isinstance(files, list) else 0}):\n" + "\n".join(file_lines)
    )

    # Carry resolved context to later steps.
    session_state["repo"] = repo_name(url)
    session_state["owner_repo"] = owner_repo
    session_state["pr_number"] = pr_number
    session_state["pr_url"] = pr.get("html_url", "")
    session_state["pr_title"] = pr.get("title", "")
    session_state["brief"] = brief
    return StepOutput(content=brief)


def _explorer_review(session_state: dict[str, Any], focus: str) -> StepOutput:
    brief = session_state.get("brief", "")
    repo = session_state.get("repo", "the repo")
    prompt = (
        f"You are reviewing a pull request in the '{repo}' repository.\n"
        f"Focus ONLY on: {focus}.\n\n"
        f"Use the PR number and repo below to fetch the diff and read changed files for context. "
        f"Cite `file:line` for every claim. Be specific and concise — bullets, no preamble.\n\n"
        f"{brief}"
    )
    response = explorer.run(prompt)
    return StepOutput(content=response.content or "")


def correctness_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    return _explorer_review(
        session_state or {},
        "correctness and architecture — logic errors, edge cases, broken invariants, design concerns",
    )


def conventions_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    return _explorer_review(
        session_state or {},
        "conventions and learned patterns — naming, structure, error handling, and consistency with the rest of the repo",
    )


def security_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    return _explorer_review(
        session_state or {},
        "security and tests — injection, secrets, unsafe input handling, and whether the change is adequately tested",
    )


def synthesize_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    if session_state is None:
        session_state = {}
    sections = {
        "Correctness & Architecture": last_output(step_input, STEP_CORRECTNESS),
        "Conventions": last_output(step_input, STEP_CONVENTIONS),
        "Security & Tests": last_output(step_input, STEP_SECURITY),
    }
    parts: list[str] = []
    for title, body in sections.items():
        parts.append(f"### {title}\n{as_text(body).strip() or 'No findings.'}")

    review = "## Coda PR Review\n\n" + "\n\n".join(parts)
    session_state["review"] = review
    return StepOutput(content=review)


def post_review_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    if session_state is None:
        session_state = {}
    owner_repo = session_state.get("owner_repo")
    pr_number = session_state.get("pr_number")
    review = session_state.get("review", "")
    if not owner_repo or not pr_number or not review:
        return StepOutput(success=False, error="Missing PR context to post the review.", content="Nothing to post.")

    result = github_post(f"/repos/{owner_repo}/issues/{pr_number}/comments", {"body": review})
    if result is None:
        return StepOutput(success=False, error="GitHub rejected the review comment.", content=review)

    return StepOutput(content=f"Posted review to {owner_repo}#{pr_number}.")


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
# Kept as a list so they can be splatted into `Parallel`, whose varargs
# signature the Agno stubs do not model.
_review_steps: list[Any] = [
    Step(name=STEP_CORRECTNESS, executor=correctness_step),
    Step(name=STEP_CONVENTIONS, executor=conventions_step),
    Step(name=STEP_SECURITY, executor=security_step),
]

pr_review_workflow = Workflow(
    id="coda-pr-review",
    name="Coda PR Review",
    description=(
        "Fetch a pull request, review it in parallel for correctness, conventions, and "
        "security/tests, synthesise the findings, then post the review after human approval."
    ),
    db=WORKFLOW_DB,
    steps=[
        Step(name=STEP_FETCH, executor=fetch_pr_step),
        Parallel(*_review_steps, name="Review in parallel"),
        Step(name=STEP_SYNTHESIZE, executor=synthesize_step),
        Step(
            name="Post review",
            executor=post_review_step,
            requires_confirmation=True,
            confirmation_message="Post this review to the pull request? Confirm to publish, reject to discard.",
        ),
    ],
    add_session_state_to_context=True,
)
