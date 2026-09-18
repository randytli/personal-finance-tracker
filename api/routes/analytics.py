from calendar import monthrange
from datetime import date
from decimal import Decimal
import os
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from api.classification import ALLOWED_TRANSACTION_TYPES, effective_classification
from api.categories import active_category, effective_category, category_editable
from api.benefit_categories import active_benefit_category, effective_benefit_category
from api.labels import ALLOWED_LABELS, label_result, load_label_overrides
from api.models import ManualCategoryOverride, ManualBenefitCategoryOverride
from api.db import SessionLocal
from api.models import Account, Item, ManualClassificationOverride, RawTransaction, Transaction


router = APIRouter(prefix="/analytics")
ZERO = Decimal("0")
DETAIL_TYPES = ALLOWED_TRANSACTION_TYPES | {"unclassified"}
MembershipPeriod = Literal["trailing_12m", "ytd"]
MembershipView = Literal["all", "charges", "refunds", "reimbursements", "card_benefits"]


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
            ManualBenefitCategoryOverride,
        )
        .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
        .join(Item, Item.item_id == RawTransaction.item_id)
        .join(
            Account,
            (Account.account_id == Transaction.account_id)
            & (Account.account_id == RawTransaction.account_id)
            & (Account.item_id == Item.item_id),
        )
        .outerjoin(
            ManualClassificationOverride,
            (ManualClassificationOverride.transaction_id == Transaction.transaction_id)
            & ManualClassificationOverride.cleared_at.is_(None),
        )
        .where(
            # Category overrides never change classification or monetary eligibility.
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            RawTransaction.is_removed.is_(False),
            Item.status == "active",
            Account.consumer_transactions_enabled.is_(True),
            Item.user_id == os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user"),
        )
    )
    statement = statement.outerjoin(ManualCategoryOverride,
        ManualCategoryOverride.transaction_id == Transaction.transaction_id)
    statement = statement.outerjoin(ManualBenefitCategoryOverride,
        ManualBenefitCategoryOverride.transaction_id == Transaction.transaction_id)
    async with SessionLocal() as db:
        return (await db.execute(statement)).all()


async def _active_month_rows(month, category=None):
    start_date, end_date = _month_bounds(month)
    rows = await _active_analytics_rows(start_date, end_date)
    if category is None:
        return rows
    return [row for row in rows if _category(_analytics_row(row)[0], _analytics_row(row)[5],
                                           _analytics_row(row)[2]) == category]


def _analytics_row(row):
    """Normalize database rows and compact rows used by pure unit tests."""
    values = list(row)
    if len(values) == 2: values += [None, None, None, None, None]
    elif len(values) == 3: values += [None, None, None, None]
    elif len(values) == 5: values += [None, None]
    elif len(values) == 6: values += [None]
    return tuple(values)


def _category(transaction, override=None, classification_override=None):
    return effective_category(transaction, override, classification_override)


