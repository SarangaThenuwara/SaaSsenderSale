import stripe
import logging
from .config import STRIPE_SECRET_KEY, STRIPE_SUCCESS_URL, STRIPE_CANCEL_URL, STRIPE_CURRENCY, STRIPE_PRICE_ID, APP_URL

stripe.api_key = STRIPE_SECRET_KEY
LOG = logging.getLogger(__name__)

def create_checkout_session(user_id, user_email, price_amount=10.00, product_name="Premium Subscription", mode="subscription"):
    """
    Creates a Stripe Checkout Session for the user.
    Can be 'payment' (one-time) or 'subscription' (recurring).
    """
    if not STRIPE_SECRET_KEY or STRIPE_SECRET_KEY.startswith("sk_test_51..."):
        LOG.error("Cannot create session: STRIPE_SECRET_KEY is invalid or default")
        return None
        
    try:
        if mode == "subscription":
            # If we have a Price ID configured, use it. Otherwise create inline price (legacy).
            if STRIPE_PRICE_ID and not STRIPE_PRICE_ID.startswith("price_..."):
                line_items = [{
                    'price': STRIPE_PRICE_ID,
                    'quantity': 1,
                }]
            else:
                line_items = [{
                    'price_data': {
                        'currency': STRIPE_CURRENCY or 'usd',
                        'product_data': {
                            'name': product_name,
                        },
                        'unit_amount': int(price_amount * 100),
                        'recurring': {'interval': 'month'},
                    },
                    'quantity': 1,
                }]
        else:
            line_items = [{
                'price_data': {
                    'currency': STRIPE_CURRENCY or 'usd',
                    'product_data': {
                        'name': product_name,
                    },
                    'unit_amount': int(price_amount * 100),
                },
                'quantity': 1,
            }]

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=user_email,
            line_items=line_items,
            mode=mode,
            success_url=STRIPE_SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=STRIPE_CANCEL_URL,
            metadata={
                "user_id": str(user_id),
                "type": "premium_subscription"
            }
        )
        return session
    except Exception as e:
        LOG.error(f"Error creating Stripe checkout session for user {user_id}: {e}")
        return None

def create_portal_session(customer_id, return_url=None):
    """
    Creates a Stripe Customer Portal session so users can manage/cancel their own subscriptions.
    """
    if not return_url:
        return_url = f"{APP_URL}/settings"
        
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return session
    except Exception as e:
        LOG.error(f"Error creating Stripe portal session: {e}")
        return None

def cancel_subscription(subscription_id):
    """
    Cancels a Stripe subscription immediately or at period end.
    """
    try:
        # We'll do cancel at period end for better UX, but you can set it to True for immediate.
        sub = stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )
        return sub
    except Exception as e:
        LOG.error(f"Error cancelling Stripe subscription {subscription_id}: {e}")
        return None

def verify_webhook_signature(payload, sig_header, webhook_secret):
    """
    Verifies the Stripe webhook signature.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        return event
    except ValueError as e:
        # Invalid payload
        LOG.error(f"Invalid webhook payload: {e}")
        return None
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        LOG.error(f"Invalid webhook signature: {e}")
        return None
