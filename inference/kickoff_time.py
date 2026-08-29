from __future__ import annotations

import pandas as pd


PARIS_TIMEZONE = "Europe/Paris"


def paris_timestamp(value: object) -> pd.Timestamp:
    """Return one kickoff as a timezone-aware Europe/Paris timestamp.

    Naive values are part of the project's public contract and therefore mean
    local Paris time. Aware values are converted without changing the instant.
    """
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Kickoff timestamp is missing")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(PARIS_TIMEZONE, ambiguous="raise", nonexistent="raise")
    return timestamp.tz_convert(PARIS_TIMEZONE)


def coerce_paris_timestamp(value: object) -> pd.Timestamp:
    try:
        return paris_timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT


def paris_naive(value: object) -> pd.Timestamp:
    return paris_timestamp(value).tz_localize(None)


def paris_iso(value: object) -> str:
    return paris_timestamp(value).isoformat(timespec="seconds")


def paris_date_key(value: object) -> str:
    timestamp = coerce_paris_timestamp(value)
    return "" if pd.isna(timestamp) else timestamp.strftime("%Y-%m-%d")
