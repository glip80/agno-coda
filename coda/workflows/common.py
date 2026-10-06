"""
Coda Workflow Helpers
=====================

Shared plumbing for the development workflows in `coda.workflows`.

Every workflow step executor is a plain function that receives a `StepInput`
and returns a `StepOutput` (or a value Agno wraps into one). These helpers keep
the individual workflows focused on their logic — resolving repos, talking to
GitHub, reading upstream step outputs, and posting to Slack.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from os import getenv
from typing import Any

import httpx
from agno.workflow import StepInput, StepOutput
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from db import get_postgres_db
from tasks.sync_repos import load_repos_config

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# One shared workflow database, reused by every workflow so they do not each
# construct a redundant PostgresDb instance.
WORKFLOW_DB = get_postgres_db()


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------
def repo_name(url: str) -> str:
    """Derive the short repo name from a GitHub URL."""
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def parse_owner_repo(url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL."""
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url.rstrip("/"))
    if not match:
        raise ValueError(f"Cannot parse GitHub owner/repo from: {url}")
    return match.group(1)


def configured_repos() -> list[dict[str, Any]]:
    """Return the repositories configured in repos.yaml."""
    return load_repos_config()


def resolve_repo(text: str | None) -> dict[str, Any] | None:
    """Resolve a repo from free text.

    Matches a configured repo whose name or `owner/repo` appears in `text`.
    Falls back to the first configured repo when the text names nothing and
    only one repo exists.
    """
    repos = configured_repos()
    if not repos:
        return None

    haystack = (text or "").lower()
    for repo in repos:
        url = repo.get("url")
        if not url:
            continue
        name = repo_name(url).lower()
        owner_repo = parse_owner_repo(url).lower()
        if name in haystack or owner_repo in haystack:
            return repo

    if len(repos) == 1:
        return repos[0]
    return None


def repo_choices() -> str:
    """Human-readable list of configured repos for prompts and errors."""
    names = [repo_name(r["url"]) for r in configured_repos() if r.get("url")]
    return ", ".join(names) if names else "none configured"


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
def github_headers() -> dict[str, str]:
    """Headers for GitHub REST calls, authenticated when a token is set."""
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    token = getenv("GITHUB_ACCESS_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET a GitHub REST path. Returns parsed JSON, or None on failure."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{GITHUB_API}{path}", headers=github_headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        log.warning("GitHub GET %s failed: %s", path, exc)
        return None


def github_post(path: str, payload: dict[str, Any]) -> Any:
    """POST JSON to a GitHub REST path. Returns parsed JSON, or None on failure."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{GITHUB_API}{path}", headers=github_headers(), json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        log.warning("GitHub POST %s failed: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Step input/output
# ---------------------------------------------------------------------------
def last_output(step_input: StepInput, name: str | None = None) -> Any:
    """Read a previous step's content.

    Prefers a named step when `name` is given, otherwise the most recent one.
    """
    outputs = step_input.previous_step_outputs
    if outputs:
        if name and name in outputs:
            return outputs[name].content
        return list(outputs.values())[-1].content
    return step_input.previous_step_content


def as_text(value: Any) -> str:
    """Normalise a step value into prompt-ready text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


def text_input(step_input: StepInput) -> str:
    """Return the workflow input as text."""
    return as_text(step_input.input)


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------
def post_to_slack(text: str, channel_env: str, header: str = "") -> bool:
    """Post a markdown message to the channel named by an env var.

    Never raises: logs and returns False when Slack is not configured or the
    post fails, so a scheduled workflow cannot crash on a missing channel.
    """
    token = getenv("SLACK_TOKEN", "")
    channel = getenv(channel_env, "")
    message = f"*{header}*\n\n{text}" if header else text

    if not token or not channel:
        log.warning("SLACK_TOKEN or %s not set — printing to stdout", channel_env)
        print(message)
        return False

    try:
        WebClient(token=token).chat_postMessage(channel=channel, text=message, mrkdwn=True)
        log.info("Posted to Slack channel %s", channel)
        return True
    except SlackApiError as exc:
        error = exc.response.get("error", "unknown")
        if error == "channel_not_found":
            log.error("Channel '%s' not found. Use the channel ID (C0XXXXXXX), not the name.", channel)
        elif error == "not_in_channel":
            log.error("Bot not in channel '%s'. Run /invite @Coda first.", channel)
        elif error == "invalid_auth":
            log.error("SLACK_TOKEN is invalid or expired.")
        else:
            log.error("Slack API error: %s", error)
        log.info("Falling back to stdout:")
        print(message)
        return False


def slack_step(text: str, channel_env: str, header: str = "") -> StepOutput:
    """Step executor body: post to Slack and echo the message as the step output."""
    post_to_slack(text, channel_env, header)
    return StepOutput(content=text)