def _empty_metrics():
    return {
        "gross_spending": ZERO,
        "refunds": ZERO,
        "reimbursements": ZERO,
        "reimbursement_transaction_count": 0,
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
    elif transaction_type == "reimbursement" and amount > 0:
        metrics["reimbursements"] += amount
        metrics["reimbursement_transaction_count"] += 1
    elif transaction_type == "card_benefit" and amount > 0:
        metrics["card_benefits"] += amount
    elif transaction_type == "income" and amount > 0:
        metrics["income"] += amount


def _finalize_metrics(metrics):
    values = dict(metrics)
    values["net_spending"] = (values["gross_spending"] - values["refunds"]
                              - values["reimbursements"] - values["card_benefits"])
    values["net_savings"] = values["income"] - values["net_spending"]
    return {
        key: value if key in {"unclassified_count", "reimbursement_transaction_count"} else _money(value)
        for key, value in values.items()
    }


def _empty_membership_metrics():
    return {
        "gross_charges": ZERO, "refunds": ZERO, "reimbursements": ZERO,
        "unallocated_reimbursements": ZERO, "card_benefits": ZERO,
        "reimbursement_transaction_count": 0,
        "unallocated_reimbursement_transaction_count": 0,
        "membership_transaction_count": 0, "excluded_transaction_count": 0,
        "unclassified_count": 0,
    }


def _accumulate_membership(metrics, transaction, override_type):
    metrics["membership_transaction_count"] += 1
    kind, spending, internal = effective_classification(transaction, override_type)
    amount = Decimal(transaction.amount)
    if internal is not True and kind == "expense" and spending is True and amount < 0:
        metrics["gross_charges"] -= amount
    elif internal is not True and kind == "refund" and amount > 0:
        metrics["refunds"] += amount
    elif internal is not True and kind == "reimbursement" and amount > 0:
        # Phase 1 has no expense linkage. Preserve the receiving account, but
        # do not assign its credit to any account's Membership net cost.
        metrics["reimbursements"] += amount
        metrics["unallocated_reimbursements"] += amount
        metrics["reimbursement_transaction_count"] += 1
        metrics["unallocated_reimbursement_transaction_count"] += 1
    elif internal is not True and kind == "card_benefit" and amount > 0:
        metrics["card_benefits"] += amount
    else:
        metrics["excluded_transaction_count"] += 1
        if kind is None:
            metrics["unclassified_count"] += 1


def _finalize_membership_metrics(metrics, *, include_unallocated=True):
    return {
        "gross_charges": _money(metrics["gross_charges"]),
        "refunds": _money(metrics["refunds"]),
        "reimbursements": _money(metrics["reimbursements"]),
        "unallocated_reimbursements": _money(metrics["unallocated_reimbursements"]),
        "card_benefits": _money(metrics["card_benefits"]),
        "net_cost": _money(metrics["gross_charges"] - metrics["refunds"] - metrics["card_benefits"]
                           - (metrics["unallocated_reimbursements"] if include_unallocated else ZERO)),
        "reimbursement_transaction_count": metrics["reimbursement_transaction_count"],
        "unallocated_reimbursement_transaction_count": metrics["unallocated_reimbursement_transaction_count"],
        "membership_transaction_count": metrics["membership_transaction_count"],
        "excluded_transaction_count": metrics["excluded_transaction_count"],
        "unclassified_count": metrics["unclassified_count"],
    }


def _membership_bucket(transaction, override_type):
    if isinstance(transaction, dict):
        kind = override_type or transaction.get("transaction_type")
        spending = transaction.get("is_spending") if override_type is None else kind == "expense"
        internal = transaction.get("is_internal_transfer")
        amount = Decimal(transaction["amount"])
    else:
        kind, spending, internal = effective_classification(transaction, override_type)
        amount = Decimal(transaction.amount)
    if internal is True:
        return None
    if kind == "expense" and spending is True and amount < 0:
        return "charges"
    if kind == "refund" and amount > 0:
        return "refunds"
    if kind == "reimbursement" and amount > 0:
        return "reimbursements"
    if kind == "card_benefit" and amount > 0:
        return "card_benefits"
    return "excluded"


def summarize_memberships(rows, label_overrides, start_month, end_month,
                          period: MembershipPeriod = "trailing_12m"):
    start_date, _ = _month_bounds(start_month)
    end_date, _ = _month_bounds(end_month)
    month_count = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1
    if not 1 <= month_count <= 12:
        raise HTTPException(status_code=422, detail="membership period must span 1 to 12 months")
    months = {month: _empty_membership_metrics()
              for month in (_shift_month(start_month, offset) for offset in range(month_count))}
    overall = _empty_membership_metrics()
    type_counts = {"charges": 0, "refunds": 0, "reimbursements": 0,
                   "card_benefits": 0, "excluded": 0}
    accounts = {}
    for row in rows:
        transaction, is_removed, override_type, item, account, _, _ = _analytics_row(row)
        if is_removed or account is None or item is None:
            continue
        decisions = label_overrides.get(transaction.transaction_id, ())
        if "MEMBERSHIP" not in label_result(transaction, decisions,
                institution_id=item.institution_id, account_type=account.type,
                account_name=account.name)["effective_labels"]:
            continue
        month = transaction.transaction_date.strftime("%Y-%m")
        if month not in months:
            continue
        _accumulate_membership(overall, transaction, override_type)
        bucket = _membership_bucket(transaction, override_type)
        if bucket in type_counts:
            type_counts[bucket] += 1
        _accumulate_membership(months[month], transaction, override_type)
        account_id = account.account_id
        if account_id not in accounts:
            accounts[account_id] = {
                "institution_id": item.institution_id,
                "institution_name": item.institution_name,
                "account_id": account_id,
                "account_name": account.name,
                "account_mask": account.mask,
                "account_type": account.type,
                "account_subtype": account.subtype,
                "metrics": _empty_membership_metrics(),
            }
        _accumulate_membership(accounts[account_id]["metrics"], transaction, override_type)
    return {
        "period": period,
        "start_month": start_month,
        "end_month": end_month,
        "overall": _finalize_membership_metrics(overall),
        "type_counts": type_counts,
        "months": [{"month": month, **_finalize_membership_metrics(values)}
                   for month, values in months.items()],
        "accounts": sorted(
            [{**{key: value for key, value in entry.items() if key != "metrics"},
              **_finalize_membership_metrics(entry["metrics"], include_unallocated=False)}
             for entry in accounts.values()],
            key=lambda entry: (Decimal(entry["net_cost"]), entry["account_id"]), reverse=True,
        ),
    }


def summarize_monthly_transactions(rows):
    metrics = _empty_metrics()
    categories = {}
    for row in rows:
        transaction, is_removed, override_type, _, _, category_override, _ = _analytics_row(row)
        if is_removed:
            continue
        _accumulate(metrics, transaction, override_type)
        transaction_type, is_spending, is_internal_transfer = effective_classification(
            transaction, override_type
        )
        if is_internal_transfer is True:
            continue
        amount = Decimal(transaction.amount)
        values = categories.setdefault(
            _category(transaction, category_override, override_type),
            [ZERO, ZERO, 0, 0, 0, ZERO, 0],
        )
        if transaction_type == "expense" and is_spending is True and amount < 0:
            values[0] -= amount
            values[2] += 1
            values[3] += 1
        elif transaction_type == "refund" and amount > 0:
            values[1] += amount
            values[2] += 1
            values[4] += 1
        elif transaction_type == "reimbursement" and amount > 0:
            values[5] += amount
            values[6] += 1

    category_breakdown = [
        {
            "category": category,
            "gross_spending": _money(values[0]),
            "refunds": _money(values[1]),
            "reimbursements": _money(values[5]),
            "net_spending": _money(values[0] - values[1] - values[5]),
            "spending_transaction_count": values[2],
            "expense_transaction_count": values[3],
            "refund_transaction_count": values[4],
            "reimbursement_transaction_count": values[6],
        }
        for category, values in sorted(categories.items())
        if values[2] or values[6]
    ]
    return {**_finalize_metrics(metrics), "category_breakdown": category_breakdown,
            "benefit_category_breakdown": summarize_benefit_categories(rows)}


def summarize_benefit_categories(rows):
    groups = {}
    for row in rows:
        transaction, is_removed, override_type, item, account, _, benefit_override = _analytics_row(row)
        if is_removed or item is None or account is None:
            continue
        kind, _, internal = effective_classification(transaction, override_type)
        amount = Decimal(transaction.amount)
        if kind != "card_benefit" or amount <= 0 or internal is True:
            continue
        category = effective_benefit_category(transaction, benefit_override,
            institution_id=getattr(item, "institution_id", None),
            account_name=getattr(account, "name", None), account_type=getattr(account, "type", None),
            transaction_type=kind) or "UNCATEGORIZED"
        entry = groups.setdefault(category, [ZERO, 0])
        entry[0] += amount
        entry[1] += 1
    return [{"benefit_category": category, "benefit_amount": _money(values[0]),
             "benefit_transaction_count": values[1]}
            for category, values in sorted(groups.items(), key=lambda entry: entry[1][0], reverse=True)]


def summarize_category_transactions(rows, category):
    gross_spending = ZERO
    refunds = ZERO
    reimbursements = ZERO
    count = 0
    expense_count = 0
    refund_count = 0
    reimbursement_count = 0
    for row in rows:
        transaction, is_removed, override_type, _, _, category_override, _ = _analytics_row(row)
        if is_removed or _category(transaction, category_override, override_type) != category:
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
        elif transaction_type == "reimbursement" and amount > 0:
            reimbursements += amount
            reimbursement_count += 1
    return {
        "gross_spending": _money(gross_spending),
        "refunds": _money(refunds),
        "reimbursements": _money(reimbursements),
        "net_spending": _money(gross_spending - refunds - reimbursements),
        "spending_transaction_count": count,
        "expense_transaction_count": expense_count,
        "refund_transaction_count": refund_count,
        "reimbursement_transaction_count": reimbursement_count,
    }


def transaction_details(rows, category=None, transaction_type=None, institution_id=None, account_id=None, benefit_category=None):
    relevant = []
    for row in rows:
        transaction, is_removed, override_type, item, account, category_override, benefit_override = _analytics_row(row)
        if is_removed or (category is not None and
                          _category(transaction, category_override, override_type) != category):
            continue
        if institution_id is not None and getattr(item, "institution_id", None) != institution_id:
            continue
        if account_id is not None and getattr(account, "account_id", None) != account_id:
            continue
        effective_type, is_spending, is_internal = effective_classification(transaction, override_type)
        type_label = effective_type or "unclassified"
        if transaction_type is not None and type_label != transaction_type:
            continue
        if transaction_type == "reimbursement" and (is_internal is True or Decimal(transaction.amount) <= 0):
            continue
        effective_benefit = effective_benefit_category(transaction, benefit_override,
            institution_id=getattr(item, "institution_id", None), account_name=getattr(account, "name", None),
            account_type=getattr(account, "type", None), transaction_type=type_label)
        if benefit_category is not None and (type_label != "card_benefit" or effective_benefit != benefit_category):
            continue
        relevant.append((transaction, item, account, type_label, is_spending, is_internal,
                         category_override, benefit_override, effective_benefit,
                         category_editable(transaction, override_type)))
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
            "effective_category": _category(transaction, category_override, override_type),
            "category_editable": editable,
            "automatic_benefit_category": effective_benefit_category(transaction, None,
                institution_id=getattr(item, "institution_id", None), account_name=getattr(account, "name", None),
                account_type=getattr(account, "type", None), transaction_type=type_label),
            "override_benefit_category": active_benefit_category(benefit_override),
            "effective_benefit_category": effective_benefit,
            "benefit_category_editable": type_label == "card_benefit" and is_internal is not True and transaction.amount > 0,
        }
        for transaction, item, account, type_label, is_spending, is_internal, category_override, benefit_override, effective_benefit, editable in relevant
    ]


