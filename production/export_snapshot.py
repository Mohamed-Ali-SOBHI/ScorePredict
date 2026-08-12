from __future__ import annotations

import argparse
from pathlib import Path

from production.dashboard import DashboardService, write_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the ScorePredict read model for static hosting.")
    parser.add_argument("--root", default=None, help="Repository root (auto-detected by default).")
    parser.add_argument("--output", default=None, help="Target JSON path.")
    parser.add_argument("--allow-stale", action="store_true", help="Export even when the data audit is stale.")
    args = parser.parse_args()

    service = DashboardService(root=args.root, ttl_seconds=0)
    payload = service.get_dashboard(force=True)
    quality = payload.get("quality", {})
    if not args.allow_stale and quality.get("overallStatus") != "pass":
        raise SystemExit(
            "Publication refusée : les contrôles de qualité/fraîcheur ne sont pas tous au vert. "
            "Corrigez les sources ou utilisez --allow-stale pour une prévisualisation explicitement signalée."
        )
    target = Path(args.output).resolve() if args.output else None
    path = write_snapshot(service, target)
    print(f"Snapshot écrit : {path}")


if __name__ == "__main__":
    main()
