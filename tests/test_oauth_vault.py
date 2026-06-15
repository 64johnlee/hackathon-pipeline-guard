"""Tests for the token vault, GitLab OAuth provider, and signed-cookie helpers.

No network or GCP creds: the in-memory vault and httpx.MockTransport stand in
for Secret Manager and GitLab.
"""

from __future__ import annotations

import json

import httpx
import pytest

from pipelineguard.providers import gitlab_oauth
from pipelineguard.vault import InMemoryVault, _safe_secret_id, get_vault, reset_vault
from pipelineguard.webhook import _sign_value, _unsign_value


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "GCP_PROJECT",
        "PG_TENANCY_BACKEND",
        "GITLAB_OAUTH_CLIENT_ID",
        "GITLAB_OAUTH_CLIENT_SECRET",
        "GITLAB_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_vault()
    yield
    reset_vault()


class TestVault:
    def test_put_get_delete(self) -> None:
        v = InMemoryVault()
        ref = v.put("gitlab:1", "tok-abc")
        assert v.get(ref) == "tok-abc"
        v.delete(ref)
        assert v.get(ref) == ""

    def test_get_missing_returns_empty(self) -> None:
        assert InMemoryVault().get("mem:nope") == ""

    def test_safe_secret_id_sanitizes(self) -> None:
        sid = _safe_secret_id("gitlab:grp/repo#1")
        assert sid.startswith("pg-token-")
        assert all(c.isalnum() or c in "-_" for c in sid)

    def test_factory_defaults_to_memory(self) -> None:
        reset_vault()
        assert isinstance(get_vault(), InMemoryVault)


class TestSignedCookie:
    def test_roundtrip(self) -> None:
        signed = _sign_value("gitlab:42", "s3cret")
        assert _unsign_value(signed, "s3cret") == "gitlab:42"

    def test_tamper_rejected(self) -> None:
        signed = _sign_value("gitlab:42", "s3cret")
        tampered = signed.replace("gitlab:42", "gitlab:99")
        assert _unsign_value(tampered, "s3cret") is None

    def test_wrong_secret_rejected(self) -> None:
        signed = _sign_value("gitlab:42", "s3cret")
        assert _unsign_value(signed, "other") is None

    def test_malformed_returns_none(self) -> None:
        assert _unsign_value("", "s") is None
        assert _unsign_value("no-dot", "s") is None


class TestOAuthPure:
    def test_not_configured_by_default(self) -> None:
        assert gitlab_oauth.is_configured() is False

    def test_configured_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITLAB_OAUTH_CLIENT_ID", "cid")
        monkeypatch.setenv("GITLAB_OAUTH_CLIENT_SECRET", "csec")
        assert gitlab_oauth.is_configured() is True

    def test_authorize_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITLAB_OAUTH_CLIENT_ID", "cid")
        url = gitlab_oauth.authorize_url("https://app/cb", "xyz", scope="read_user api")
        assert url.startswith("https://gitlab.com/oauth/authorize?")
        assert "client_id=cid" in url
        assert "redirect_uri=https%3A%2F%2Fapp%2Fcb" in url
        assert "state=xyz" in url
        assert "scope=read_user+api" in url


class TestOAuthHTTP:
    async def test_exchange_code(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/oauth/token"
            return httpx.Response(200, json={"access_token": "AT", "token_type": "bearer"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            tok = await gitlab_oauth.exchange_code("code123", "https://app/cb", client=client)
        finally:
            await client.aclose()
        assert tok["access_token"] == "AT"

    async def test_get_user(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v4/user"
            assert request.headers["Authorization"] == "Bearer AT"
            return httpx.Response(200, json={"id": 7, "username": "ada"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            user = await gitlab_oauth.get_user("AT", client=client)
        finally:
            await client.aclose()
        assert user["id"] == 7 and user["username"] == "ada"

    async def test_create_pipeline_webhook(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            # raw_path is the on-the-wire form — GitLab needs the %2F-encoded :id
            captured["path"] = request.url.raw_path.decode()
            captured["body"] = request.read().decode()
            return httpx.Response(201, json={"id": 99, "url": "https://app/webhook/gitlab/tenant"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            hook = await gitlab_oauth.create_pipeline_webhook(
                "AT", "gitlab-org/cli", "https://app/webhook/gitlab/tenant", "wh-secret",
                client=client,
            )
        finally:
            await client.aclose()
        # repo path is URL-encoded as the :id segment
        assert captured["path"] == "/api/v4/projects/gitlab-org%2Fcli/hooks"
        body = json.loads(captured["body"])
        assert body["pipeline_events"] is True
        assert body["push_events"] is False
        assert body["token"] == "wh-secret"
        assert body["url"] == "https://app/webhook/gitlab/tenant"
        assert hook["id"] == 99


class TestConnectIdempotent:
    def test_reconnect_does_not_create_duplicate_webhook(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        from pipelineguard.store import (
            Account,
            Connection,
            get_store,
            make_connection_id,
            reset_store,
        )
        from pipelineguard.vault import get_vault, reset_vault
        from pipelineguard.webhook import _sign_value, make_app

        monkeypatch.setenv("PG_TENANCY_BACKEND", "memory")
        monkeypatch.setenv("SESSION_SECRET", "testsecret")
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example")
        reset_store()
        reset_vault()
        store = get_store()
        ref = get_vault().put("gitlab:1", "tok")
        store.upsert_account(Account(id="gitlab:1", provider="gitlab", token_ref=ref))
        store.upsert_connection(
            Connection(
                id=make_connection_id("gitlab", "grp/repo"),
                account_id="gitlab:1",
                provider="gitlab",
                repo_full_path="grp/repo",
                webhook_secret="s",
                token_secret_ref=ref,
            )
        )

        async def _boom(*a, **k):
            raise AssertionError("create_pipeline_webhook must NOT be called on re-connect")

        monkeypatch.setattr(gitlab_oauth, "create_pipeline_webhook", _boom)

        client = TestClient(make_app(gemini_api_key="t", gitlab_token="t"))
        client.cookies.set("pg_session", _sign_value("gitlab:1", "testsecret"))
        r = client.post("/api/connect", json={"repo": "grp/repo"})
        assert r.status_code == 200 and r.json()["status"] == "already_connected"
        reset_store()
        reset_vault()
