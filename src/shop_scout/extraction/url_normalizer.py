from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from shop_scout.constants import TRACKING_QUERY_KEYS


def normalize_http_url(url: str, base_url: str | None = None) -> str:
    value = url.strip()
    if value.startswith("//"):
        value = f"https:{value}"
    elif base_url:
        value = urljoin(base_url, value)
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Unsupported URL: {url!r}")
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port else ""
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
    ]
    query.sort()
    return urlunsplit(
        (parsed.scheme.lower(), f"{host}{port}", parsed.path or "/", urlencode(query), "")
    )


def canonical_url_hash(url: str) -> str:
    return hashlib.sha256(normalize_http_url(url).encode()).hexdigest()[:24]


def query_value(url: str, *keys: str) -> str | None:
    wanted = {key.lower() for key in keys}
    for key, value in parse_qsl(urlsplit(url).query):
        if key.lower() in wanted and value:
            return value
    return None
