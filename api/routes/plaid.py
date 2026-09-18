from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
import json
import logging
import plaid
from decimal import Decimal
from difflib import SequenceMatcher
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
from sqlalchemy.dialects.postgresql import insert
from api.db import SessionLocal
from api.models import Account, Item, RawTransaction, Transaction, LegacyConsumerRow, ManualClassificationOverride
from api.classification import INTERNAL_TRANSFER_TYPES
from api.consumer_scope import initial_consumer_scope, account_type_drift
from api.card_benefits import (AMERICAN_EXPRESS_INSTITUTION_ID,
    AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES, CARD_BENEFIT_DESCRIPTIONS,
    normalized_benefit_text)
from api.statement_semantics import normalized_raw_values, statement_classification, lock_consumer_derivation
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

SPENDING_CATEGORIES = {
    "BANK_FEES",
    "ENTERTAINMENT",
    "FOOD_AND_DRINK",
    "GENERAL_MERCHANDISE",
    "GENERAL_SERVICES",
    "GOVERNMENT_AND_NON_PROFIT",
    "HOME_IMPROVEMENT",
    "MEDICAL",
    "PERSONAL_CARE",
    "RENT_AND_UTILITIES",
    "TRANSPORTATION",
    "TRAVEL",
}
CREDIT_CARD_PAYMENT_DESCRIPTIONS = {
    "PAYMENT THANK YOU MOBILE",
}

def classify_transaction(
    transaction,
    credit_account_ids=frozenset(),
    amex_benefit_account_ids=frozenset(),
    amex_merchant_benefit_account_ids=None,
):
    seed = statement_classification(getattr(transaction, "statement_kind", None), transaction.amount)
    if seed is not None:
        return seed
    category = transaction.plaid_category
    amount = transaction.amount
    description = (transaction.description or "").upper()

    if amount > 0 and re.search(
        r"\b(?:INTRST\s+PYMNT|INTEREST\s+(?:PAYMENT|PAID|EARNED|CREDIT))\b",
        description,
    ):
        return "income", False, False
    if category == "LOAN_PAYMENTS":
        return "payment", False, None
    if (
        amount > 0
        and transaction.account_id in credit_account_ids
        and category == "LOAN_DISBURSEMENTS"
        and _normalized_match_text(description) in CREDIT_CARD_PAYMENT_DESCRIPTIONS
    ):
        return "payment", False, None
    normalized_description = _normalized_match_text(description)
    merchant_benefit_account_ids = (
        amex_merchant_benefit_account_ids or {}
    ).get(normalized_description, frozenset())
    if (
        amount > 0
        and transaction.account_id in amex_benefit_account_ids
        and (
            normalized_description in CARD_BENEFIT_DESCRIPTIONS
            or (normalized_description == "WALMART"
                and amount == Decimal("13.81")
                and transaction.account_id in merchant_benefit_account_ids)
            or (normalized_description != "WALMART"
                and transaction.account_id in merchant_benefit_account_ids)
        )
    ):
        return "card_benefit", False, False
    if category in {"TRANSFER_IN", "TRANSFER_OUT"}:
        return "transfer", False, None
    if amount < 0 and category in SPENDING_CATEGORIES:
        return "expense", True, False
    if amount > 0 and (
        category == "INCOME"
    ):
        return "income", False, False
    return None, None, None

def _normalized_match_text(value):
    return normalized_benefit_text(value)

def _is_same_merchant_or_description(expense, credit):
    expense_merchant = _normalized_match_text(expense.merchant_name)
    credit_merchant = _normalized_match_text(credit.merchant_name)
    if expense_merchant and credit_merchant:
        return expense_merchant == credit_merchant

    expense_description = _normalized_match_text(expense.description)
    credit_description = _normalized_match_text(credit.description)
    if len(expense_description) < 5 or len(credit_description) < 5:
        return False
    return SequenceMatcher(
        None,
        expense_description,
        credit_description,
    ).ratio() >= 0.9

def _has_exact_merchant_or_description(expense, credit):
    expense_merchant = _normalized_match_text(expense.merchant_name)
    credit_merchant = _normalized_match_text(credit.merchant_name)
    expense_description = _normalized_match_text(expense.description)
    credit_description = _normalized_match_text(credit.description)
    return bool(
        (expense_merchant and expense_merchant == credit_merchant)
        or (
            expense_description
            and expense_description == credit_description
        )
    )


