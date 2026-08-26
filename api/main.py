from contextlib import asynccontextmanager

from fastapi import FastAPI
from api.db import engine, init_db
from api.routes import analytics, plaid

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
app.include_router(plaid.router)
app.include_router(analytics.router)

@app.get("/ping")
async def ping(): return {"pong": True}
