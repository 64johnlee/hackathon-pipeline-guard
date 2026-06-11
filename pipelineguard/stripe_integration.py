"""Stripe payment integration for PipelineGuard subscription tiers."""

import os
from typing import Any

STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")

PRICING_TIERS = {
    "free": {
        "name": "Free",
        "price": 0,
        "description": "Unlimited diagnoses on public repositories",
        "features": [
            "Unlimited diagnoses on public repos",
            "GitLab CI support",
            "Community support",
            "30-day log retention",
        ],
    },
    "teams": {
        "name": "Teams",
        "price": 29,
        "price_id": os.getenv("STRIPE_PRICE_ID_TEAMS", ""),
        "description": "For teams managing private repositories",
        "features": [
            "Private repository support",
            "Slack & Teams routing",
            "90-day log retention",
            "Up to 5 team members",
            "Email support",
        ],
    },
    "business": {
        "name": "Business",
        "price": 99,
        "price_id": os.getenv("STRIPE_PRICE_ID_BUSINESS", ""),
        "description": "Enterprise-grade features",
        "features": [
            "Multi-project dashboards",
            "Single Sign-On (SSO)",
            "Service Level Agreement (SLA)",
            "Unlimited team members",
            "Priority 24/7 support",
            "Advanced analytics",
        ],
    },
}