def build_classifications(
    transactions,
    credit_account_ids=frozenset(),
    amex_benefit_account_ids=frozenset(),
    amex_merchant_benefit_account_ids=None,
    active_manual_types=None,
):
    active_manual_types = active_manual_types or {}
    classifications = {
        transaction.transaction_id: classify_transaction(
            transaction,
            credit_account_ids,
            amex_benefit_account_ids,
            amex_merchant_benefit_account_ids,
        )
        for transaction in transactions
    }
    expenses = [
        transaction
        for transaction in transactions
        if classifications[transaction.transaction_id][0] == "expense"
    ]
    refund_matches = 0

    for credit in transactions:
        if credit.amount <= 0 or classifications[credit.transaction_id][0] is not None:
            continue
        same_day_candidates = [
            expense
            for expense in expenses
            if expense.account_id == credit.account_id
            and expense.transaction_date == credit.transaction_date
            and abs(expense.amount) == credit.amount
            and expense.plaid_category == credit.plaid_category
            and _has_exact_merchant_or_description(expense, credit)
        ]
        if len(same_day_candidates) == 1:
            classifications[credit.transaction_id] = ("refund", False, False)
            refund_matches += 1
            continue

        historical_candidates = [
            expense
            for expense in expenses
            if expense.account_id == credit.account_id
            and expense.transaction_date < credit.transaction_date
            and abs(expense.amount) == credit.amount
            and _is_same_merchant_or_description(expense, credit)
        ]
        if len(historical_candidates) == 1:
            classifications[credit.transaction_id] = ("refund", False, False)
            refund_matches += 1
            continue

        recent_exact_candidates = [
            expense
            for expense in historical_candidates
            if (credit.transaction_date - expense.transaction_date).days <= 7
            and _normalized_match_text(expense.description)
            == _normalized_match_text(credit.description)
        ]
        if len(recent_exact_candidates) == 1:
            classifications[credit.transaction_id] = ("refund", False, False)
            refund_matches += 1

    transfer_candidates = {
        transaction.transaction_id: []
        for transaction in transactions
        if classifications[transaction.transaction_id][0] in INTERNAL_TRANSFER_TYPES
        and (active_manual_types.get(transaction.transaction_id) is None
             or active_manual_types[transaction.transaction_id] in INTERNAL_TRANSFER_TYPES)
    }
    eligible_transfers = [
        transaction
        for transaction in transactions
        if transaction.transaction_id in transfer_candidates
    ]
    for index, transaction in enumerate(eligible_transfers):
        for counterpart in eligible_transfers[index + 1:]:
            if (
                transaction.account_id != counterpart.account_id
                and transaction.amount == -counterpart.amount
                and transaction.amount != 0
                and abs(
                    (transaction.transaction_date - counterpart.transaction_date).days
                ) <= 3
            ):
                transfer_candidates[transaction.transaction_id].append(counterpart)
                transfer_candidates[counterpart.transaction_id].append(transaction)

    for transaction in eligible_transfers:
        candidates = transfer_candidates[transaction.transaction_id]
        if len(candidates) != 1:
            continue
        counterpart = candidates[0]
        if len(transfer_candidates[counterpart.transaction_id]) != 1:
            continue
        for matched_transaction in (transaction, counterpart):
            transaction_type = classifications[matched_transaction.transaction_id][0]
            classifications[matched_transaction.transaction_id] = (
                transaction_type,
                False,
                True,
            )

    return classifications, refund_matches

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
    item = await _get_item(item_id, ("pending", "active", "disabled"))
    if item.status == "active" and data.status == "disabled":
        raise HTTPException(status_code=409, detail="Active Items cannot be disabled through this endpoint")
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(select(Item).where(Item.item_id == item_id).with_for_update())
            if data.status == "active":
                await validate_consumer_activation(db, item_id)
            await db.execute(
                update(Item).where(Item.item_id == item_id).values(status=data.status)
            )
    return {"item_id": item_id, "status": data.status}


async def validate_consumer_activation(db, item_id):
    accounts = {a.account_id: a for a in (await db.execute(
        select(Account).where(Account.item_id == item_id)
    )).scalars()}
    if not any(a.consumer_transactions_enabled for a in accounts.values()):
        raise HTTPException(409, "Discover at least one enabled consumer account before activation")
    rows = (await db.execute(
        select(RawTransaction, Transaction, LegacyConsumerRow)
        .outerjoin(Transaction, Transaction.transaction_id == RawTransaction.transaction_id)
        .outerjoin(LegacyConsumerRow, LegacyConsumerRow.transaction_id == RawTransaction.transaction_id)
        .where(RawTransaction.item_id == item_id)
    )).all()
    for raw, normalized, legacy in rows:
        account = accounts.get(raw.account_id)
        if account is None or (normalized and normalized.account_id != raw.account_id):
            raise HTTPException(409, "Consumer transaction account ownership is inconsistent")
        if not account.consumer_transactions_enabled:
            if (legacy is None or legacy.item_id != item_id or legacy.account_id != raw.account_id
                    or (normalized and legacy.normalized_account_id != normalized.account_id)):
                raise HTTPException(409, "New disabled-account consumer data requires investigation")


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

