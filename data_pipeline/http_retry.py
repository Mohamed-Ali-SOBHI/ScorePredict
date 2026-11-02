"""Bounded retries for live, read-only public data requests; never use stale data."""
import time
from urllib.parse import urlsplit

import requests

DELAYS = (3, 10, 30)
TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}
SOURCE_HOSTS = {'understat.com', 'www.football-data.co.uk'}


def get(url, *, request=None, **kwargs):
    request = request or requests.get
    # Do not apply this policy to authenticated stores or unrelated services.
    if urlsplit(url).hostname not in SOURCE_HOSTS:
        return request(url, **kwargs)
    for attempt in range(len(DELAYS) + 1):
        try:
            response = request(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError:
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as error:
            if isinstance(error, requests.exceptions.HTTPError):
                if error.response is None or error.response.status_code not in TRANSIENT_STATUS:
                    raise
                error.response.close()
            if attempt == len(DELAYS):
                raise
            delay = DELAYS[attempt]
            print(f'Public source {urlsplit(url).hostname}: {type(error).__name__}; '
                  f'retry {attempt + 2}/{len(DELAYS) + 1} in {delay}s.', flush=True)
            time.sleep(delay)
