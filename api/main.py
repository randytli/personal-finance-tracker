from fastapi import FastAPI
from api.routes import plaid
app = FastAPI()
app.include_router(plaid.router)

@app.get("/ping")
async def ping(): return {"pong": True}