@router.get("/transactions")
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
    accepted_added, accepted_modified, accepted_removed = [], [], []
    skipped = {"added": 0, "modified": 0, "removed": 0}
    async with SessionLocal() as db:
        async with db.begin():
            item = (await db.execute(select(Item).where(
                Item.item_id == item_id, Item.user_id == _user_id(),
                Item.status.in_(("pending", "active")),
            ).with_for_update())).scalar_one_or_none()
            if item is None or item.transactions_cursor != starting_cursor:
                raise HTTPException(409, "Item changed during sync; retry")
            accounts = {a.account_id: a for a in (await db.execute(
                select(Account).where(Account.item_id == item_id).with_for_update()
            )).scalars()}
            ids = {t["transaction_id"] for t in added + modified + removed}
            existing = {r.transaction_id: r for r in (await db.execute(
                select(RawTransaction).where(RawTransaction.transaction_id.in_(ids))
            )).scalars()}
            batch_owners = {}
            for kind, batch, accepted in (
                ("added", added, accepted_added), ("modified", modified, accepted_modified),
            ):
                for transaction in batch:
                    tid = transaction["transaction_id"]
                    if tid in batch_owners and batch_owners[tid] != transaction["account_id"]:
                        raise HTTPException(409, "Conflicting account ownership within sync batch")
                    batch_owners[tid] = transaction["account_id"]
                    account = accounts.get(transaction["account_id"])
                    prior = existing.get(transaction["transaction_id"])
                    if prior and prior.source != "plaid":
                        raise HTTPException(409, "Plaid cannot modify statement-source rows")
                    if account is None:
                        raise HTTPException(409, "Unknown or conflicting account; discover accounts before retrying")
                    if prior and (prior.item_id != item_id or prior.account_id != transaction["account_id"]):
                        raise HTTPException(409, "Transaction ownership conflict")
                    if account.consumer_transactions_enabled:
                        accepted.append(transaction)
                    else:
                        skipped[kind] += 1
            for transaction in removed:
                prior = existing.get(transaction["transaction_id"])
                if prior is None:
                    # An added/modified row can also be removed in a later page
                    # of the same sync batch, before it exists in PostgreSQL.
                    account_id = batch_owners.get(transaction["transaction_id"])
                    if account_id is not None:
                        if accounts[account_id].consumer_transactions_enabled:
                            accepted_removed.append(transaction)
                        else:
                            skipped["removed"] += 1
                    continue
                account = accounts.get(prior.account_id)
                if prior.source != "plaid":
                    raise HTTPException(409, "Plaid cannot remove statement-source rows")
                if prior.item_id != item_id or account is None:
                    raise HTTPException(409, "Removed transaction ownership conflict")
                if account.consumer_transactions_enabled:
                    accepted_removed.append(transaction)
                else:
                    skipped["removed"] += 1
            from statement_imports.persistence import block_plaid_overlap, ImportBlocked
            try:
                await block_plaid_overlap(db, item_id, accepted_added + accepted_modified)
            except ImportBlocked as exc:
                raise HTTPException(409, str(exc)) from None
            for transaction in accepted_added:
                payload = jsonable_encoder(transaction)
                await db.execute(
                    insert(RawTransaction)
                    .values(
                        transaction_id=transaction["transaction_id"],
                        item_id=item.item_id,
                        account_id=transaction["account_id"],
                        transaction_date=transaction["date"],
                        payload=payload,
                    )
                    .on_conflict_do_nothing(index_elements=["transaction_id"])
                )

            for transaction in accepted_modified:
                payload = jsonable_encoder(transaction)
                statement = insert(RawTransaction).values(
                        transaction_id=transaction["transaction_id"],
                        item_id=item_id,
                        account_id=transaction["account_id"],
                        transaction_date=transaction["date"],
                        payload=payload,
                        is_removed=False,
                )
                await db.execute(statement.on_conflict_do_update(
                    index_elements=["transaction_id"],
                    set_={"transaction_date": transaction["date"], "payload": payload, "is_removed": False},
                    where=(RawTransaction.item_id == item_id)
                        & (RawTransaction.account_id == transaction["account_id"])
                        & (RawTransaction.source == "plaid"),
                ))

            # Also catch concurrent cross-Item inserts that raced the initial lookup.
            for transaction in accepted_added + accepted_modified:
                owner = (await db.execute(select(RawTransaction.item_id, RawTransaction.account_id, RawTransaction.source)
                    .where(RawTransaction.transaction_id == transaction["transaction_id"]))).one()
                if owner != (item_id, transaction["account_id"], "plaid"):
                    raise HTTPException(409, "Transaction ownership conflict")

            for transaction in accepted_removed:
                await db.execute(
                    update(RawTransaction)
                    .where(
                        RawTransaction.transaction_id == transaction["transaction_id"],
                        RawTransaction.item_id == item.item_id,
                        RawTransaction.source == "plaid",
                    )
                    .values(is_removed=True)
                )

            await db.execute(
                update(Item)
                .where(Item.item_id == item.item_id)
                .values(transactions_cursor=cursor)
            )

    return {
        "added": accepted_added,
        "modified": accepted_modified,
        "removed": accepted_removed,
        "next_cursor": cursor,
        "added_count": len(accepted_added),
        "modified_count": len(accepted_modified),
        "removed_count": len(accepted_removed),
        "skipped_disabled_counts": skipped,
        "pages_fetched": pages_fetched,
    }