def generate_pricing_html() -> str:
    """Generate HTML for the pricing page with Stripe integration."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>PipelineGuard Pricing</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0d1117;
      color: #e6edf3;
      min-height: 100vh;
      padding-top: 2rem;
    }
    header {
      text-align: center;
      margin-bottom: 3rem;
    }
    header h1 {
      font-size: 2.5rem;
      font-weight: 700;
      color: #58a6ff;
      margin-bottom: 0.5rem;
    }
    header p {
      font-size: 1.1rem;
      color: #8b949e;
    }
    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 1rem;
    }
    .pricing-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 2rem;
      margin-bottom: 3rem;
    }
    .pricing-card {
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 12px;
      padding: 2rem;
      display: flex;
      flex-direction: column;
      transition: all 0.3s ease;
    }
    .pricing-card:hover {
      border-color: #58a6ff;
      box-shadow: 0 8px 24px rgba(88, 166, 255, 0.15);
    }
    .pricing-card.featured {
      border-color: #58a6ff;
      background: #0d1117;
      box-shadow: 0 8px 24px rgba(88, 166, 255, 0.1);
    }
    .pricing-header {
      margin-bottom: 1.5rem;
    }
    .pricing-header h2 {
      font-size: 1.5rem;
      color: #e6edf3;
      margin-bottom: 0.5rem;
    }
    .pricing-header p {
      color: #8b949e;
      font-size: 0.9rem;
    }
    .price {
      font-size: 3rem;
      font-weight: 700;
      color: #58a6ff;
      margin: 1rem 0;
    }
    .price-unit {
      font-size: 1rem;
      color: #8b949e;
      font-weight: 400;
    }
    .features {
      list-style: none;
      margin: 2rem 0;
      flex-grow: 1;
    }
    .features li {
      padding: 0.75rem 0;
      color: #8b949e;
      border-bottom: 1px solid #21262d;
      display: flex;
      align-items: center;
    }
    .features li:last-child {
      border-bottom: none;
    }
    .features li::before {
      content: '✓';
      color: #3fb950;
      font-weight: 700;
      margin-right: 0.75rem;
      font-size: 1.1rem;
    }
    .cta-button {
      background: #238636;
      color: #fff;
      border: none;
      border-radius: 6px;
      padding: 0.75rem 1.5rem;
      font-size: 1rem;
      cursor: pointer;
      font-weight: 600;
      transition: background 0.2s;
      margin-top: 1.5rem;
      width: 100%;
    }
    .cta-button:hover {
      background: #2ea043;
    }
    .cta-button:disabled {
      background: #21262d;
      color: #484f58;
      cursor: not-allowed;
    }
    .cta-button.secondary {
      background: #21262d;
      color: #8b949e;
      border: 1px solid #30363d;
    }
    .cta-button.secondary:hover {
      background: #30363d;
      border-color: #58a6ff;
    }
    .faq {
      margin-top: 4rem;
      padding-top: 2rem;
      border-top: 1px solid #30363d;
    }
    .faq h2 {
      font-size: 1.5rem;
      margin-bottom: 2rem;
      text-align: center;
    }
    .faq-item {
      margin-bottom: 1.5rem;
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 1.5rem;
    }
    .faq-item h3 {
      color: #58a6ff;
      margin-bottom: 0.5rem;
      font-size: 1.1rem;
    }
    .faq-item p {
      color: #8b949e;
      line-height: 1.6;
    }
    .footer {
      text-align: center;
      margin-top: 4rem;
      padding-top: 2rem;
      border-top: 1px solid #30363d;
      color: #8b949e;
      font-size: 0.9rem;
    }
    .footer a {
      color: #58a6ff;
      text-decoration: none;
    }
    .footer a:hover {
      text-decoration: underline;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>PipelineGuard Pricing</h1>
      <p>Choose the plan that fits your team's needs</p>
    </header>

    <div class="pricing-grid">
      <!-- Free Tier -->
      <div class="pricing-card">
        <div class="pricing-header">
          <h2>Free</h2>
          <p>Get started for free</p>
        </div>
        <div class="price"><span class="price-unit">$</span>0<span class="price-unit">/month</span></div>
        <ul class="features">
          <li>Unlimited diagnoses on public repos</li>
          <li>GitLab CI support</li>
          <li>Community support</li>
          <li>30-day log retention</li>
        </ul>
        <button class="cta-button secondary" disabled>Current Plan</button>
      </div>

      <!-- Teams Tier -->
      <div class="pricing-card featured">
        <div class="pricing-header">
          <h2>Teams</h2>
          <p>For growing teams</p>
        </div>
        <div class="price"><span class="price-unit">$</span>29<span class="price-unit">/month</span></div>
        <ul class="features">
          <li>Private repository support</li>
          <li>Slack & Teams routing</li>
          <li>90-day log retention</li>
          <li>Up to 5 team members</li>
          <li>Email support</li>
        </ul>
        <button class="cta-button" onclick="subscribe('teams')">Start 7-day Free Trial</button>
      </div>

      <!-- Business Tier -->
      <div class="pricing-card">
        <div class="pricing-header">
          <h2>Business</h2>
          <p>Enterprise features</p>
        </div>
        <div class="price"><span class="price-unit">$</span>99<span class="price-unit">/month</span></div>
        <ul class="features">
          <li>Multi-project dashboards</li>
          <li>Single Sign-On (SSO)</li>
          <li>Service Level Agreement (SLA)</li>
          <li>Unlimited team members</li>
          <li>Priority 24/7 support</li>
          <li>Advanced analytics</li>
        </ul>
        <button class="cta-button" onclick="subscribe('business')">Start 7-day Free Trial</button>
      </div>
    </div>

    <div class="faq">
      <h2>Frequently Asked Questions</h2>

      <div class="faq-item">
        <h3>Can I switch plans anytime?</h3>
        <p>Yes! You can upgrade or downgrade your plan at any time. Changes take effect at the end of your billing cycle.</p>
      </div>

      <div class="faq-item">
        <h3>Is there a free trial?</h3>
        <p>Yes, all paid plans include a 7-day free trial. No credit card required to start.</p>
      </div>

      <div class="faq-item">
        <h3>What happens when my trial expires?</h3>
        <p>We'll send you a reminder before your trial expires. Your subscription will only renew if you confirm.</p>
      </div>

      <div class="faq-item">
        <h3>Do you offer annual billing discounts?</h3>
        <p>Contact our sales team for enterprise pricing and annual billing options.</p>
      </div>

      <div class="faq-item">
        <h3>What payment methods do you accept?</h3>
        <p>We accept all major credit cards via Stripe. Other payment methods available for enterprise customers.</p>
      </div>
    </div>

    <div class="footer">
      <p>All plans include 24-hour support. <a href="/">Back to PipelineGuard</a></p>
    </div>
  </div>

  <script>
    function subscribe(plan) {
      const btn = event.target;
      btn.disabled = true;
      btn.textContent = '⏳ Redirecting...';

      fetch('/subscribe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({plan: plan})
      })
      .then(r => r.json())
      .then(data => {
        if (data.checkout_url) {
          window.location.href = data.checkout_url;
        } else if (data.error) {
          alert('Error: ' + data.error);
          btn.disabled = false;
          btn.textContent = 'Start 7-day Free Trial';
        }
      })
      .catch(e => {
        alert('Error: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Start 7-day Free Trial';
      });
    }
  </script>
</body>
</html>"""


async def create_checkout_session(plan: str, customer_email: str = "") -> dict[str, Any]:
    """Create a Stripe Checkout session for the given plan.

    Returns a dict with 'checkout_url' key on success, or 'error' key on failure.
    """
    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe is not configured. Contact support."}

    if plan not in PRICING_TIERS:
        return {"error": f"Invalid plan: {plan}"}

    tier = PRICING_TIERS[plan]
    price_id = tier.get("price_id", "")

    if plan != "free" and not price_id:
        return {"error": f"Plan {plan} is not yet available. Please contact sales@pipelineguard.io"}

    try:
        import stripe

        stripe.api_key = STRIPE_SECRET_KEY

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            mode="subscription",
            success_url="https://pipeline-guard-fpgq3ij7ya-uc.a.run.app?subscribe=success",
            cancel_url="https://pipeline-guard-fpgq3ij7ya-uc.a.run.app/pricing",
            customer_email=customer_email,
            billing_address_collection="auto",
        )
        return {"checkout_url": session.url}
    except ImportError:
        return {
            "error": "Stripe SDK not installed. Install with: pip install stripe",
            "plan": plan,
        }
    except Exception as e:
        return {"error": f"Failed to create checkout session: {e!s}"}
