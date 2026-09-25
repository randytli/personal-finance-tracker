from contextlib import asynccontextmanager
import ipaddress
import os
import re
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from api.db import engine, verify_database_name, verify_runtime_schema
from api.routes import analytics, plaid, review, sync

@asynccontextmanager
async def lifespan(app: FastAPI):
    plaid.validate_runtime_configuration()
    if os.environ.get("PFT_STRICT_LOCAL_HTTP") == "true":
        boundary_config()
    await verify_database_name()
    await verify_runtime_schema()
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)


_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def _host_name(value: str) -> str:
    if not value or value.endswith(".") or "*" in value:
        raise ValueError("Invalid host name")
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        name = value.lower()
        if len(name) > 253 or not all(_DNS_LABEL.fullmatch(label) for label in name.split(".")):
            raise ValueError("Invalid host name") from None
        return name


def _authority(value: str) -> tuple[str, int | None]:
    if not value or value != value.strip() or any(c in value for c in "/?#@,\\"):
        raise ValueError("Invalid host authority")
    parsed = urlsplit("//" + value)
    if parsed.path or parsed.query or parsed.fragment or parsed.username is not None:
        raise ValueError("Invalid host authority")
    if parsed.hostname is None or value.endswith(":"):
        raise ValueError("Invalid host authority")
    host = _host_name(parsed.hostname)
    # IPv6 authorities must be bracketed; a bare colon is ambiguous with a port.
    if ":" in host and not value.startswith("["):
        raise ValueError("Unbracketed IPv6 host")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid host port")
    return host, port


def _origin(value: str) -> tuple[str, str, int]:
    if not value or value != value.strip() or "*" in value:
        raise ValueError("Invalid origin")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.netloc or
            parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Invalid origin")
    host, port = _authority(parsed.netloc)
    return parsed.scheme, host, port or (443 if parsed.scheme == "https" else 80)


def boundary_config() -> tuple[set[tuple[str, int | None]], set[tuple[str, str, int]]]:
    hosts_value = os.environ.get("PFT_ALLOWED_HOSTS", "")
    if not hosts_value:
        raise ValueError("PFT_ALLOWED_HOSTS is required")
    hosts = {_authority(entry) for entry in hosts_value.split(",")}
    origin_values = []
    if "PFT_ALLOWED_ORIGINS" in os.environ:
        origin_values.extend(os.environ["PFT_ALLOWED_ORIGINS"].split(","))
    if "PFT_ALLOWED_ORIGIN" in os.environ:
        origin_values.append(os.environ["PFT_ALLOWED_ORIGIN"])
    if not origin_values:
        raise ValueError("At least one allowed origin is required")
    origins = {_origin(entry) for entry in origin_values}
    return hosts, origins

@app.middleware("http")
async def local_request_boundary(request, call_next):
    if os.environ.get("PFT_STRICT_LOCAL_HTTP") == "true":
        try:
            allowed_hosts, allowed_origins = boundary_config()
        except ValueError:
            return JSONResponse({"detail": "HTTP boundary unavailable"}, status_code=503)
        try:
            host_headers = (request.headers.getlist("host") if hasattr(request.headers, "getlist")
                            else [request.headers.get("host", "")])
            if len(host_headers) != 1 or _authority(host_headers[0]) not in allowed_hosts:
                raise ValueError("Host is not allowed")
        except ValueError:
            return JSONResponse({"detail": "Invalid host"}, status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            try:
                origin = _origin(request.headers.get("origin", ""))
            except ValueError:
                origin = None
            if origin not in allowed_origins:
                return JSONResponse({"detail": "Invalid origin"}, status_code=403)
    return await call_next(request)

app.include_router(plaid.router)
app.include_router(analytics.router)
app.include_router(review.router)
app.include_router(sync.router)

@app.get("/ping")
async def ping(): return {"pong": True}

@app.get("/ready")
async def ready():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"ready": True}
