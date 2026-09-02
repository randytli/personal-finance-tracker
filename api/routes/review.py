import os
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert

from api.classification import effective_classification, validate_manual_override
from api.db import SessionLocal
from api.models import (
    Account,
    Item,
    ManualClassificationOverride,
    RawTransaction,
    Transaction,
)


router = APIRouter(prefix="/review")
TransactionType = Literal[
    "expense", "refund", "income", "card_benefit", "payment", "transfer", "adjustment"
]


class OverrideRequest(BaseModel):
    transaction_type: TransactionType


def _user_id():
    return os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user")


def _money(value):
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def _transaction_scope(transaction_id):
    return (
        select(Transaction, Account, Item, RawTransaction.is_removed)
        .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
        .join(Item, Item.item_id == RawTransaction.item_id)
        .join(
            Account,
            (Account.account_id == Transaction.account_id)
            & (Account.item_id == Item.item_id),
        )
        .where(
            Transaction.transaction_id == transaction_id,
            Item.user_id == _user_id(),
            Item.status == "active",
            RawTransaction.is_removed.is_(False),
        )
    )


def _review_ordering():
    return (
        case((Account.type == "credit", 1), else_=0),
        Transaction.transaction_date,
        Transaction.transaction_id,
    )


def _result(transaction, override_type):
    effective_type, effective_spending, effective_internal = effective_classification(
        transaction, override_type
    )
    return {
        "transaction_id": transaction.transaction_id,
        "automatic_transaction_type": transaction.transaction_type,
        "override_transaction_type": override_type,
        "effective_transaction_type": effective_type,
        "effective_is_spending": effective_spending,
        "effective_is_internal_transfer": effective_internal,
    }


@router.get("/transactions")
async def transactions_needing_review(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = (
        Item.user_id == _user_id(),
        Item.status == "active",
        RawTransaction.is_removed.is_(False),
        Transaction.transaction_type.is_(None),
        ManualClassificationOverride.transaction_type.is_(None),
    )
    joins = (
        (RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id),
        (Item, Item.item_id == RawTransaction.item_id),
        (
            Account,
            (Account.account_id == Transaction.account_id)
            & (Account.item_id == Item.item_id),
        ),
    )
    async with SessionLocal() as db:
        count_statement = select(func.count(Transaction.transaction_id))
        for model, condition in joins:
            count_statement = count_statement.join(model, condition)
        count_statement = count_statement.outerjoin(
            ManualClassificationOverride,
            ManualClassificationOverride.transaction_id == Transaction.transaction_id,
        ).where(*filters)
        total = await db.scalar(count_statement)

        statement = select(Transaction, Account, Item)
        for model, condition in joins:
            statement = statement.join(model, condition)
        statement = (
            statement.outerjoin(
                ManualClassificationOverride,
                ManualClassificationOverride.transaction_id == Transaction.transaction_id,
            )
            .where(*filters)
            .order_by(*_review_ordering())
            .offset(offset)
            .limit(limit)
        )
        rows = (await db.execute(statement)).all()

    return {
        "total": total or 0,
        "transactions": [
            {
                "transaction_id": transaction.transaction_id,
                "transaction_date": transaction.transaction_date.isoformat(),
                "institution_name": item.institution_name,
                "account_name": account.name,
                "account_mask": account.mask,
                "account_type": account.type,
                "merchant_name": transaction.merchant_name,
                "description": transaction.description,
                "amount": _money(transaction.amount),
                "plaid_category": transaction.plaid_category,
                "automatic_transaction_type": transaction.transaction_type,
                "override_transaction_type": None,
                "effective_transaction_type": None,
            }
            for transaction, account, item in rows
        ],
    }


@router.put("/transactions/{transaction_id}/override")
async def set_override(transaction_id: str, request: OverrideRequest):
    actor = _user_id()
    async with SessionLocal() as db:
        async with db.begin():
            row = (await db.execute(_transaction_scope(transaction_id))).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="transaction not found")
            transaction, _, _, _ = row
            error = validate_manual_override(transaction, request.transaction_type)
            if error:
                raise HTTPException(status_code=422, detail=error)
            values = {
                "transaction_id": transaction_id,
                "transaction_type": request.transaction_type,
                "created_by": actor,
                "updated_by": actor,
                "cleared_by": None,
                "cleared_at": None,
            }
            await db.execute(
                insert(ManualClassificationOverride)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["transaction_id"],
                    set_={
                        "transaction_type": request.transaction_type,
                        "updated_by": actor,
                        "updated_at": func.now(),
                        "cleared_by": None,
                        "cleared_at": None,
                    },
                )
            )
    return _result(transaction, request.transaction_type)


@router.delete("/transactions/{transaction_id}/override")
async def clear_override(transaction_id: str):
    actor = _user_id()
    async with SessionLocal() as db:
        async with db.begin():
            row = (await db.execute(_transaction_scope(transaction_id))).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="transaction not found")
            transaction, _, _, _ = row
            await db.execute(
                update(ManualClassificationOverride)
                .where(ManualClassificationOverride.transaction_id == transaction_id)
                .values(
                    transaction_type=None,
                    updated_by=actor,
                    updated_at=func.now(),
                    cleared_by=actor,
                    cleared_at=func.now(),
                )
            )
    return _result(transaction, None)
