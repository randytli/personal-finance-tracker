from calendar import monthrange
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from api.db import SessionLocal
from api.models import RawTransaction, Transaction


router = APIRouter(prefix="/analytics")
ZERO = Decimal("0")


def _money(value):
    return format(value.quantize(Decimal("0.01")), "f")


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


@router.get("/monthly")
async def monthly_spending(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    try:
        year, month_number = (int(part) for part in month.split("-"))
        start_date = date(year, month_number, 1)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")

    end_date = date(year, month_number, monthrange(year, month_number)[1])
    async with SessionLocal() as db:
        result = await db.execute(
            select(Transaction, RawTransaction.is_removed)
            .join(
                RawTransaction,
                RawTransaction.transaction_id == Transaction.transaction_id,
            )
            .where(
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
                RawTransaction.is_removed.is_(False),
            )
        )
        rows = result.all()

    return {"month": month, **summarize_monthly_transactions(rows)}
