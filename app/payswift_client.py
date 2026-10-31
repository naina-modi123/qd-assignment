
import os
import requests


PAYSWIFT_BASE_URL = os.getenv(
    "PAYSWIFT_BASE_URL",
    "http://localhost:8081"
).rstrip("/")


def get_rider_payouts(rider_id):
    """Fetch payouts recorded by PaySwift for a rider."""
    response = requests.get(
        f"{PAYSWIFT_BASE_URL}/v1/payouts",
        params={"rider_id": rider_id},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def create_payout(rider_id, amount, reference, message_id):
    """Submit a payout using message_id as the idempotency key."""
    response = requests.post(
        f"{PAYSWIFT_BASE_URL}/v1/payouts",
        json={
            "rider_id": rider_id,
            "amount": int(amount),
            "reference": reference,
        },
        headers={"Idempotency-Key": message_id},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
