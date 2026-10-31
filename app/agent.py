from app.payswift_client import create_payout, get_rider_payouts
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


def check_cancellation_dispute(rider_id, trip_id, received_at):
    trip = find_trip(rider_id, trip_id)

    if trip is None:
        return {
            "status": "not_found",
            "amount": 0,
            "reason": "Trip not found for this rider.",
        }

    if trip["status"] != "cancelled_by_rider":
        return {
            "status": "not_eligible",
            "amount": 0,
            "reason": (
                "This trip was not cancelled by the rider. "
                "The rider-cancellation penalty does not apply."
            ),
        }

    if not is_within_dispute_window(trip["started_at"], received_at):
        return {
            "status": "outside_window",
            "amount": 0,
            "reason": "The cancellation dispute is outside the 7-day window.",
        }

    matching = payout_lines[
        (payout_lines["rider_id"] == rider_id)
        & (payout_lines["trip_id"] == trip_id)
        & (payout_lines["line_type"] == "cancellation_penalty")
    ]

    if matching.empty:
        return {
            "status": "no_penalty_record",
            "amount": 0,
            "reason": (
                "No cancellation penalty deduction was found in the "
                "payout records. No rider payout is due based on this "
                "record alone; manual review may be needed."
            ),
        }

    return {
        "status": "penalty_recorded",
        "amount": 0,
        "reason": (
            f"A cancellation penalty record exists for trip {trip_id}. "
            "Please review the recorded deduction if you dispute it."
        ),
    }

def analyze_message(rider_id, message, received_at):
    message_lower = message.lower()

    # Extract trip IDs from the message.
    trip_ids = re.findall(r"\bT\d+\b", message.upper())

    # Handle cancellation-related messages first.
    # Do not automatically pay a rider for a missing penalty record.
    if "cancel" in message_lower or "penalty" in message_lower:
        if not trip_ids:
            return {
                "reply": (
                    "Please share the trip ID for the "
                    "cancellation penalty dispute."
                ),
                "verified_amount": 0,
                "reason": "Cancellation dispute requires a trip ID.",
                "status": "needs_clarification",
            }

        result = check_cancellation_dispute(
            rider_id, trip_ids[0], received_at
        )

        return {
            "reply": result["reason"],
            "verified_amount": 0,
            "reason": result["reason"],
            "status": result["status"],
        }

    # Check completed-trip fare disputes.
    if trip_ids:
        result = check_trip_dispute(
            rider_id, trip_ids[0], received_at
        )

        if result["status"] == "shortfall_found":
            return {
                "reply": (
                    f"We verified a missing payment of "
                    f"INR {result['amount']} for trip {trip_ids[0]}."
                ),
                "verified_amount": result["amount"],
                "reason": result["reason"],
                "dispute_reference": f"trip:{rider_id}:{trip_ids[0]}",
                "status": result["status"],
            }

        return {
            "reply": result["reason"],
            "verified_amount": 0,
            "reason": result["reason"],
            "status": result["status"],
        }

    # Check daily incentive disputes.
    if "incentive" in message_lower:
        dates = re.findall(
            r"\b\d{4}-\d{2}-\d{2}\b", message
        )

        if not dates:
            return {
                "reply": (
                    "Please share the date of the missing "
                    "incentive in YYYY-MM-DD format."
                ),
                "verified_amount": 0,
                "reason": "Incentive dispute requires a date.",
                "status": "needs_clarification",
            }

        target_date = dates[0]
        result = check_incentive_dispute(
            rider_id, target_date, received_at
        )

        return {
            "reply": (
                f"Verified missing incentive: INR {result['amount']}."
                if result["status"] == "shortfall_found"
                else result["reason"]
            ),
            "verified_amount": result["amount"],
            "reason": result["reason"],
            "dispute_reference": f"incentive:{rider_id}:{target_date}",
            "status": result["status"],
        }

    return {
        "reply": (
            "Please share a trip ID or mention 'incentive' "
            "with its date in YYYY-MM-DD format."
        ),
        "verified_amount": 0,
        "reason": "More information is needed.",
        "status": "needs_clarification",
    }
def process_verified_payout(
    rider_id, amount, reason, message_id, dispute_reference
):
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
        # Reconcile against PaySwift's actual ledger first.
        existing_response = get_rider_payouts(rider_id)
        existing_payouts = existing_response.get("data", [])

        # A prior payout with the same reference may mean this
        # dispute was already paid, even after an app restart.
        matching_payout = next(
            (
                item for item in existing_payouts
                if item.get("rider_id") == rider_id
                and item.get("reference") == dispute_reference
                and int(item.get("amount", 0)) == int(amount)
                and item.get("status") == "processed"
            ),
            None,
        )

        if matching_payout:
            processed_payouts.add(payout_key)
            return {
                "status": "already_reconciled",
                "amount": 0,
                "payout": matching_payout,
                "reason": (
                    "A matching payout already exists in PaySwift. "
                    "No additional payout was created."
                ),
            }

        payout = create_payout(
            rider_id=rider_id,
            amount=amount,
            reference=dispute_reference,
            message_id=message_id,
        )

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
