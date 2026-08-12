from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qs

from production.dashboard import DashboardService


STATIC_ROOT = Path(__file__).resolve().parent / "static"
SERVICE = DashboardService()


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _response(
    start_response: Callable,
    status: str,
    body: bytes,
    content_type: str,
    *,
    cache_control: str = "no-store",
    environ: dict | None = None,
) -> Iterable[bytes]:
    headers = [
        ("Content-Type", content_type),
        ("Cache-Control", cache_control),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
        ("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"),
    ]
    etag = f'"{hashlib.sha256(body).hexdigest()[:24]}"'
    headers.append(("ETag", etag))
    request_etag = (environ or {}).get("HTTP_IF_NONE_MATCH")
    if request_etag == etag:
        start_response("304 Not Modified", headers)
        return [b""]
    accepts_gzip = "gzip" in (environ or {}).get("HTTP_ACCEPT_ENCODING", "")
    if accepts_gzip and len(body) > 1200:
        body = gzip.compress(body, compresslevel=5)
        headers.append(("Content-Encoding", "gzip"))
        headers.append(("Vary", "Accept-Encoding"))
    headers.append(("Content-Length", str(len(body))))
    start_response(status, headers)
    if (environ or {}).get("REQUEST_METHOD") == "HEAD":
        return [b""]
    return [body]


def _safe_static_path(url_path: str) -> Path | None:
    relative = "index.html" if url_path == "/" else url_path.lstrip("/")
    candidate = (STATIC_ROOT / relative).resolve()
    try:
        candidate.relative_to(STATIC_ROOT.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def application(environ: dict, start_response: Callable) -> Iterable[bytes]:
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")
    if method not in {"GET", "HEAD"}:
        return _response(start_response, "405 Method Not Allowed", _json_bytes({"error": "method_not_allowed"}), "application/json; charset=utf-8", environ=environ)

    if path == "/api/health":
        dashboard = SERVICE.get_dashboard()
        status = dashboard.get("meta", {}).get("status", "blocked")
        code = "200 OK" if status != "blocked" else "503 Service Unavailable"
        return _response(
            start_response,
            code,
            _json_bytes({"status": status, "generatedAt": dashboard.get("meta", {}).get("generatedAt")}),
            "application/json; charset=utf-8",
            environ=environ,
        )

    if path == "/api/v1/dashboard":
        query = parse_qs(environ.get("QUERY_STRING", ""))
        force = query.get("refresh", [""])[0] == "1"
        return _response(
            start_response,
            "200 OK",
            _json_bytes(SERVICE.get_dashboard(force=force)),
            "application/json; charset=utf-8",
            cache_control="private, max-age=15",
            environ=environ,
        )

    static_path = _safe_static_path(path)
    if static_path:
        content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        cache = "public, max-age=3600" if path.startswith("/assets/") else "no-cache"
        return _response(start_response, "200 OK", static_path.read_bytes(), content_type, cache_control=cache, environ=environ)

    if not path.startswith("/api/"):
        index = STATIC_ROOT / "index.html"
        return _response(start_response, "200 OK", index.read_bytes(), "text/html; charset=utf-8", cache_control="no-cache", environ=environ)
    return _response(start_response, "404 Not Found", _json_bytes({"error": "not_found"}), "application/json; charset=utf-8", environ=environ)


def main() -> None:
    from wsgiref.simple_server import make_server

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"ScorePredict disponible sur http://{host}:{port}")
    with make_server(host, port, application) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
