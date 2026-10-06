"""
Atlassian MCP Tools
===================

Builds Agno `MCPTools` bound to the community `mcp-atlassian` MCP server,
exposing Jira and Confluence to the workflows over stdio.

Authentication is passed through to the MCP subprocess via environment
variables (JIRA_URL / JIRA_USERNAME / JIRA_API_TOKEN, plus the Confluence
equivalents). The launch command can be overridden with ATLASSIAN_MCP_COMMAND
(e.g. a self-hosted wrapper) and defaults to `uvx mcp-atlassian`.

Connecting to an MCP server happens on the async path only, so agents using
these tools must be run with `arun`.
"""

from __future__ import annotations

from os import getenv

from agno.tools.mcp import MCPTools

DEFAULT_MCP_COMMAND = "uvx mcp-atlassian"

# Environment variables the `mcp-atlassian` server reads. Passed through to the
# stdio subprocess so the server can authenticate against Jira and Confluence.
_ATLASSIAN_ENV_KEYS = (
    "JIRA_URL",
    "JIRA_USERNAME",
    "JIRA_API_TOKEN",
    "JIRA_PERSONAL_TOKEN",
    "JIRA_SSL_VERIFY",
    "CONFLUENCE_URL",
    "CONFLUENCE_USERNAME",
    "CONFLUENCE_API_TOKEN",
    "CONFLUENCE_PERSONAL_TOKEN",
    "CONFLUENCE_SSL_VERIFY",
    "ATLASSIAN_OAUTH_ACCESS_TOKEN",
)


def atlassian_env() -> dict[str, str]:
    """Collect the Atlassian credentials/URLs present in the environment."""
    return {key: value for key in _ATLASSIAN_ENV_KEYS if (value := getenv(key))}


def atlassian_mcp(*, name: str) -> MCPTools:
    """Create an `MCPTools` instance for the Jira + Confluence MCP server.

    The tool is constructed, not connected: the connection is opened when an
    agent runs it asynchronously.
    """
    return MCPTools(
        command=getenv("ATLASSIAN_MCP_COMMAND") or DEFAULT_MCP_COMMAND,
        env=atlassian_env(),
        name=name,
        timeout_seconds=int(getenv("ATLASSIAN_MCP_TIMEOUT", "30")),
    )
