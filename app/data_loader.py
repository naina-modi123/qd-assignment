from datetime import datetime
from pathlib import Path
from datetime import datetime
import pandas as pd
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def load_data():
    return {
        "riders": pd.read_csv(DATA_DIR / "riders.csv"),
        "trips": pd.read_csv(DATA_DIR / "trips.csv"),
        "payout_lines": pd.read_csv(DATA_DIR / "payout_lines.csv"),
    }
def calculate_trip_fare(distance_km, surge_multiplier):
    distance_km = float(distance_km)
    surge_multiplier = float(surge_multiplier)

    fare = (25 + max(0, distance_km - 2) * 6) * surge_multiplier

    # Round to nearest rupee, with 0.5 rounded up.
    return int(fare + 0.5)
def get_ist_date(timestamp):
    dt = pd.to_datetime(timestamp, utc=True)
    return dt.tz_convert("Asia/Kolkata").date()

def count_completed_trips(trips, rider_id, target_date):
    rider_trips = trips[
        (trips["rider_id"] == rider_id)
        & (trips["status"] == "completed")
    ].copy()

    rider_trips["ist_date"] = rider_trips["started_at"].apply(
        get_ist_date
    )

    return int(
        (rider_trips["ist_date"] == target_date).sum()
    )
def calculate_daily_incentive(trips, rider_id, target_date):
    completed_count = count_completed_trips(
        trips, rider_id, target_date
    )

    if completed_count >= 12:
        return 150

    return 0


def get_trip_payment(payout_lines, rider_id, trip_id):
    matching = payout_lines[
        (payout_lines["rider_id"] == rider_id)
        & (payout_lines["trip_id"] == trip_id)
        & (payout_lines["line_type"] == "trip")
    ]

    return int(matching["amount"].sum())

def calculate_trip_shortfall(trips, payout_lines, rider_id, trip_id):
    matching_trip = trips[
        (trips["rider_id"] == rider_id)
        & (trips["trip_id"] == trip_id)
        & (trips["status"] == "completed")
    ]

    if matching_trip.empty:
        return 0

    trip = matching_trip.iloc[0]

    expected = calculate_trip_fare(
        trip["distance_km"],
        trip["surge_multiplier"],
    )

    paid = get_trip_payment(payout_lines, rider_id, trip_id)

    return max(0, expected - paid)

def is_within_dispute_window(trip_timestamp, received_at):
    trip_date = get_ist_date(trip_timestamp)
    received_date = get_ist_date(received_at)

    days_ago = (received_date - trip_date).days

    return 0 <= days_ago <= 7
