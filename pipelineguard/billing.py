"""Account-aware Stripe billing for PipelineGuard 2.0 (Phase 1).

Maps the $29/mo Pro plan to ``store.PLAN_PRO``. The event→plan mapping is a pure
function (testable without Stripe); checkout creation and signature verification
call the Stripe SDK lazily, so the module imports fine without it.

Inert until configured: STRIPE_SECRET_KEY + STRIPE_PRICE_ID_PRO (the $29 price).
Webhook verification additionally needs STRIPE_WEBHOOK_SECRET.
"""
from __future__ import annotations

import os
from typing import Any

from .store import PLAN_FREE, PLAN_PRO, Account


def _secret_key() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "")


def _pro_price_id() -> str:
    # STRIPE_PRICE_ID_PRO is the canonical $29 price; fall back to the legacy
    # STRIPE_PRICE_ID_TEAMS so existing setups keep working.
    return os.environ.get("STRIPE_PRICE_ID_PRO", "") or os.environ.get(
        "STRIPE_PRICE_ID_TEAMS", ""
    )


def _webhook_secret() -> str:
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def is_configured() -> bool:
    return bool(_secret_key() and _pro_price_id())


async def create_pro_checkout(
    account: Account, success_url: str, cancel_url: str
) -> dict[str, Any]:
    """Create a Stripe Checkout session to upgrade an account to Pro."""
    if not is_configured():
        return {"error": "billing not configured"}
    try:
        import stripe

        stripe.api_key = _secret_key()
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": _pro_price_id(), "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=account.id,
            customer=account.stripe_customer_id or None,
            customer_email=account.email or None,
            metadata={"account_id": account.id},
            subscription_data={"metadata": {"account_id": account.id}},
        )
        return {"checkout_url": session.url}
    except Exception as exc:
        return {"error": f"checkout failed: {exc!s}"}


def plan_change_from_event(event: dict) -> tuple[str, str, str] | None:
    """Map a Stripe webhook event to ``(account_id, new_plan, customer_id)``.

    Returns None for events we don't act on, or when the account id is absent.
      - checkout.session.completed     -> Pro
      - customer.subscription.deleted  -> Free (downgrade on cancellation)
    """
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    customer = str(obj.get("customer") or "")
    if etype == "checkout.session.completed":
        account_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get(
            "account_id", ""
        )
        if account_id:
            return (str(account_id), PLAN_PRO, customer)
    elif etype == "customer.subscription.deleted":
        account_id = (obj.get("metadata") or {}).get("account_id", "")
        if account_id:
            return (str(account_id), PLAN_FREE, customer)
    return None


def construct_event(payload: bytes, sig_header: str) -> dict | None:
    """Verify a Stripe webhook signature and return the event, else None."""
    secret = _webhook_secret()
    if not secret or not sig_header:
        return None
    try:
        import stripe

        return stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception:
        return None
