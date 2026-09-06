"""The public window uses Paris calendar days, including today."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PREDICTION_WINDOW_DAYS = 3
PARIS = ZoneInfo("Europe/Paris")


def in_prediction_window(value: object, now: datetime) -> bool:
    try:
        kickoff = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=PARIS)
        today = now.astimezone(PARIS).date()
        return today <= kickoff.astimezone(PARIS).date() < today + timedelta(days=PREDICTION_WINDOW_DAYS)
    except (ValueError, TypeError):
        return False
