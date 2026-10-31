from app.payswift_client import create_payout
from datetime import datetime, timezone
pending_operations = []
daily_auto_payouts = {}
processed_payouts = set()
from app.data_loader import (
    load_data,
    calculate_trip_shortfall,
    calculate_daily_incentive,
    is_within_dispute_window,
)

data = load_data()
riders = data["riders"]
trips = data["trips"]
payout_lines = data["payout_lines"]


def find_trip(rider_id, trip_id):
    matching = trips[
        (trips["rider_id"] == rider_id)
        & (trips["trip_id"] == trip_id)
    ]

    if matching.empty:
        return None

    return matching.iloc[0].to_dict()


def check_trip_shortfall(rider_id, trip_id, received_at):
    trip = find_trip(rider_id, trip_id)

    if trip is None:
        return {"status": "not_found", "amount": 0}

    if trip["status"] != "completed":
        return {"status": "not_completed", "amount": 0}

    if not is_within_dispute_window(trip["started_at"], received_at):
        return {"status": "outside_window", "amount": 0}

    amount = calculate_trip_shortfall(
        trips, payout_lines, rider_id, trip_id
    )

    return {
        "status": "verified" if amount > 0 else "no_shortfall",
        "amount": amount,
    }

def check_trip_dispute(rider_id, trip_id, received_at):
    trip = find_trip(rider_id, trip_id)

    if trip is None:
        return {
            "status": "not_found",
            "amount": 0,
            "reason": "Trip not found for this rider.",
        }

    if trip["status"] != "completed":
        return {
            "status": "not_eligible",
            "amount": 0,
            "reason": "Only completed trips qualify for trip fare corrections.",
        }

    if not is_within_dispute_window(trip["started_at"], received_at):
        return {
            "status": "outside_window",
            "amount": 0,
            "reason": "The trip is outside the 7-day dispute window.",
        }

    shortfall = calculate_trip_shortfall(
        trips, payout_lines, rider_id, trip_id
    )

    if shortfall <= 0:
        return {
            "status": "no_shortfall",
            "amount": 0,
            "reason": "No missing payment was found for this trip.",
        }

    return {
        "status": "shortfall_found",
        "amount": shortfall,
        "reason": f"Verified missing payment for trip {trip_id}.",
    }
def check_incentive_dispute(rider_id, target_date, received_at):
    if not is_within_dispute_window(
        str(target_date), received_at
    ):
        return {
            "status": "outside_window",
            "amount": 0,
            "reason": "The incentive dispute is outside the 7-day window."
        }

    expected = calculate_daily_incentive(
        trips, rider_id, target_date
    )

    matching = payout_lines[
        (payout_lines["rider_id"] == rider_id)
        & (payout_lines["line_type"] == "daily_incentive")
        & (
            payout_lines["payout_date"].astype(str).str[:10]
            == str(target_date)
        )
    ]

    paid = int(matching["amount"].sum())
    shortfall = max(0, expected - paid)

    if shortfall > 0:
        return {
            "status": "shortfall_found",
            "amount": shortfall,
            "reason": (
                f"Verified missing incentive of ₹{shortfall} "
                f"for {target_date}."
            )
        }

    return {
        "status": "no_shortfall",
        "amount": 0,
        "reason": (
            f"No missing incentive payment found for {target_date}."
        )
    }
import re


def analyze_message(rider_id, message, received_at):
    trip_ids = re.findall(r"\bT\d+\b", message.upper())

    if trip_ids:
        result = check_trip_dispute(
            rider_id,
            trip_ids[0],
            received_at
        )

        if result["status"] == "shortfall_found":
            return {
                "reply": (
                    f"We verified a missing payment of "
                    f"₹{result['amount']} for trip {trip_ids[0]}."
                ),
                "verified_amount": result["amount"],
                "reason": result["reason"],
                "status": result["status"],
            }

        return {
            "reply": result.get(
                "reason",
                "We could not verify a missing payment for this trip."
            ),
            "verified_amount": 0,
            "reason": result.get("reason", "No shortfall verified."),
            "status": result["status"],
        }

    return {
        "reply": (
            "Please share the trip ID or the date of the missing "
            "payment so I can check your payout."
        ),
        "verified_amount": 0,
        "reason": "More information is needed.",
        "status": "needs_clarification",
    }


def process_verified_payout(rider_id, amount, reason, message_id):
    from zoneinfo import ZoneInfo

    if amount <= 0:
        return {
            "status": "no_payment",
            "amount": 0,
            "reason": "No verified missing payment.",
        }

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

    # Identify this specific dispute separately from the daily limit.
    payout_key = (rider_id, message_id)
    daily_key = (rider_id, today)

    if payout_key in processed_payouts:
        return {
            "status": "duplicate_payout",
            "amount": 0,
            "reason": "This dispute has already been processed.",
        }

    def queue_approval(approval_reason):
        operation = {
            "id": f"OP-{len(pending_operations) + 1:04d}",
            "rider_id": rider_id,
            "type": "approval",
            "amount": amount,
            "reason": approval_reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        pending_operations.append(operation)
        return {
            "status": "approval_required",
            "amount": amount,
            "reason": approval_reason,
            "operation_id": operation["id"],
        }

    # Finance policy: only one automatic payout per rider per IST day.
    if daily_auto_payouts.get(daily_key, 0) > 0:
        return queue_approval(
            "Repeat dispute: manual approval required. " + reason
        )

    # Amounts above ₹200 require human approval.
    if amount > 200:
        return queue_approval(reason)

    try:
        payout = create_payout(
            rider_id=rider_id,
            amount=amount,
            reference=reason,
            message_id=message_id,
        )

        # Record only after the payment succeeds.
        processed_payouts.add(payout_key)
        daily_auto_payouts[daily_key] = amount

        return {
            "status": "paid",
            "amount": amount,
            "payout": payout,
            "reason": reason,
        }

    except Exception as exc:
        return {
            "status": "payment_error",
            "amount": amount,
            "reason": str(exc),
        }
