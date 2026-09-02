from contextlib import asynccontextmanager

from fastapi import FastAPI
from api.db import engine, init_db, verify_database_name
from api.routes import analytics, plaid, review

@asynccontextmanager
async def lifespan(app: FastAPI):
    plaid.validate_runtime_configuration()
    await verify_database_name()
    await init_db()
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
app.include_router(plaid.router)
app.include_router(analytics.router)
app.include_router(review.router)

@app.get("/ping")
async def ping(): return {"pong": True}
