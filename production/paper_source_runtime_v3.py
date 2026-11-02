"""Retry transient source failures around the unchanged v2 paper experiment."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

import requests
from data_pipeline import http_retry
from production import paper_settlement_runtime_v2 as v2

VERSION = 'paper_source_retries_v3_2026_11_02'
MANIFEST = Path(__file__).with_suffix('.json')


def verify_amendment():
    manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
    files = {
        'runtime_sha256': Path(__file__),
        'http_helper_sha256': Path(http_retry.__file__),
        'parent_manifest_sha256': v2.MANIFEST,
    }
    if manifest['version'] != VERSION or any(
        hashlib.sha256(path.read_bytes()).hexdigest() != manifest[key]
        for key, path in files.items()
    ):
        raise ValueError('Source retry amendment changed; register a new version')
    return manifest


@contextmanager
def source_retries():
    # Frozen collectors import requests inside collect() and use worker threads.
    # Scope the adapter to this process, GET and the two public source hosts.
    original = requests.get
    def get(url, **kwargs):
        return http_retry.get(url, request=original, **kwargs)
    requests.get = get
    try:
        yield
    finally:
        requests.get = original


def main():
    verify_amendment()
    print('Source transport amendment: ' + VERSION, flush=True)
    with source_retries():
        # v2 still verifies both sealed protocols and all prior amendments,
        # guards live execution, records source timestamps and settles once.
        v2.main()


if __name__ == '__main__':
    main()
