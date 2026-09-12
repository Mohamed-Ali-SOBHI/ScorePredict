"""Export fresh analyses independently of the official recommendations and ledger."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from production.dashboard import _read_csv
from production.explorer import build_explorer
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--predictions', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = Path(args.predictions)
    now = datetime.now(timezone.utc)
    rows = _read_csv(source)
    if any(row.get('portfolio_name') != DEFAULT_PORTFOLIO_NAME for row in rows):
        raise ValueError('Unexpected model portfolio')
    updated = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc)
    if (now-updated).total_seconds() > 86400:
        raise ValueError('Prediction export is stale')
    explorer = build_explorer(root, rows, now)
    payload = {'meta':{'status':'ready','latestPredictionAt':updated.isoformat(),'activePortfolio':DEFAULT_PORTFOLIO_NAME},'explorer':explorer}
    target = root/'production/static/data/explorer.json'
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print({'matches':len(explorer['matches']), 'output':str(target)})


if __name__ == '__main__':
    main()
