from calendar import monthrange
from datetime import date
from decimal import Decimal
import os
import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from api.db import SessionLocal
from api.models import Item, RawTransaction, Transaction


router = APIRouter(prefix="/analytics")
ZERO = Decimal("0")


def _money(value):
    return format(value.quantize(Decimal("0.01")), "f")


def _month_bounds(month):
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    try:
        year, month_number = (int(part) for part in month.split("-"))
        start_date = date(year, month_number, 1)
        end_date = date(year, month_number, monthrange(year, month_number)[1])
    except ValueError:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    return start_date, end_date


async def _active_month_rows(month, category=None):
    start_date, end_date = _month_bounds(month)
    statement = (
        select(Transaction, RawTransaction.is_removed)
        .join(
            RawTransaction,
            RawTransaction.transaction_id == Transaction.transaction_id,
        )
        .join(Item, Item.item_id == RawTransaction.item_id)
        .where(
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            RawTransaction.is_removed.is_(False),
            Item.status == "active",
            Item.user_id == os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user"),
        )
    )
    if category is not None:
        statement = statement.where(Transaction.plaid_category == category)

    async with SessionLocal() as db:
        result = await db.execute(statement)
        return result.all()


def summarize_monthly_transactions(rows):
    gross_spending = ZERO
    refunds = ZERO
    card_benefits = ZERO
    unclassified_count = 0
    categories = {}

    for transaction, is_removed in rows:
        if is_removed:
            continue

        amount = Decimal(transaction.amount)
        category = transaction.plaid_category or "UNCATEGORIZED"
        transaction_type = transaction.transaction_type

        if transaction_type is None:
            unclassified_count += 1
        elif (
            transaction_type == "expense"
            and transaction.is_spending is True
            and amount < 0
        ):
            value = -amount
            gross_spending += value
            category_values = categories.setdefault(category, [ZERO, ZERO])
            category_values[0] += value
        elif transaction_type == "refund" and amount > 0:
            refunds += amount
            category_values = categories.setdefault(category, [ZERO, ZERO])
            category_values[1] += amount
        elif transaction_type == "card_benefit" and amount > 0:
            card_benefits += amount

    category_breakdown = [
        {
            "category": category,
            "gross_spending": _money(values[0]),
            "refunds": _money(values[1]),
            "net_spending": _money(values[0] - values[1]),
        }
        for category, values in sorted(categories.items())
    ]
    return {
        "gross_spending": _money(gross_spending),
        "refunds": _money(refunds),
        "card_benefits": _money(card_benefits),
        "net_spending": _money(gross_spending - refunds - card_benefits),
        "category_breakdown": category_breakdown,
        "unclassified_count": unclassified_count,
    }


def summarize_category_transactions(rows, category):
    gross_spending = ZERO
    refunds = ZERO
    transaction_count = 0

    for transaction, is_removed in rows:
        if is_removed or transaction.plaid_category != category:
            continue
        amount = Decimal(transaction.amount)
        if (
            transaction.transaction_type == "expense"
            and transaction.is_spending is True
            and amount < 0
        ):
            gross_spending -= amount
            transaction_count += 1
        elif transaction.transaction_type == "refund" and amount > 0:
            refunds += amount
            transaction_count += 1

    return {
        "gross_spending": _money(gross_spending),
        "refunds": _money(refunds),
        "net_spending": _money(gross_spending - refunds),
        "transaction_count": transaction_count,
    }


def category_transaction_details(rows, category):
    relevant = []
    for transaction, is_removed in rows:
        if (
            is_removed
            or transaction.plaid_category != category
            or transaction.transaction_type not in {"expense", "refund"}
        ):
            continue
        relevant.append(transaction)

    relevant.sort(
        key=lambda transaction: (transaction.transaction_date, transaction.transaction_id),
        reverse=True,
    )
    return [
        {
            "transaction_id": transaction.transaction_id,
            "transaction_date": transaction.transaction_date.isoformat(),
            "merchant_name": transaction.merchant_name,
            "description": transaction.description,
            "amount": _money(Decimal(transaction.amount)),
            "transaction_type": transaction.transaction_type,
            "plaid_category": transaction.plaid_category,
        }
        for transaction in relevant
    ]


@router.get("/monthly")
async def monthly_spending(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    rows = await _active_month_rows(month)
    return {"month": month, **summarize_monthly_transactions(rows)}


@router.get("/category")
async def category_spending(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    category: str = Query(..., min_length=1),
):
    rows = await _active_month_rows(month, category)
    return {
        "month": month,
        "category": category,
        **summarize_category_transactions(rows, category),
    }


@router.get("/transactions")
async def category_transactions(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    category: str = Query(..., min_length=1),
):
    rows = await _active_month_rows(month, category)
    transactions = category_transaction_details(rows, category)
    return {
        "month": month,
        "category": category,
        "transactions": transactions,
        "transaction_count": len(transactions),
    }
