from cryptography.fernet import Fernet, InvalidToken
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import json
import logging
import plaid
import re
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_transactions import LinkTokenTransactions
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from api.db import SessionLocal
from api.models import Account, Item, RawTransaction
from api.statement_semantics import lock_consumer_derivation
from api.services.derivation import (
    activate_item, classify_active_transactions, normalize_item_transactions,
    preview_pending_classification, validate_consumer_activation,
)
from api.services.persistence import (
    persist_account_metadata as persist_account_metadata_in_session,
    persist_consumer_transactions as persist_consumer_transactions_in_session,
)
import os, uuid

router = APIRouter(prefix="/plaid")
ENCRYPTED_TOKEN_PREFIX = "fernet:v1:"
logger = logging.getLogger(__name__)


class PublicTokenExchange(BaseModel):
    public_token: str = Field(min_length=1)
    institution_id: str = Field(pattern=r"^ins_[A-Za-z0-9]+$")
    institution_name: str = Field(min_length=1, max_length=200)


class ItemStatusUpdate(BaseModel):
    status: str


def is_production():
    return os.environ.get("PLAID_ENV", "").lower() == "production"


def _fernet():
    key = os.environ.get("PLAID_TOKEN_ENCRYPTION_KEY", "")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PLAID_TOKEN_ENCRYPTION_KEY is missing or invalid") from exc


def encrypt_access_token(access_token):
    if not is_production():
        return access_token
    ciphertext = _fernet().encrypt(access_token.encode()).decode()
    return f"{ENCRYPTED_TOKEN_PREFIX}{ciphertext}"


def decrypt_access_token(stored_token):
    if not is_production():
        return stored_token
    if not stored_token.startswith(ENCRYPTED_TOKEN_PREFIX):
        raise RuntimeError("Production access token is not encrypted")
    ciphertext = stored_token.removeprefix(ENCRYPTED_TOKEN_PREFIX)
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Production access token cannot be decrypted") from exc


