from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from api.db import engine, verify_database_name, verify_runtime_schema
from api.routes import analytics, plaid, review

@asynccontextmanager
async def lifespan(app: FastAPI):
    plaid.validate_runtime_configuration()
    await verify_database_name()
    await verify_runtime_schema()
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def local_request_boundary(request, call_next):
    if os.environ.get("PFT_STRICT_LOCAL_HTTP") == "true":
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        if host not in ("api", "127.0.0.1", "localhost"):
            return JSONResponse({"detail": "Invalid host"}, status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            allowed_origin = os.environ.get("PFT_ALLOWED_ORIGIN")
            if not allowed_origin or request.headers.get("origin") != allowed_origin:
                return JSONResponse({"detail": "Invalid origin"}, status_code=403)
    return await call_next(request)

app.include_router(plaid.router)
app.include_router(analytics.router)
app.include_router(review.router)

@app.get("/ping")
async def ping(): return {"pong": True}

@app.get("/ready")
async def ready():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"ready": True}
