"""GitLab OAuth login + pipeline-webhook auto-setup.

Inert until configured: `is_configured()` is False unless GITLAB_OAUTH_CLIENT_ID
and GITLAB_OAUTH_CLIENT_SECRET are set, so the app runs fine with placeholders.

Async functions accept an optional httpx client (for tests/connection reuse);
when omitted they create and close their own.
"""
from __future__ import annotations

import os
from urllib.parse import quote, urlencode

import httpx

PROVIDER = "gitlab"
DEFAULT_SCOPE = "read_user api"  # api is needed to create hooks + post MR notes
_TIMEOUT = 15.0


def _cfg() -> dict[str, str]:
    return {
        "client_id": os.environ.get("GITLAB_OAUTH_CLIENT_ID", ""),
        "client_secret": os.environ.get("GITLAB_OAUTH_CLIENT_SECRET", ""),
        "base": os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/"),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["client_id"] and c["client_secret"])


def authorize_url(redirect_uri: str, state: str, scope: str = DEFAULT_SCOPE) -> str:
    """Build the GitLab authorization URL to redirect the user to."""
    c = _cfg()
    q = urlencode(
        {
            "client_id": c["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": scope,
        }
    )
    return f"{c['base']}/oauth/authorize?{q}"


async def exchange_code(
    code: str, redirect_uri: str, *, client: httpx.AsyncClient | None = None
) -> dict:
    """Exchange an authorization code for an access token."""
    c = _cfg()
    own = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.post(
            f"{c['base']}/oauth/token",
            data={
                "client_id": c["client_id"],
                "client_secret": c["client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if own:
            await client.aclose()


async def get_user(token: str, *, client: httpx.AsyncClient | None = None) -> dict:
    """Fetch the authenticated user's GitLab profile."""
    c = _cfg()
    own = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.get(
            f"{c['base']}/api/v4/user",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if own:
            await client.aclose()


async def create_pipeline_webhook(
    token: str,
    repo_full_path: str,
    webhook_url: str,
    secret: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Create a pipeline-events webhook on the project (URL-encoded path as :id)."""
    c = _cfg()
    project_id = quote(repo_full_path, safe="")
    own = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.post(
            f"{c['base']}/api/v4/projects/{project_id}/hooks",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "url": webhook_url,
                "token": secret,
                "pipeline_events": True,
                "push_events": False,
                "enable_ssl_verification": True,
            },
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if own:
            await client.aclose()
