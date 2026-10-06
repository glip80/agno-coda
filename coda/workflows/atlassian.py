"""
Atlassian Agents
================

Workflow-scoped agents that operate on Jira and Confluence through the
`mcp-atlassian` MCP server. They are intentionally separate from the
GitHub-based agents in `coda.agents` so the interactive team is unaffected.

These agents expose MCP tools, which only connect on the async path — always
run them with `arun`.
"""

from __future__ import annotations

from agno.agent import Agent

from coda.settings import MODEL, agent_db
from coda.tools.atlassian import atlassian_mcp

# ---------------------------------------------------------------------------
# Jira triager — categorise and label tasks without closing them
# ---------------------------------------------------------------------------
jira_triager = Agent(
    id="jira-triager",
    name="Jira Triager",
    role="Triage Jira tasks: categorise, label, and comment with code-backed analysis",
    model=MODEL,
    db=agent_db,
    tools=[atlassian_mcp(name="jira-triager")],
    instructions="""\
You triage Jira tasks. You may read tasks, add labels, transition status,
and comment — but you NEVER delete or close a task during an automated run.

For each task:
1. Read its full description and comments.
2. Categorise it (Bug, Enhancement, Question, Chore, Slop).
3. Apply appropriate labels.
4. Comment only when it adds value (code pointers, duplicate links, repro steps).

Return a concise Slack-ready summary grouped by category, with one bullet per
task: `• <task-url|KEY summary> — action taken`. End with a final line
`Scanned N tasks`.

If no tasks match the request, reply with exactly `NO_TASKS` and nothing else.
""",
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Jira planner — turn an approved plan into Jira tasks
# ---------------------------------------------------------------------------
jira_planner = Agent(
    id="jira-planner",
    name="Jira Planner",
    role="Create Jira tasks from an approved plan",
    model=MODEL,
    db=agent_db,
    tools=[atlassian_mcp(name="jira-planner")],
    instructions="""\
You create Jira tasks from an approved plan. Use the Jira tools to open one
task per planned item, with a clear summary, a description containing scope
and code pointers, and appropriate labels. Never create duplicates — search
for existing tasks first. Return a short summary of the tasks you created,
with their keys.
""",
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Confluence researcher — read-only knowledge source
# ---------------------------------------------------------------------------
confluence_researcher = Agent(
    id="confluence-researcher",
    name="Confluence Researcher",
    role="Search Confluence for documentation relevant to a request",
    model=MODEL,
    db=agent_db,
    tools=[atlassian_mcp(name="confluence-researcher")],
    instructions="""\
You search Confluence for pages relevant to a request. Return the most useful
pages as a short list: title, link, and one line on why it matters. Read-only —
never create or edit pages. If nothing relevant is found, say so plainly.
""",
    add_datetime_to_context=True,
    markdown=True,
)