def category_transaction_details(rows, category):
    return [detail for detail in transaction_details(rows, category)
            if detail["is_internal_transfer"] is not True
            and ((detail["transaction_type"] == "expense"
                  and detail["is_spending"] is True and Decimal(detail["amount"]) < 0)
                 or (detail["transaction_type"] in {"refund", "reimbursement"}
                     and Decimal(detail["amount"]) > 0))]


def summarize_breakdown(rows, group_by, mode="spending"):
    groups = {}
    for row in rows:
        transaction, is_removed, override_type, item, account, _, _ = _analytics_row(row)
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
        if mode == "benefits":
            kind, _, internal = effective_classification(transaction, override_type)
            amount = Decimal(transaction.amount)
            if kind == "card_benefit" and amount > 0 and internal is not True:
                category = effective_benefit_category(transaction, _analytics_row(row)[6],
                    institution_id=item.institution_id, account_name=account.name,
                    account_type=account.type, transaction_type=kind)
                entry["metrics"]["card_benefits"] += amount if category else ZERO
        elif mode == "reimbursements":
            kind, _, internal = effective_classification(transaction, override_type)
            if kind == "reimbursement" and Decimal(transaction.amount) > 0 and internal is not True:
                entry["metrics"]["reimbursements"] += Decimal(transaction.amount)
                entry["metrics"]["reimbursement_transaction_count"] += 1
        else:
            _accumulate(entry["metrics"], transaction, override_type)
    result = [{**entry["metadata"], **_finalize_metrics(entry["metrics"])} for entry in groups.values()]
    if mode == "benefits":
        result = [value for value in result if Decimal(value["card_benefits"]) > 0]
        for value in result:
            value["benefit_amount"] = value["card_benefits"]
            value["benefit_transaction_count"] = 0
        for row in rows:
            transaction, is_removed, override_type, item, account, _, benefit_override = _analytics_row(row)
            kind, _, internal = effective_classification(transaction, override_type)
            if is_removed or kind != "card_benefit" or Decimal(transaction.amount) <= 0 or internal is True:
                continue
            key = account.account_id if group_by == "account" else item.institution_id
            for value in result:
                if (group_by == "account" and value.get("account_id") == key) or (group_by == "institution" and value.get("institution_id") == key):
                    if effective_benefit_category(transaction, benefit_override, institution_id=item.institution_id, account_name=account.name, account_type=account.type, transaction_type=kind):
                        value["benefit_transaction_count"] += 1
                        break
        return sorted(result, key=lambda value: (Decimal(value["benefit_amount"]), str(value)), reverse=True)
    if mode == "reimbursements":
        return sorted((value for value in result if value["reimbursement_transaction_count"] > 0),
                      key=lambda value: (Decimal(value["reimbursements"]), str(value)), reverse=True)
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
        months.append({"month": month, **{key: summary[key] for key in (
            "net_spending", "income", "net_savings", "reimbursements", "reimbursement_transaction_count")}})
    return {"start_month": start_month, "end_month": end_month, "months": months}