@router.get("/accounts")
async def get_accounts(item_id: str = Query(..., min_length=1)):
    item = await _get_item(item_id, ("pending", "active"))

    client = get_client()
    request = AccountsGetRequest(access_token=decrypt_access_token(item.access_token))
    try:
        accounts = client.accounts_get(request).to_dict()["accounts"]
    except plaid.ApiException as exc:
        raise _plaid_failure() from exc

    return await persist_account_metadata(item.item_id, accounts)


async def persist_account_metadata(item_id, accounts):
    drift = []
    safe_accounts = []
    async with SessionLocal() as db:
        async with db.begin():
            item = (await db.execute(select(Item).where(
                Item.item_id == item_id, Item.user_id == _user_id(),
                Item.status.in_(("active", "pending")),
            ).with_for_update())).scalar_one_or_none()
            if item is None:
                raise HTTPException(404, "Item not found")
            for account in accounts:
                existing = await db.get(Account, account["account_id"])
                if existing and existing.item_id != item_id:
                    raise HTTPException(409, "Account ownership conflict")
                values = {
                    "account_id": account["account_id"],
                    "item_id": item.item_id,
                    "name": account["name"],
                    "official_name": account.get("official_name"),
                    "type": getattr(account.get("type"), "value", account.get("type")) or "unknown",
                    "subtype": getattr(account.get("subtype"), "value", account.get("subtype")),
                    "mask": account.get("mask"),
                }
                values["consumer_transactions_enabled"] = (
                    existing.consumer_transactions_enabled if existing
                    else initial_consumer_scope(values["type"])
                )
                if existing:
                    change = account_type_drift(existing, values["type"], values["subtype"])
                    if change:
                        drift.append(change)
                safe_accounts.append({k: v for k, v in values.items() if k != "item_id"})
                statement = insert(Account).values(**values)
                saved_id = await db.scalar(
                    statement.on_conflict_do_update(
                        index_elements=["account_id"],
                        set_={
                            "name": values["name"],
                            "official_name": values["official_name"],
                            "type": values["type"],
                            "subtype": values["subtype"],
                            "mask": values["mask"],
                            "updated_at": func.now(),
                        },
                        where=Account.item_id == item_id,
                    ).returning(Account.account_id)
                )
                if saved_id is None:
                    raise HTTPException(409, "Account ownership conflict")

    return {
        "accounts": safe_accounts,
        "account_count": len(accounts),
        "type_drift": drift,
    }

@router.post("/transactions/normalize")
async def normalize_transactions(item_id: str = Query(..., min_length=1)):
    async with SessionLocal.begin() as guard:
        await lock_consumer_derivation(guard, _user_id())
        return await _normalize_transactions(item_id)


