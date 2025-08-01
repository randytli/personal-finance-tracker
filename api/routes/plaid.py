from fastapi import APIRouter, Depends
from plaid import Client, errors
from api.db import SessionLocal
from api.models import Item
import os, uuid

router = APIRouter(prefix="/plaid")

def get_client():
    return Client(
        client_id=os.environ["PLAID_CLIENT_ID"],
        secret=os.environ["PLAID_SECRET"],
        environment=os.environ["PLAID_ENV"],
    )

@router.post("/link-token")
async def create_link_token():
    client = get_client()
    resp = client.link_token_create({
        "user": {"client_user_id": str(uuid.uuid4())},
        "products": ["transactions"],
        "client_name": "PFT",
        "country_codes": ["US"],
        "language": "en"
    })
    return resp["link_token"]

@router.post("/exchange")
async def exchange_public_token(data: dict):
    try:
        client = get_client()
        exchange = client.item.public_token.exchange(data["public_token"])
        async with SessionLocal() as db:
            db.add(Item(item_id=exchange["item_id"],
                        access_token=exchange["access_token"]))
            await db.commit()
        return {"status": "linked"}
    except errors.PlaidError as e:
        print(f"Plaid API error: {e}")
        return {"error": str(e)}
    except Exception as e:
        print(f"Internal server error: {e}")
        return {"error": "Internal server error"}
