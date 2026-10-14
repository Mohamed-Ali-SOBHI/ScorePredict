"""One rolling day shared by collection, publication and result refresh."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PREDICTION_WINDOW_HOURS = 24
PARIS = ZoneInfo("Europe/Paris")


def in_prediction_window(value: object, now: datetime) -> bool:
    try:
        kickoff = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=PARIS)
        if now.tzinfo is None:
            now = now.replace(tzinfo=PARIS)
        start = now.astimezone(timezone.utc)
        return start <= kickoff.astimezone(timezone.utc) < start + timedelta(hours=PREDICTION_WINDOW_HOURS)
    except (ValueError, TypeError):
        return False


def collection_dates(now: datetime) -> tuple[str, str]:
    """Calendar endpoints required by the source; exact kickoffs are filtered later."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=PARIS)
    end = now.astimezone(timezone.utc) + timedelta(hours=PREDICTION_WINDOW_HOURS)
    return now.astimezone(PARIS).date().isoformat(), end.astimezone(PARIS).date().isoformat()


if __name__ == "__main__":
    import json
    start, end = collection_dates(datetime.now(timezone.utc))
    print(json.dumps({"DateFrom": start, "DateTo": end}))
