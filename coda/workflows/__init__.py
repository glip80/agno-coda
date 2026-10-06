"""
Coda Development Workflows
==========================

Agno `Workflow`s that encode Coda's development processes. Each workflow is a
composable graph of steps built from the patterns in the Agno workflow examples:
`Parallel`, `Router`, `Loop`, `Condition`, and human-in-the-loop reviews.

    daily_digest_workflow      — parallel repo activity → Slack digest
    pr_review_workflow         — parallel review → synthesize → approve → post
    issue_triage_workflow      — triage Jira tasks → router(quiet | summary) → Slack
    feature_planning_workflow  — code + Confluence context → plan → loop refine → approve → Jira tasks
    ci_health_workflow         — parallel health checks → router(alert | report)

Register them on AgentOS by importing `CODA_WORKFLOWS`.
"""

from typing import Any

from coda.workflows.ci_health import ci_health_workflow
from coda.workflows.daily_digest import daily_digest_workflow
from coda.workflows.feature_planning import feature_planning_workflow
from coda.workflows.issue_triage import issue_triage_workflow
from coda.workflows.pr_review import pr_review_workflow

# Typed as `list[Any]` so it can be passed to `AgentOS(workflows=...)`, whose
# parameter is an invariant `list[Workflow | RemoteWorkflow | WorkflowFactory]`.
CODA_WORKFLOWS: list[Any] = [
    daily_digest_workflow,
    pr_review_workflow,
    issue_triage_workflow,
    feature_planning_workflow,
    ci_health_workflow,
]

__all__ = [
    "CODA_WORKFLOWS",
    "ci_health_workflow",
    "daily_digest_workflow",
    "feature_planning_workflow",
    "issue_triage_workflow",
    "pr_review_workflow",
]
