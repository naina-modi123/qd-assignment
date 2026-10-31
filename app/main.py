
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from app.agent import analyze_message, process_verified_payout, pending_operations

load_dotenv()

PAYSWIFT_BASE_URL = os.getenv(
    "PAYSWIFT_BASE_URL",
    "http://localhost:8081",
)

app = FastAPI(title="Rider Payout Dispute Desk")

traces = {}
processed_messages = {}


class RiderMessage(BaseModel):
    message_id: str
    rider_id: str
    text: str
    received_at: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/messages")
def receive_message(message: RiderMessage):
    # Return the saved reply for a duplicate message.
    if message.message_id in processed_messages:
        return {
            "reply": "Duplicate message already processed. No new payout was made."
        }

    trace = traces.setdefault(message.rider_id, [])

    # Record the incoming message first.
    trace.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "type": "message_in",
        "name": "rider_message",
        "input": message.model_dump(),
        "output": None,
    })

    # Verify the dispute using the agent.
    result = analyze_message(
        message.rider_id,
        message.text,
        message.received_at,
    )

    reply = result["reply"]
    payout_result = None

    # Process only a verified positive shortfall.
    if (
        result.get("status") == "shortfall_found"
        and result.get("verified_amount", 0) > 0
    ):
        payout_result = process_verified_payout(
            rider_id=message.rider_id,
            amount=result["verified_amount"],
            reason=result.get("reason", "Verified payout dispute"),
            message_id=message.message_id,
            dispute_reference=result["dispute_reference"],
        )

        result["payout_result"] = payout_result
        reply += " | Payout status: " + payout_result["status"]

    # Save the final reply for message-level idempotency.
    processed_messages[message.message_id] = reply

        # Record the data-verification tool call.
    trace.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "type": "tool_call",
        "name": "analyze_message",
        "input": {
            "rider_id": message.rider_id,
            "text": message.text,
            "received_at": message.received_at,
        },
        "output": {
            "status": result.get("status"),
            "verified_amount": result.get("verified_amount", 0),
            "reason": result.get("reason"),
        },
    })

    # Record the verification and payout decision.
    trace.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "type": "decision",
        "name": "dispute_verification",
        "input": {
            "message_id": message.message_id,
            "rider_id": message.rider_id,
            "text": message.text,
        },
        "output": {
            "status": result.get("status"),
            "verified_amount": result.get("verified_amount", 0),
            "reason": result.get("reason"),
            "payout_result": payout_result,
        },
    })

    # Record the reply sent to the rider.
    trace.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "type": "reply",
        "name": "rider_reply",
        "input": None,
        "output": reply,
    })

    return {"reply": reply}


@app.get("/trace/{rider_id}")
def get_trace(rider_id: str):
    return traces.get(rider_id, [])


@app.get("/ops/pending")
def get_pending_operations():
    return pending_operations
