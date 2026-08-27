from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
import plaid
from decimal import Decimal
from difflib import SequenceMatcher
import re
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from api.db import SessionLocal
from api.models import Account, Item, RawTransaction, Transaction
import os, uuid

router = APIRouter(prefix="/plaid")
ENCRYPTED_TOKEN_PREFIX = "fernet:v1:"


class PublicTokenExchange(BaseModel):
    public_token: str = Field(min_length=1)


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


async def _production_item_exists():
    if not is_production():
        return False
    async with SessionLocal() as db:
        result = await db.execute(select(Item.item_id).limit(1))
        return result.scalar_one_or_none() is not None


def _plaid_failure():
    return HTTPException(status_code=502, detail="Plaid request failed")

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
CARD_BENEFIT_DESCRIPTIONS = {
    "AMEX LULULEMON CREDIT",
    "AMEX RESY CREDIT",
}

def classify_transaction(transaction):
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
    if amount > 0 and _normalized_match_text(description) in CARD_BENEFIT_DESCRIPTIONS:
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
    return " ".join(re.findall(r"[A-Z0-9]+", (value or "").upper()))

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

def build_classifications(transactions):
    classifications = {
        transaction.transaction_id: classify_transaction(transaction)
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
        candidates = [
            expense
            for expense in expenses
            if expense.account_id == credit.account_id
            and expense.transaction_date < credit.transaction_date
            and abs(expense.amount) == credit.amount
            and _is_same_merchant_or_description(expense, credit)
        ]
        if len(candidates) == 1:
            classifications[credit.transaction_id] = ("refund", False, False)
            refund_matches += 1

    transfer_candidates = {
        transaction.transaction_id: []
        for transaction in transactions
        if classifications[transaction.transaction_id][0] in {"transfer", "payment"}
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

@router.post("/link-token")
async def create_link_token():
    _require_production_link_enabled()
    if await _production_item_exists():
        raise HTTPException(status_code=409, detail="Production pilot Item already exists")

    client = get_client()
    client_user_id = (
        os.environ["PLAID_PILOT_USER_ID"] if is_production() else str(uuid.uuid4())
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
    request = LinkTokenCreateRequest(
        **request_data,
    )
    try:
        resp = client.link_token_create(request)
    except plaid.ApiException as exc:
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
    if await _production_item_exists():
        raise HTTPException(status_code=409, detail="Production pilot Item already exists")

    try:
        client = get_client()
        request = ItemPublicTokenExchangeRequest(public_token=data.public_token)
        exchange = client.item_public_token_exchange(request)
        async with SessionLocal() as db:
            db.add(
                Item(
                    item_id=exchange["item_id"],
                    access_token=encrypt_access_token(exchange["access_token"]),
                )
            )
            await db.commit()
        return {"status": "linked"}
    except plaid.ApiException as exc:
        raise _plaid_failure() from exc

@router.get("/transactions")
async def get_transactions():
    async with SessionLocal() as db:
        result = await db.execute(
            select(Item).order_by(Item.created_at.desc()).limit(1)
        )
        item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="No linked Item")

    client = get_client()
    access_token = decrypt_access_token(item.access_token)
    added = []
    modified = []
    removed = []
    cursor = item.transactions_cursor
    pages_fetched = 0

    while True:
        request_data = {"access_token": access_token}
        if cursor is not None:
            request_data["cursor"] = cursor
        request = TransactionsSyncRequest(**request_data)
        try:
            response = client.transactions_sync(request).to_dict()
        except plaid.ApiException as exc:
            raise _plaid_failure() from exc
        added.extend(response["added"])
        modified.extend(response["modified"])
        removed.extend(response["removed"])
        cursor = response["next_cursor"]
        pages_fetched += 1
        if not response["has_more"]:
            break

    async with SessionLocal() as db:
        async with db.begin():
            for transaction in added:
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

            for transaction in modified:
                payload = jsonable_encoder(transaction)
                await db.execute(
                    update(RawTransaction)
                    .where(RawTransaction.transaction_id == transaction["transaction_id"])
                    .values(
                        account_id=transaction["account_id"],
                        transaction_date=transaction["date"],
                        payload=payload,
                        is_removed=False,
                    )
                )

            for transaction in removed:
                await db.execute(
                    update(RawTransaction)
                    .where(RawTransaction.transaction_id == transaction["transaction_id"])
                    .values(is_removed=True)
                )

            await db.execute(
                update(Item)
                .where(Item.item_id == item.item_id)
                .values(transactions_cursor=cursor)
            )

    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "next_cursor": cursor,
        "added_count": len(added),
        "modified_count": len(modified),
        "removed_count": len(removed),
        "pages_fetched": pages_fetched,
    }

@router.get("/accounts")
async def get_accounts():
    async with SessionLocal() as db:
        result = await db.execute(
            select(Item).order_by(Item.created_at.desc()).limit(1)
        )
        item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="No linked Item")

    client = get_client()
    request = AccountsGetRequest(access_token=decrypt_access_token(item.access_token))
    try:
        accounts = client.accounts_get(request).to_dict()["accounts"]
    except plaid.ApiException as exc:
        raise _plaid_failure() from exc

    async with SessionLocal() as db:
        async with db.begin():
            for account in accounts:
                values = {
                    "account_id": account["account_id"],
                    "item_id": item.item_id,
                    "name": account["name"],
                    "official_name": account.get("official_name"),
                    "type": getattr(account["type"], "value", account["type"]),
                    "subtype": getattr(account.get("subtype"), "value", account.get("subtype")),
                    "mask": account.get("mask"),
                }
                statement = insert(Account).values(**values)
                await db.execute(
                    statement.on_conflict_do_update(
                        index_elements=["account_id"],
                        set_={
                            **values,
                            "updated_at": func.now(),
                        },
                    )
                )

    return {
        "accounts": jsonable_encoder(accounts),
        "account_count": len(accounts),
    }

@router.post("/transactions/normalize")
async def normalize_transactions():
    async with SessionLocal() as db:
        result = await db.execute(
            select(RawTransaction).where(RawTransaction.is_removed.is_(False))
        )
        raw_transactions = result.scalars().all()

    async with SessionLocal() as db:
        async with db.begin():
            for raw_transaction in raw_transactions:
                payload = raw_transaction.payload
                category = payload.get("personal_finance_category")
                values = {
                    "transaction_id": raw_transaction.transaction_id,
                    "account_id": raw_transaction.account_id,
                    "transaction_date": raw_transaction.transaction_date,
                    "amount": -Decimal(str(payload["amount"])),
                    "merchant_name": payload.get("merchant_name"),
                    "description": payload.get("name"),
                    "plaid_category": category.get("primary") if category else None,
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
                            "updated_at": func.now(),
                        },
                    )
                )

    return {"normalized_count": len(raw_transactions)}

@router.post("/transactions/classify")
async def classify_transactions():
    async with SessionLocal() as db:
        result = await db.execute(select(Transaction))
        transactions = result.scalars().all()

    classifications, refund_matches = build_classifications(transactions)
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