def validate_runtime_configuration():
    environment = os.environ.get("PLAID_ENV", "").lower()
    if environment not in {"sandbox", "production"}:
        raise RuntimeError("PLAID_ENV must be sandbox or production")
    for name in ("PLAID_CLIENT_ID", "PLAID_SECRET"):
        if not os.environ.get(name):
            raise RuntimeError(f"{name} is required")
    if not is_production():
        return

    for name in (
        "EXPECTED_DATABASE_NAME",
        "PLAID_PILOT_USER_ID",
        "PLAID_REDIRECT_URI",
        "PLAID_TOKEN_ENCRYPTION_KEY",
    ):
        if not os.environ.get(name):
            raise RuntimeError(f"{name} is required in Production")
    if not os.environ["PLAID_REDIRECT_URI"].startswith("https://"):
        raise RuntimeError("PLAID_REDIRECT_URI must use HTTPS in Production")
    enabled = os.environ.get("PLAID_PILOT_LINK_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise RuntimeError("PLAID_PILOT_LINK_ENABLED must be true or false")
    _fernet()


def _require_production_link_enabled():
    if is_production() and os.environ.get(
        "PLAID_PILOT_LINK_ENABLED", "false"
    ).lower() != "true":
        raise HTTPException(status_code=403, detail="Production pilot Link is disabled")


def _user_id():
    return os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user")


async def _institution_exists(institution_id):
    if not is_production():
        return False
    async with SessionLocal() as db:
        result = await db.execute(
            select(Item.item_id).where(
                Item.user_id == _user_id(),
                Item.institution_id == institution_id,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None


async def _get_item(item_id, allowed_statuses=("active",)):
    async with SessionLocal() as db:
        result = await db.execute(select(Item).where(
            Item.item_id == item_id,
            Item.user_id == _user_id(),
            Item.status.in_(allowed_statuses),
        ))
        item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def _plaid_failure():
    return HTTPException(status_code=502, detail="Plaid request failed")


def _sanitize_plaid_diagnostic(value, max_length=300):
    if not isinstance(value, str):
        return None
    sanitized = " ".join(value.split())
    secret = os.environ.get("PLAID_SECRET")
    if secret:
        sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = re.sub(
        r"(?i)\b(?:access|public|link)[_-]?token\b\s*[:=]\s*[^\s,;]+",
        "token=[REDACTED]",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)\b(?:access|public|link)-(?:sandbox|development|production)-[A-Za-z0-9_-]+",
        "[REDACTED]",
        sanitized,
    )
    return sanitized[:max_length] or None


def _log_link_token_plaid_error(exc):
    details = {}
    if isinstance(exc.body, (str, bytes)):
        try:
            details = json.loads(exc.body)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            details = {}
    if not isinstance(details, dict):
        details = {}

    error_type = _sanitize_plaid_diagnostic(details.get("error_type"), 100)
    error_code = _sanitize_plaid_diagnostic(details.get("error_code"), 100)
    message = _sanitize_plaid_diagnostic(
        details.get("display_message") or details.get("error_message")
    )
    request_id = _sanitize_plaid_diagnostic(details.get("request_id"), 100)
    logger.warning(
        "Plaid link-token request failed: error_type=%r error_code=%r "
        "message=%r request_id=%r",
        error_type,
        error_code,
        message,
        request_id,
    )

from api.classification_rules import (
    build_classifications, classify_transaction, zelle_confirmation_code,
    _normalized_match_text,
)

def get_client():
    environments = {
        "sandbox": plaid.Environment.Sandbox,
        "production": plaid.Environment.Production,
    }
    environment_name = os.environ.get("PLAID_ENV", "").lower()
    if environment_name not in environments:
        raise RuntimeError("PLAID_ENV must be sandbox or production")
    environment = environments[environment_name]
    configuration = plaid.Configuration(
        host=environment,
        api_key={
            "clientId": os.environ["PLAID_CLIENT_ID"],
            "secret": os.environ["PLAID_SECRET"],
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def fetch_transaction_pages(client, access_token, starting_cursor):
    """Fetch one Item's complete sync without mutating another Item's cursor."""
    added, modified, removed = [], [], []
    cursor = starting_cursor
    pages_fetched = 0
    while True:
        request_data = {"access_token": access_token}
        if cursor is not None:
            request_data["cursor"] = cursor
        try:
            response = client.transactions_sync(
                TransactionsSyncRequest(**request_data)
            ).to_dict()
        except plaid.ApiException as exc:
            raise _plaid_failure() from exc
        added.extend(response["added"])
        modified.extend(response["modified"])
        removed.extend(response["removed"])
        cursor = response["next_cursor"]
        pages_fetched += 1
        if not response["has_more"]:
            return added, modified, removed, cursor, pages_fetched

@router.get("/items")
async def get_items():
    async with SessionLocal() as db:
        result = await db.execute(
            select(Item).where(Item.user_id == _user_id()).order_by(Item.created_at)
        )
        items = result.scalars().all()
    return {"items": [item_metadata(item) for item in items]}


def item_metadata(item):
    return {
        "item_id": item.item_id,
        "institution_id": item.institution_id,
        "institution_name": item.institution_name,
        "status": item.status,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.patch("/items/{item_id}/status")
async def update_item_status(item_id: str, data: ItemStatusUpdate):
    if data.status not in {"active", "disabled"}:
        raise HTTPException(status_code=422, detail="status must be active or disabled")
    async with SessionLocal.begin() as db:
        if data.status == "active":
            return await activate_item(db, _user_id(), item_id)
        await lock_consumer_derivation(db, _user_id())
        item = await db.scalar(select(Item).where(
            Item.item_id == item_id, Item.user_id == _user_id(),
            Item.status.in_(("pending", "active", "disabled")),
        ).with_for_update())
        if item is None:
            raise HTTPException(404, "Item not found")
        if item.status == "active":
            raise HTTPException(409, "Active Items cannot be disabled through this endpoint")
        await db.execute(update(Item).where(Item.item_id == item_id).values(status="disabled"))
    return {"item_id": item_id, "status": "disabled"}


@router.get("/items/{item_id}/classification-preview")
async def get_pending_classification_preview(item_id: str):
    async with SessionLocal.begin() as db:
        return await preview_pending_classification(db, _user_id(), item_id)


@router.post("/link-token")
async def create_link_token():
    _require_production_link_enabled()

    client = get_client()
    client_user_id = (
        _user_id() if is_production() else str(uuid.uuid4())
    )
    request_data = {
        "user": LinkTokenCreateRequestUser(client_user_id=client_user_id),
        "products": [Products("transactions")],
        "client_name": "PFT",
        "country_codes": [CountryCode("US")],
        "language": "en",
    }
    if is_production():
        request_data["redirect_uri"] = os.environ["PLAID_REDIRECT_URI"]
        request_data["transactions"] = LinkTokenTransactions(days_requested=730)
    request = LinkTokenCreateRequest(
        **request_data,
    )
    try:
        resp = client.link_token_create(request)
    except plaid.ApiException as exc:
        _log_link_token_plaid_error(exc)
        raise _plaid_failure() from exc
    return resp["link_token"]

@router.post("/sandbox/public-token")
async def create_sandbox_public_token():
    if os.environ.get("PLAID_ENV", "").lower() != "sandbox":
        raise HTTPException(status_code=403, detail="Sandbox only")

    client = get_client()
    request = SandboxPublicTokenCreateRequest(
        institution_id="ins_109508",
        initial_products=[Products("transactions")],
    )
    try:
        resp = client.sandbox_public_token_create(request)
    except plaid.ApiException as exc:
        raise _plaid_failure() from exc
    return resp["public_token"]

@router.post("/exchange")
async def exchange_public_token(data: PublicTokenExchange):
    _require_production_link_enabled()
    institution_name = " ".join(data.institution_name.split())
    if not institution_name:
        raise HTTPException(status_code=422, detail="Institution metadata is required")
    if await _institution_exists(data.institution_id):
        raise HTTPException(status_code=409, detail="Institution is already connected")

    try:
        client = get_client()
        request = ItemPublicTokenExchangeRequest(public_token=data.public_token)
        exchange = client.item_public_token_exchange(request)
        item_response = client.item_get(
            ItemGetRequest(access_token=exchange["access_token"])
        ).to_dict()
        institution_id = item_response["item"].get("institution_id")
        if institution_id != data.institution_id:
            raise HTTPException(status_code=409, detail="Connected institution did not match selection")
        if await _institution_exists(institution_id):
            raise HTTPException(status_code=409, detail="Institution is already connected")
        institution = client.institutions_get_by_id(
            InstitutionsGetByIdRequest(
                institution_id=institution_id,
                country_codes=[CountryCode("US")],
            )
        ).to_dict()["institution"]
        if institution["name"].casefold() != institution_name.casefold():
            raise HTTPException(status_code=409, detail="Connected institution name did not match selection")
        async with SessionLocal() as db:
            db.add(
                Item(
                    item_id=exchange["item_id"],
                    user_id=_user_id(),
                    institution_id=institution_id,
                    institution_name=institution["name"],
                    status="pending",
                    access_token=encrypt_access_token(exchange["access_token"]),
                )
            )
            try:
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                raise HTTPException(status_code=409, detail="Institution is already connected") from exc
        return {"status": "pending", "item_id": exchange["item_id"]}
    except plaid.ApiException as exc:
        raise _plaid_failure() from exc

@router.post("/transactions")
async def get_transactions(item_id: str = Query(..., min_length=1)):
    item = await _get_item(item_id, ("pending", "active"))
    async with SessionLocal() as db:
        discovered = await db.scalar(select(func.count()).select_from(Account).where(Account.item_id == item_id))
        if not discovered:
            raise HTTPException(409, "Discover accounts before transaction sync")

    client = get_client()
    access_token = decrypt_access_token(item.access_token)
    added, modified, removed, cursor, pages_fetched = fetch_transaction_pages(
        client, access_token, item.transactions_cursor
    )

    return await persist_consumer_transactions(
        item.item_id, item.transactions_cursor, added, modified, removed, cursor, pages_fetched,
    )


async def persist_consumer_transactions(item_id, starting_cursor, added, modified, removed, cursor, pages_fetched):
    async with SessionLocal.begin() as db:
        return await persist_consumer_transactions_in_session(
            db, _user_id(), item_id, starting_cursor, added, modified, removed, cursor, pages_fetched,
        )

@router.post("/accounts")
async def get_accounts(item_id: str = Query(..., min_length=1)):
    item = await _get_item(item_id, ("pending", "active"))

    client = get_client()
    request = AccountsGetRequest(access_token=decrypt_access_token(item.access_token))
    try:
        accounts = client.accounts_get(request).to_dict()["accounts"]
    except plaid.ApiException as exc:
        async with SessionLocal.begin() as db:
            await db.execute(update(Item).where(Item.item_id == item.item_id,
                                               Item.user_id == _user_id()).values(
                metadata_warning="metadata_refresh_failed",
                metadata_warning_at=datetime.now(timezone.utc)))
        raise _plaid_failure() from exc

    return await persist_account_metadata(item.item_id, accounts)


async def persist_account_metadata(item_id, accounts):
    async with SessionLocal.begin() as db:
        result = await persist_account_metadata_in_session(db, _user_id(), item_id, accounts)
        await db.execute(update(Item).where(Item.item_id == item_id, Item.user_id == _user_id())
                         .values(metadata_warning=None, metadata_warning_at=None))
        return result

@router.post("/transactions/normalize")
async def normalize_transactions(item_id: str = Query(..., min_length=1)):
    async with SessionLocal.begin() as db:
        return await normalize_item_transactions(db, _user_id(), item_id)


@router.post("/transactions/classify")
async def classify_transactions():
    async with SessionLocal.begin() as db:
        return await classify_active_transactions(db, _user_id())
