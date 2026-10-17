"""Bounded GitHub-hosted watch around published bets, without a local daemon."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

PUBLIC_DASHBOARD = "https://mohamed-ali-sobhi.github.io/ScorePredict/data/dashboard.json"
WORKFLOW = "results-monitor.yml"


def watch_state(snapshot: dict, now: datetime) -> tuple[bool, bool]:
    """Watch near-term matches; retry old unmatched results via the normal cron."""
    watch, due = False, False
    for row in snapshot.get("activity", []):
        if row.get("recommended") is not True or row.get("status") in {"won", "lost", "void"}:
            continue
        try:
            kickoff = datetime.fromisoformat(row["date"].replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        # A morning/daily workflow can arm the watch before kickoff. Never
        # hold the Pages publication lock while waiting in this runner.
        if kickoff - timedelta(hours=5) <= now <= kickoff + timedelta(hours=6):
            watch = True
            due |= now >= kickoff + timedelta(minutes=105)
    return watch, due


def monitor_busy(runs: list[dict]) -> bool:
    return any(run.get("status") != "completed" for run in runs)


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True, timeout=40)


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This watch runs only on GitHub Actions, not on a local computer.")
    repository = os.environ["GITHUB_REPOSITORY"]
    deadline = time.monotonic() + 350 * 60
    failures = 0
    while time.monotonic() < deadline:
        try:
            request = Request(f"{PUBLIC_DASHBOARD}?watch={int(time.time())}", headers={"Cache-Control": "no-cache"})
            with urlopen(request, timeout=30) as response:
                snapshot = json.load(response)
            watch, due = watch_state(snapshot, datetime.now(timezone.utc))
            if not watch:
                print("No near-term published bet needs watching.", flush=True)
                return
            if due:
                runs = json.loads(gh("run", "list", "--repo", repository, "--workflow", WORKFLOW,
                                     "--limit", "10", "--json", "status"))
                if not monitor_busy(runs):
                    gh("workflow", "run", WORKFLOW, "--repo", repository, "--ref", "main")
                    print("Dispatched result check.", flush=True)
                else:
                    print("Result check already running or queued.", flush=True)
            failures = 0
        except Exception as exc:
            failures += 1
            print(f"Watch request failed ({failures}/3): {exc}", flush=True)
            if failures >= 3:
                raise
        time.sleep(min(300, max(0, deadline - time.monotonic())))
    print("Bounded watch finished; later scheduled runs remain enabled.", flush=True)


if __name__ == "__main__":
    main()
