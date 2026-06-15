"""Tests for account-aware Stripe billing (billing.py) + the wired routes.

The event→plan mapping is pure; the route tests use an in-memory store, a
monkeypatched signature verifier, and a forged signed-session cookie — no Stripe
SDK or network involved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pipelineguard import billing
from pipelineguard.store import Account, get_store, reset_store
from pipelineguard.webhook import _sign_value, make_app


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "GCP_PROJECT",
        "STRIPE_SECRET_KEY",
        "STRIPE_PRICE_ID_PRO",
        "STRIPE_PRICE_ID_TEAMS",
        "STRIPE_WEBHOOK_SECRET",
        "SESSION_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PG_TENANCY_BACKEND", "memory")
    reset_store()
    yield
    reset_store()


class TestPlanChangeFromEvent:
    def test_checkout_completed_via_client_reference_id(self) -> None:
        ev = {
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": "gitlab:1", "customer": "cus_A"}},
        }
        assert billing.plan_change_from_event(ev) == ("gitlab:1", "pro", "cus_A")

    def test_checkout_completed_via_metadata(self) -> None:
        ev = {
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"account_id": "gitlab:2"}}},
        }
        assert billing.plan_change_from_event(ev) == ("gitlab:2", "pro", "")

    def test_subscription_deleted_downgrades(self) -> None:
        ev = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"metadata": {"account_id": "gitlab:3"}, "customer": "cus_C"}},
        }
        assert billing.plan_change_from_event(ev) == ("gitlab:3", "free", "cus_C")

    def test_unrelated_event_is_none(self) -> None:
        assert billing.plan_change_from_event({"type": "invoice.paid", "data": {"object": {}}}) is None

    def test_missing_account_id_is_none(self) -> None:
        ev = {"type": "checkout.session.completed", "data": {"object": {"customer": "cus_X"}}}
        assert billing.plan_change_from_event(ev) is None


class TestIsConfigured:
    def test_not_configured_by_default(self) -> None:
        assert billing.is_configured() is False

    def test_configured_with_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_x")
        assert billing.is_configured() is True

    def test_pro_price_falls_back_to_teams(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_PRICE_ID_TEAMS", "price_teams")
        assert billing.is_configured() is True


class TestStripeWebhookRoute:
    def _app(self) -> TestClient:
        return TestClient(make_app(gemini_api_key="t", gitlab_token="t"))

    def test_flips_account_to_pro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = get_store()
        store.upsert_account(Account(id="gitlab:1", provider="gitlab", plan="free"))
        monkeypatch.setattr(
            billing,
            "construct_event",
            lambda payload, sig: {
                "type": "checkout.session.completed",
                "data": {"object": {"client_reference_id": "gitlab:1", "customer": "cus_A"}},
            },
        )
        r = self._app().post("/webhook/stripe", content=b"{}", headers={"stripe-signature": "sig"})
        assert r.status_code == 200 and r.json()["plan"] == "pro"
        acct = store.get_account("gitlab:1")
        assert acct.plan == "pro" and acct.stripe_customer_id == "cus_A"

    def test_invalid_signature_is_400(self) -> None:
        # No STRIPE_WEBHOOK_SECRET → construct_event returns None → 400.
        r = self._app().post("/webhook/stripe", content=b"{}", headers={"stripe-signature": "x"})
        assert r.status_code == 400

    def test_unknown_account_is_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            billing,
            "construct_event",
            lambda payload, sig: {
                "type": "checkout.session.completed",
                "data": {"object": {"client_reference_id": "gitlab:absent"}},
            },
        )
        r = self._app().post("/webhook/stripe", content=b"{}", headers={"stripe-signature": "s"})
        assert r.status_code == 200 and r.json()["status"] == "unknown_account"


class TestSubscribeRoute:
    def test_requires_auth(self) -> None:
        app = make_app(gemini_api_key="t", gitlab_token="t")
        assert TestClient(app).post("/api/subscribe").status_code == 401

    def test_authed_but_unconfigured_is_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_SECRET", "testsecret")
        store = get_store()
        store.upsert_account(Account(id="gitlab:1", provider="gitlab", plan="free"))
        app = make_app(gemini_api_key="t", gitlab_token="t")
        client = TestClient(app)
        client.cookies.set("pg_session", _sign_value("gitlab:1", "testsecret"))
        r = client.post("/api/subscribe")
        assert r.status_code == 503  # billing not configured