@router.get("/breakdown")
async def spending_breakdown(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    group_by: str = Query("institution", pattern=r"^(institution|account)$"),
    mode: str = Query("spending", pattern=r"^(spending|benefits|reimbursements)$"),
):
    return {"month": month, "group_by": group_by, "mode": mode, "groups": summarize_breakdown(await _active_month_rows(month), group_by, mode)}


@router.get("/memberships")
async def membership_costs(
    end_month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    period: MembershipPeriod = "trailing_12m",
):
    _, end_date = _month_bounds(end_month)
    if period == "trailing_12m":
        start_month = _shift_month(end_month, -11)
    elif period == "ytd":
        start_month = f"{end_date.year:04d}-01"
    else:
        raise HTTPException(status_code=422, detail="unsupported membership period")
    start_date, _ = _month_bounds(start_month)
    rows = await _active_analytics_rows(start_date, end_date)
    async with SessionLocal() as db:
        overrides = await load_label_overrides(
            db, [transaction.transaction_id for transaction, *_ in rows])
    return summarize_memberships(rows, overrides, start_month, end_month, period)


@router.get("/transactions")
async def analytics_transactions(
    month: str | None = None,
    category: str | None = Query(None, min_length=1),
    transaction_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    institution_id: str | None = None,
    account_id: str | None = None,
    benefit_category: str | None = None,
    label: str | None = None,
    start_month: str | None = None,
    end_month: str | None = None,
    membership_view: MembershipView | None = None,
):
    if membership_view is not None and (label != "MEMBERSHIP"):
        raise HTTPException(status_code=422, detail="membership_view requires label=MEMBERSHIP")
    if membership_view is not None and transaction_type is not None:
        raise HTTPException(status_code=422, detail="choose membership_view or transaction_type")
    if transaction_type is not None and transaction_type not in DETAIL_TYPES:
        raise HTTPException(status_code=422, detail="unsupported transaction type")
    if label is not None and label not in ALLOWED_LABELS:
        raise HTTPException(status_code=422, detail="unsupported transaction label")
    if benefit_category is not None and benefit_category not in {"DINING_CREDIT", "TRAVEL_CREDIT", "SHOPPING_CREDIT", "TRANSPORTATION_CREDIT", "DIGITAL_ENTERTAINMENT_CREDIT", "ENTERTAINMENT_CREDIT", "GENERAL_SERVICES_CREDIT", "UNCATEGORIZED"}:
        raise HTTPException(status_code=422, detail="unsupported benefit category")
    if month is not None:
        if start_month is not None or end_month is not None:
            raise HTTPException(status_code=422, detail="choose month or a month range")
        rows = await _active_month_rows(month)
    else:
        if start_month is None or end_month is None:
            raise HTTPException(status_code=422, detail="provide month or both range endpoints")
        start_date, _ = _month_bounds(start_month)
        _, end_date = _month_bounds(end_month)
        if start_date > end_date or not 0 <= ((int(end_month[:4]) - int(start_month[:4])) * 12
                                          + int(end_month[5:]) - int(start_month[5:])) < 12:
            raise HTTPException(status_code=422, detail="month range must span at most 12 months")
        rows = await _active_analytics_rows(start_date, end_date)
    details = transaction_details(
        rows, category, transaction_type, institution_id, account_id, benefit_category
    )
    contexts = {
        transaction.transaction_id: {
            "institution_id": getattr(item, "institution_id", None),
            "account_type": getattr(account, "type", None),
            "account_name": getattr(account, "name", None),
        }
        for transaction, _, _, item, account, _, _ in (_analytics_row(row) for row in rows)
        if item is not None and account is not None
    }
    async with SessionLocal() as db:
        overrides = await load_label_overrides(db, [detail["transaction_id"] for detail in details])
    details = [
        {**detail, **label_result(detail, overrides.get(detail["transaction_id"], ()),
                                 **contexts.get(detail["transaction_id"], {}))}
        for detail in details
    ]
    if label is not None:
        details = [detail for detail in details if label in detail["effective_labels"]]
    membership_counts = None
    if label == "MEMBERSHIP":
        buckets = {"charges": 0, "refunds": 0, "reimbursements": 0,
                   "card_benefits": 0, "excluded": 0}
        for detail in details:
            bucket = _membership_bucket(detail, None)
            if bucket is None:
                continue
            buckets[bucket] += 1
        membership_counts = {
            "charges": buckets["charges"],
            "refunds": buckets["refunds"],
            "reimbursements": buckets["reimbursements"],
            "card_benefits": buckets["card_benefits"],
            "all": len(details),
        }
        if membership_view and membership_view != "all":
            details = [detail for detail in details
                       if _membership_bucket(detail, None) == membership_view]
    reimbursement_details = [detail for detail in details
                             if detail["transaction_type"] == "reimbursement"
                             and detail["is_internal_transfer"] is not True
                             and Decimal(detail["amount"]) > 0]
    reimbursement_total = _money(sum((Decimal(detail["amount"]) for detail in reimbursement_details), ZERO))
    page = details[offset : offset + limit]
    return {
        "month": month,
        "start_month": start_month,
        "end_month": end_month,
        "category": category,
        "transaction_type": transaction_type,
        "label": label,
        "total": len(details),
        "reimbursements": reimbursement_total,
        "reimbursement_transaction_count": len(reimbursement_details),
        "unallocated_reimbursements": reimbursement_total if label == "MEMBERSHIP" else _money(ZERO),
        "unallocated_reimbursement_transaction_count": len(reimbursement_details)
            if label == "MEMBERSHIP" else 0,
        "limit": limit,
        "offset": offset,
        "transactions": page,
        "transaction_count": len(page),
        "membership_counts": membership_counts,
        "membership_view": membership_view,
    }


category_transactions = analytics_transactions
