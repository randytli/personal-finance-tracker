from calendar import monthrange
from datetime import date
from decimal import Decimal
import os
import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from api.classification import ALLOWED_TRANSACTION_TYPES, effective_classification
from api.categories import active_category, effective_category, category_editable
from api.models import ManualCategoryOverride
from api.db import SessionLocal
from api.models import Account, Item, ManualClassificationOverride, RawTransaction, Transaction


router = APIRouter(prefix="/analytics")
ZERO = Decimal("0")
DETAIL_TYPES = ALLOWED_TRANSACTION_TYPES | {"unclassified"}


def _money(value):
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


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


def _shift_month(month, offset):
    start, _ = _month_bounds(month)
    ordinal = start.year * 12 + start.month - 1 + offset
    return f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}"


async def _active_analytics_rows(start_date, end_date):
    statement = (
        select(
            Transaction,
            RawTransaction.is_removed,
            ManualClassificationOverride.transaction_type,
            Item,
            Account,
            ManualCategoryOverride,
        )
        .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
        .join(Item, Item.item_id == RawTransaction.item_id)
        .join(
            Account,
            (Account.account_id == Transaction.account_id)
            & (Account.item_id == Item.item_id),
        )
        .outerjoin(
            ManualClassificationOverride,
            ManualClassificationOverride.transaction_id == Transaction.transaction_id,
        )
        .where(
            # Category overrides never change classification or monetary eligibility.
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            RawTransaction.is_removed.is_(False),
            Item.status == "active",
            Item.user_id == os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user"),
        )
    )
    statement = statement.outerjoin(ManualCategoryOverride,
        ManualCategoryOverride.transaction_id == Transaction.transaction_id)
    async with SessionLocal() as db:
        return (await db.execute(statement)).all()


async def _active_month_rows(month, category=None):
    start_date, end_date = _month_bounds(month)
    rows = await _active_analytics_rows(start_date, end_date)
    if category is None:
        return rows
    return [row for row in rows if _category(_analytics_row(row)[0], _analytics_row(row)[5]) == category]


def _analytics_row(row):
    """Normalize database rows and compact rows used by pure unit tests."""
    if len(row) == 2:
        transaction, is_removed = row
        return transaction, is_removed, None, None, None, None
    if len(row) == 3:
        transaction, is_removed, override_type = row
        return transaction, is_removed, override_type, None, None, None
    if len(row) == 5:
        return (*row, None)
    return row


def _category(transaction, override=None):
    return effective_category(transaction, override)


def _empty_metrics():
    return {
        "gross_spending": ZERO,
        "refunds": ZERO,
        "card_benefits": ZERO,
        "net_spending": ZERO,
        "income": ZERO,
        "net_savings": ZERO,
        "unclassified_count": 0,
    }


def _accumulate(metrics, transaction, override_type):
    amount = Decimal(transaction.amount)
    transaction_type, is_spending, is_internal_transfer = effective_classification(
        transaction, override_type
    )
    if transaction_type is None:
        metrics["unclassified_count"] += 1
    elif is_internal_transfer is True:
        return
    elif transaction_type == "expense" and is_spending is True and amount < 0:
        metrics["gross_spending"] -= amount
    elif transaction_type == "refund" and amount > 0:
        metrics["refunds"] += amount
    elif transaction_type == "card_benefit" and amount > 0:
        metrics["card_benefits"] += amount
    elif transaction_type == "income" and amount > 0:
        metrics["income"] += amount


def _finalize_metrics(metrics):
    values = dict(metrics)
    values["net_spending"] = values["gross_spending"] - values["refunds"] - values["card_benefits"]
    values["net_savings"] = values["income"] - values["net_spending"]
    return {
        key: value if key == "unclassified_count" else _money(value)
        for key, value in values.items()
    }


def summarize_monthly_transactions(rows):
    metrics = _empty_metrics()
    categories = {}
    for row in rows:
        transaction, is_removed, override_type, _, _, category_override = _analytics_row(row)
        if is_removed:
            continue
        _accumulate(metrics, transaction, override_type)
        transaction_type, is_spending, is_internal_transfer = effective_classification(
            transaction, override_type
        )
        if is_internal_transfer is True:
            continue
        amount = Decimal(transaction.amount)
        values = categories.setdefault(_category(transaction, category_override), [ZERO, ZERO, 0, 0, 0])
        if transaction_type == "expense" and is_spending is True and amount < 0:
            values[0] -= amount
            values[2] += 1
            values[3] += 1
        elif transaction_type == "refund" and amount > 0:
            values[1] += amount
            values[2] += 1
            values[4] += 1

    category_breakdown = [
        {
            "category": category,
            "gross_spending": _money(values[0]),
            "refunds": _money(values[1]),
            "net_spending": _money(values[0] - values[1]),
            "spending_transaction_count": values[2],
            "expense_transaction_count": values[3],
            "refund_transaction_count": values[4],
        }
        for category, values in sorted(categories.items())
        if values[2]
    ]
    return {**_finalize_metrics(metrics), "category_breakdown": category_breakdown}


def summarize_category_transactions(rows, category):
    gross_spending = ZERO
    refunds = ZERO
    count = 0
    expense_count = 0
    refund_count = 0
    for row in rows:
        transaction, is_removed, override_type, _, _, category_override = _analytics_row(row)
        if is_removed or _category(transaction, category_override) != category:
            continue
        transaction_type, is_spending, is_internal_transfer = effective_classification(
            transaction, override_type
        )
        if is_internal_transfer is True:
            continue
        amount = Decimal(transaction.amount)
        if transaction_type == "expense" and is_spending is True and amount < 0:
            gross_spending -= amount
            count += 1
            expense_count += 1
        elif transaction_type == "refund" and amount > 0:
            refunds += amount
            count += 1
            refund_count += 1
    return {
        "gross_spending": _money(gross_spending),
        "refunds": _money(refunds),
        "net_spending": _money(gross_spending - refunds),
        "spending_transaction_count": count,
        "expense_transaction_count": expense_count,
        "refund_transaction_count": refund_count,
    }


