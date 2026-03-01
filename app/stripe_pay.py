import stripe
import logging
from .config import STRIPE_SECRET_KEY, STRIPE_SUCCESS_URL, STRIPE_CANCEL_URL, STRIPE_CURRENCY

stripe.api_key = STRIPE_SECRET_KEY
LOG = logging.getLogger(__name__)

def create_checkout_session(user_id, user_email, price_amount=10.00, product_name="Premium Subscription"):
    """
    Creates a Stripe Checkout Session for the user.
    """
    from .config import STRIPE_SECRET_KEY
    if not STRIPE_SECRET_KEY or STRIPE_SECRET_KEY.startswith("sk_test_51..."):
        LOG.error("Cannot create session: STRIPE_SECRET_KEY is invalid or default")
        return None
        
    stripe.api_key = STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=user_email,
            line_items=[{
                'price_data': {
                    'currency': STRIPE_CURRENCY or 'usd',
                    'product_data': {
                        'name': product_name,
                    },
                    'unit_amount': int(price_amount * 100), # amount in cents
                },
                'quantity': 1,
            }],
            mode='payment',
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
