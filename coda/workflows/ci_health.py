"""
Release / CI Health Workflow
============================

An Agno `Workflow` that checks the health of a repository's default branch in
parallel, then routes to an alert or a routine report.

Patterns demonstrated:
    - `Parallel` — CI checks, open PRs, and recent commits are gathered at once.
    - `Router`   — a selector reads the composed health verdict and picks the
                   alert branch or the report branch.
    - function executors over the GitHub REST API.

Trigger:
    from coda.workflows import ci_health_workflow
    ci_health_workflow.print_response("agno", stream=True)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agno.workflow import Parallel, Router, Step, StepInput, StepOutput, Workflow

from coda.workflows.common import (
    WORKFLOW_DB,
    as_text,
    github_get,
    last_output,
    now_utc,
    parse_owner_repo,
    post_to_slack,
    repo_choices,
    repo_name,
    resolve_repo,
    text_input,
)

STEP_CI = "CI status"
STEP_PRS = "Open PRs"
STEP_COMMITS = "Recent commits"
STEP_COMPOSE = "Compose health"
CHOICE_ALERT = "Alert"
CHOICE_REPORT = "Report"

FAILING_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required"}


def _context(step_input: StepInput, session_state: dict[str, Any]) -> tuple[str, str] | None:
    """Resolve repo + owner_repo, caching them in session state. None on failure."""
    if session_state.get("owner_repo") and session_state.get("repo"):
        return str(session_state["repo"]), str(session_state["owner_repo"])
    text = text_input(step_input)
    repo = resolve_repo(text)
    if repo is None:
        return None
    url = repo["url"]
    session_state["repo"] = repo_name(url)
    session_state["owner_repo"] = parse_owner_repo(url)
    return repo_name(url), parse_owner_repo(url)


# ---------------------------------------------------------------------------
# Parallel checks
# ---------------------------------------------------------------------------
def ci_status_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    session_state = session_state or {}
    ctx = _context(step_input, session_state)
    if ctx is None:
        return StepOutput(content={"error": f"No repo resolved. Configured: {repo_choices()}."})
    _, owner_repo = ctx

    repo_info = github_get(f"/repos/{owner_repo}") or {}
    branch = repo_info.get("default_branch", "main") if isinstance(repo_info, dict) else "main"
    head = github_get(f"/repos/{owner_repo}/commits/{branch}") or {}
    sha = head.get("sha", "") if isinstance(head, dict) else ""
    message = ((head.get("commit") or {}).get("message") or "").splitlines()[:1] if isinstance(head, dict) else []

    checks: list[dict[str, Any]] = []
    if sha:
        runs = github_get(f"/repos/{owner_repo}/commits/{sha}/check-runs") or {}
        if isinstance(runs, dict):
            checks = list(runs.get("check_runs") or [])

    failing = [c.get("name") for c in checks if (c.get("conclusion") or "") in FAILING_CONCLUSIONS]
    pending = [c.get("name") for c in checks if c.get("status") != "completed"]
    session_state["failing_checks"] = len(failing)

    return StepOutput(
        content={
            "branch": branch,
            "sha": sha[:8],
            "message": message[0] if message else "",
            "checks_total": len(checks),
            "failing": failing,
            "pending": pending,
        }
    )


def open_prs_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    session_state = session_state or {}
    ctx = _context(step_input, session_state)
    if ctx is None:
        return StepOutput(content={"error": "No repo resolved."})
    _, owner_repo = ctx

    prs = github_get(f"/repos/{owner_repo}/pulls", {"state": "open", "sort": "created", "direction": "desc"}) or []
    items: list[dict[str, Any]] = []
    oldest_days = 0
    now = datetime.now(UTC)
    if isinstance(prs, list):
        for pr in prs[:20]:
            if pr.get("draft"):
                continue
            created = pr.get("created_at")
            age = 0
            if created:
                try:
                    age = (now - datetime.fromisoformat(created)).days
                except ValueError:
                    age = 0
            oldest_days = max(oldest_days, age)
            items.append({"number": pr.get("number"), "title": pr.get("title"), "age_days": age})

    count = len(prs) if isinstance(prs, list) else 0
    return StepOutput(content={"count": count, "oldest_days": oldest_days, "items": items})


def recent_commits_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    session_state = session_state or {}
    ctx = _context(step_input, session_state)
    if ctx is None:
        return StepOutput(content={"error": "No repo resolved."})
    _, owner_repo = ctx

    commits = github_get(f"/repos/{owner_repo}/commits", {"per_page": 5}) or []
    items: list[dict[str, Any]] = []
    if isinstance(commits, list):
        for c in commits:
            commit = c.get("commit") or {}
            items.append(
                {
                    "sha": (c.get("sha") or "")[:8],
                    "message": (commit.get("message") or "").splitlines()[:1],
                    "author": ((commit.get("author") or {}).get("name")) or "",
                }
            )
    return StepOutput(content={"items": items})


# ---------------------------------------------------------------------------
# Compose + route + post
# ---------------------------------------------------------------------------
def compose_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    session_state = session_state or {}
    ci = last_output(step_input, STEP_CI)
    prs = last_output(step_input, STEP_PRS)
    commits = last_output(step_input, STEP_COMMITS)

    ci = ci if isinstance(ci, dict) else {}
    prs = prs if isinstance(prs, dict) else {}
    commits = commits if isinstance(commits, dict) else {}

    repo = session_state.get("repo", "repo")
    failing = ci.get("failing") or []
    lines = [
        f"*Repo:* {repo} (branch `{ci.get('branch', 'main')}` @ {ci.get('sha', '?')})",
        f"*Latest commit:* {ci.get('message', 'n/a')}",
        f"*CI checks:* {ci.get('checks_total', 0)} total"
        + (f" — failing: {', '.join(failing)}" if failing else " — all passing")
        + (f" (pending: {', '.join(ci.get('pending') or [])})" if ci.get("pending") else ""),
        f"*Open PRs:* {prs.get('count', 0)}"
        + (f" (oldest {prs.get('oldest_days')}d)" if prs.get("oldest_days") else ""),
    ]
    for item in (prs.get("items") or [])[:5]:
        lines.append(f"  • #{item.get('number')} {item.get('title')} ({item.get('age_days')}d)")
    lines.append("*Recent commits:*")
    for commit in (commits.get("items") or [])[:5]:
        lines.append(f"  • {commit.get('sha')} {commit.get('message')} — {commit.get('author')}")

    status = "STATUS: FAILING" if failing else "STATUS: HEALTHY"
    body = "\n".join(lines)
    session_state["health_body"] = body
    return StepOutput(content=f"{status}\n{body}\n———\n{now_utc()}")


def health_selector(step_input: StepInput) -> list[Any]:
    composed = as_text(last_output(step_input, STEP_COMPOSE))
    return [_ALERT_STEP] if "STATUS: FAILING" in composed else [_REPORT_STEP]


def alert_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    session_state = session_state or {}
    body = str(session_state.get("health_body", ""))
    post_to_slack(f":rotating_light: *CI failing*\n{body}", "DIGEST_CHANNEL", header="Coda CI Health")
    return StepOutput(content=body)


def report_step(step_input: StepInput, session_state: dict[str, Any] | None = None) -> StepOutput:
    session_state = session_state or {}
    body = str(session_state.get("health_body", ""))
    post_to_slack(f":white_check_mark: *Healthy*\n{body}", "DIGEST_CHANNEL", header="Coda CI Health")
    return StepOutput(content=body)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
# Kept as a list so they can be splatted into `Parallel`, whose varargs
# signature the Agno stubs do not model.
_health_steps: list[Any] = [
    Step(name=STEP_CI, executor=ci_status_step),
    Step(name=STEP_PRS, executor=open_prs_step),
    Step(name=STEP_COMMITS, executor=recent_commits_step),
]
_ALERT_STEP = Step(name=CHOICE_ALERT, executor=alert_step)
_REPORT_STEP = Step(name=CHOICE_REPORT, executor=report_step)

ci_health_workflow = Workflow(
    id="coda-ci-health",
    name="Coda CI Health",
    description=(
        "Check a repo's default branch, CI checks, open PRs, and recent commits in parallel, "
        "then alert on failures or post a routine health report."
    ),
    db=WORKFLOW_DB,
    steps=[
        Parallel(*_health_steps, name="Gather health signals"),
        Step(name=STEP_COMPOSE, executor=compose_step),
        Router(
            name="Route by health",
            choices=[_ALERT_STEP, _REPORT_STEP],
            selector=health_selector,
        ),
    ],
    add_session_state_to_context=True,
)
