from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_pipeline.team_registry import audit_registry, read_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the current-season club registry.")
    parser.add_argument("--data-dir", default="Data")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--output", default="train/output/team_registry_audit.json")
    args = parser.parse_args()

    audit = audit_registry(read_registry(args.data_dir), args.season)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    if audit["status"] != "ok":
        raise SystemExit("Le registre des clubs de la saison est incomplet.")


if __name__ == "__main__":
    main()