async def _normalize_transactions(item_id):
    item = await _get_item(item_id, ("pending", "active"))
    async with SessionLocal() as db:
        result = await db.execute(
            select(RawTransaction).join(Account,
                (Account.account_id == RawTransaction.account_id)
                & (Account.item_id == RawTransaction.item_id)).where(
                RawTransaction.item_id == item.item_id,
                RawTransaction.is_removed.is_(False),
                Account.consumer_transactions_enabled.is_(True),
            )
        )
        raw_transactions = result.scalars().all()

    async with SessionLocal() as db:
        async with db.begin():
            for raw_transaction in raw_transactions:
                values = {
                    "transaction_id": raw_transaction.transaction_id,
                    "account_id": raw_transaction.account_id,
                    "transaction_date": raw_transaction.transaction_date,
                    **normalized_raw_values(raw_transaction),
                    "transaction_type": None,
                    "is_spending": None,
                    "is_internal_transfer": None,
                }
                statement = insert(Transaction).values(**values)
                await db.execute(
                    statement.on_conflict_do_update(
                        index_elements=["transaction_id"],
                        set_={
                            "account_id": values["account_id"],
                            "transaction_date": values["transaction_date"],
                            "amount": values["amount"],
                            "merchant_name": values["merchant_name"],
                            "description": values["description"],
                            "plaid_category": values["plaid_category"],
                            "statement_kind": values["statement_kind"],
                            "updated_at": func.now(),
                        },
                    )
                )

    return {"normalized_count": len(raw_transactions)}

@router.post("/transactions/classify")
async def classify_transactions():
    async with SessionLocal.begin() as guard:
        await lock_consumer_derivation(guard, _user_id())
        return await _classify_transactions()


async def _classify_transactions():
    async with SessionLocal() as db:
        result = await db.execute(
            select(Transaction, ManualClassificationOverride.transaction_type)
            .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
            .join(Item, Item.item_id == RawTransaction.item_id)
            .join(Account, (Account.account_id == Transaction.account_id)
                  & (Account.account_id == RawTransaction.account_id)
                  & (Account.item_id == Item.item_id))
            .outerjoin(ManualClassificationOverride,
                       (ManualClassificationOverride.transaction_id == Transaction.transaction_id)
                       & ManualClassificationOverride.cleared_at.is_(None))
            .where(
                Account.consumer_transactions_enabled.is_(True),
                Item.user_id == _user_id(),
                Item.status.in_(("active", "pending")),
                RawTransaction.is_removed.is_(False),
            )
        )
        classified_rows = result.all()
        transactions = [transaction for transaction, _ in classified_rows]
        active_manual_types = {
            transaction.transaction_id: manual_type
            for transaction, manual_type in classified_rows if manual_type is not None
        }
        result = await db.execute(
            select(Account.account_id)
            .join(Item, Item.item_id == Account.item_id)
            .where(
                Account.type == "credit",
                Account.consumer_transactions_enabled.is_(True),
                Item.user_id == _user_id(),
                Item.status.in_(("active", "pending")),
            )
        )
        credit_account_ids = set(result.scalars().all())
        result = await db.execute(
            select(Account.account_id, Account.name)
            .join(Item, Item.item_id == Account.item_id)
            .where(
                Account.type == "credit",
                Account.consumer_transactions_enabled.is_(True),
                Item.institution_id == AMERICAN_EXPRESS_INSTITUTION_ID,
                Item.user_id == _user_id(),
                Item.status.in_(("active", "pending")),
            )
        )
        amex_credit_accounts = result.all()
        amex_benefit_account_ids = {
            account_id for account_id, _ in amex_credit_accounts
        }
        amex_merchant_benefit_account_ids = {
            description: {
                account_id
                for account_id, account_name in amex_credit_accounts
                if _normalized_match_text(account_name) == required_account_name
            }
            for description, required_account_name in (
                AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES.items()
            )
        }

    classifications, refund_matches = build_classifications(
        transactions,
        credit_account_ids,
        amex_benefit_account_ids,
        amex_merchant_benefit_account_ids,
        active_manual_types=active_manual_types,
    )
    internal_transfer_matches = sum(
        1 for values in classifications.values() if values[2] is True
    ) // 2
    counts = {
        "card_benefit": 0,
        "expense": 0,
        "income": 0,
        "payment": 0,
        "refund": 0,
        "transfer": 0,
        "unclassified": 0,
    }
    async with SessionLocal() as db:
        async with db.begin():
            for transaction in transactions:
                transaction_type, is_spending, is_internal_transfer = (
                    classifications[transaction.transaction_id]
                )
                await db.execute(
                    update(Transaction)
                    .where(Transaction.transaction_id == transaction.transaction_id)
                    .values(
                        transaction_type=transaction_type,
                        is_spending=is_spending,
                        is_internal_transfer=is_internal_transfer,
                    )
                )
                counts[transaction_type or "unclassified"] += 1

    return {
        "classified_count": len(transactions) - counts["unclassified"],
        "refund_matches": refund_matches,
        "internal_transfer_matches": internal_transfer_matches,
        **counts,
    }