def transaction_details(rows, category=None, transaction_type=None, institution_id=None, account_id=None):
    relevant = []
    for row in rows:
        transaction, is_removed, override_type, item, account, category_override = _analytics_row(row)
        if is_removed or (category is not None and _category(transaction, category_override) != category):
            continue
        if institution_id is not None and getattr(item, "institution_id", None) != institution_id:
            continue
        if account_id is not None and getattr(account, "account_id", None) != account_id:
            continue
        effective_type, is_spending, is_internal = effective_classification(transaction, override_type)
        type_label = effective_type or "unclassified"
        if transaction_type is not None and type_label != transaction_type:
            continue
        relevant.append((transaction, item, account, type_label, is_spending, is_internal,
                         category_override, category_editable(transaction, override_type)))
    relevant.sort(key=lambda value: (value[0].transaction_date, value[0].transaction_id), reverse=True)
    return [
        {
            "transaction_id": transaction.transaction_id,
            "transaction_date": transaction.transaction_date.isoformat(),
            "institution_name": getattr(item, "institution_name", None),
            "account_name": getattr(account, "name", None),
            "account_mask": getattr(account, "mask", None),
            "account_type": getattr(account, "type", None),
            "account_subtype": getattr(account, "subtype", None),
            "merchant_name": transaction.merchant_name,
            "description": transaction.description,
            "amount": _money(transaction.amount),
            "transaction_type": type_label,
            "is_spending": is_spending,
            "is_internal_transfer": is_internal,
            "plaid_category": transaction.plaid_category or "UNCATEGORIZED",
            "original_category": transaction.plaid_category,
            "override_category": active_category(category_override),
            "effective_category": _category(transaction, category_override),
            "category_editable": editable,
        }
        for transaction, item, account, type_label, is_spending, is_internal, category_override, editable in relevant
    ]


def category_transaction_details(rows, category):
    return [detail for detail in transaction_details(rows, category) if detail["transaction_type"] in {"expense", "refund"}]


def summarize_breakdown(rows, group_by):
    groups = {}
    for row in rows:
        transaction, is_removed, override_type, item, account, _ = _analytics_row(row)
        if is_removed or item is None or account is None:
            continue
        if group_by == "institution":
            key = item.institution_id
            metadata = {"institution_id": item.institution_id, "institution_name": item.institution_name}
        else:
            key = account.account_id
            metadata = {
                "institution_id": item.institution_id,
                "institution_name": item.institution_name,
                "account_id": account.account_id,
                "account_name": account.name,
                "account_mask": account.mask,
                "account_type": account.type,
                "account_subtype": account.subtype,
            }
        entry = groups.setdefault(key, {"metadata": metadata, "metrics": _empty_metrics()})
        _accumulate(entry["metrics"], transaction, override_type)
    result = [{**entry["metadata"], **_finalize_metrics(entry["metrics"])} for entry in groups.values()]
    return sorted(result, key=lambda value: (Decimal(value["net_spending"]), str(value)), reverse=True)


@router.get("/monthly")
async def monthly_spending(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    return {"month": month, **summarize_monthly_transactions(await _active_month_rows(month))}


@router.get("/category")
async def category_spending(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), category: str = Query(..., min_length=1)):
    rows = await _active_month_rows(month)
    return {"month": month, "category": category, **summarize_category_transactions(rows, category)}


@router.get("/trend")
async def spending_trend(end_month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    start_month = _shift_month(end_month, -11)
    start_date, _ = _month_bounds(start_month)
    _, end_date = _month_bounds(end_month)
    rows = await _active_analytics_rows(start_date, end_date)
    by_month = {month: [] for month in (_shift_month(start_month, offset) for offset in range(12))}
    for row in rows:
        transaction = _analytics_row(row)[0]
        by_month[transaction.transaction_date.strftime("%Y-%m")].append(row)
    months = []
    for month, month_rows in by_month.items():
        summary = summarize_monthly_transactions(month_rows)
        months.append({"month": month, **{key: summary[key] for key in ("net_spending", "income", "net_savings")}})
    return {"start_month": start_month, "end_month": end_month, "months": months}


@router.get("/breakdown")
async def spending_breakdown(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    group_by: str = Query("institution", pattern=r"^(institution|account)$"),
):
    return {"month": month, "group_by": group_by, "groups": summarize_breakdown(await _active_month_rows(month), group_by)}


@router.get("/transactions")
async def analytics_transactions(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    category: str | None = Query(None, min_length=1),
    transaction_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    institution_id: str | None = None,
    account_id: str | None = None,
):
    if transaction_type is not None and transaction_type not in DETAIL_TYPES:
        raise HTTPException(status_code=422, detail="unsupported transaction type")
    details = transaction_details(
        await _active_month_rows(month), category, transaction_type, institution_id, account_id
    )
    page = details[offset : offset + limit]
    return {
        "month": month,
        "category": category,
        "transaction_type": transaction_type,
        "total": len(details),
        "limit": limit,
        "offset": offset,
        "transactions": page,
        "transaction_count": len(page),
    }


category_transactions = analytics_transactions
