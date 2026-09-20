import os
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime, timezone
from api.categories import MANUAL_CATEGORIES, active_category, effective_category, category_editable
from api.benefit_categories import BENEFIT_CATEGORIES, BENEFIT_CATEGORY_LABELS, active_benefit_category, effective_benefit_category
from api.labels import ALLOWED_LABELS, label_result, load_label_overrides
from api.models import ManualCategoryOverride, ManualBenefitCategoryOverride
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from api.classification import effective_classification, validate_manual_override
from api.db import SessionLocal
from api.models import (
    Account,
    Item,
    ManualClassificationOverride,
    ManualTransactionLabelOverride,
    RawTransaction,
    Transaction,
)


router = APIRouter(prefix="/review")


class CategoryRequest(BaseModel):
    category: str

    @field_validator('category')
    @classmethod
    def allowed(cls, value):
        if value not in MANUAL_CATEGORIES:
            raise ValueError('unsupported manual category')
        return value


class BenefitCategoryRequest(BaseModel):
    benefit_category: str

    @field_validator('benefit_category')
    @classmethod
    def allowed(cls, value):
        if value not in BENEFIT_CATEGORIES:
            raise ValueError('unsupported benefit category')
        return value


@router.get('/categories')
async def category_options():
    return {'categories': [{'value': value, 'label': value.replace('_', ' ').title()}
                           for value in MANUAL_CATEGORIES]}


@router.get('/benefit-categories')
async def benefit_category_options():
    return {'categories': [{'value': value, 'label': BENEFIT_CATEGORY_LABELS[value]}
                           for value in BENEFIT_CATEGORIES]}


class LabelDecisionRequest(BaseModel):
    decision: Literal["include", "exclude"]


@router.get("/labels")
async def label_options():
    return {"labels": [{"value": value, "label": value.title()} for value in ALLOWED_LABELS]}


def category_result(transaction, override, classification_type=None):
    return {'transaction_id': transaction.transaction_id,
            'original_category': transaction.plaid_category,
            'override_category': active_category(override),
            'effective_category': effective_category(transaction, override, classification_type)}


async def _apply_category(db, transaction, category, actor, classification=None):
    override = await db.get(ManualCategoryOverride, transaction.transaction_id)
    if classification is None:
        classification = await db.get(ManualClassificationOverride, transaction.transaction_id)
    classification_type = (classification.transaction_type if classification is not None
                           and classification.cleared_at is None else None)
    if category is not None:
        if not category_editable(transaction, classification_type):
            raise HTTPException(422, 'category editing requires an included expense, refund, or reimbursement')
        if active_category(override) == category:
            return category_result(transaction, override, classification_type), False
    elif active_category(override) is None:
        return category_result(transaction, override, classification_type), False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if override is None:
        override = ManualCategoryOverride(transaction_id=transaction.transaction_id,
            created_by=actor, created_at=now)
        db.add(override)
    override.category = category
    override.updated_by = actor
    override.updated_at = now
    override.cleared_by = actor if category is None else None
    override.cleared_at = now if category is None else None
    return category_result(transaction, override, classification_type), True


async def mutate_category(transaction_id, category):
    async with SessionLocal() as db:
        async with db.begin():
            row = (await db.execute(_transaction_scope(transaction_id).with_for_update())).one_or_none()
            if row is None:
                raise HTTPException(404, 'transaction not found')
            transaction = row[0]
            result, _ = await _apply_category(db, transaction, category, _user_id())
            return result


@router.put('/transactions/{transaction_id}/category-override')
async def set_category_override(transaction_id: str, request: CategoryRequest):
    return await mutate_category(transaction_id, request.category)


@router.delete('/transactions/{transaction_id}/category-override')
async def clear_category_override(transaction_id: str):
    return await mutate_category(transaction_id, None)


async def mutate_benefit_category(transaction_id, category):
    actor = _user_id()
    async with SessionLocal() as db:
        async with db.begin():
            row = (await db.execute(_transaction_scope(transaction_id).with_for_update())).one_or_none()
            if row is None:
                raise HTTPException(404, 'transaction not found')
            transaction, account, item, _ = row
            classification = await db.get(ManualClassificationOverride, transaction_id)
            override_type = classification.transaction_type if classification and classification.cleared_at is None else None
            kind, _, internal = effective_classification(transaction, override_type)
            if kind != 'card_benefit' or transaction.amount <= 0 or internal is True:
                raise HTTPException(422, 'benefit category editing requires a positive card benefit')
            override = await db.get(ManualBenefitCategoryOverride, transaction_id)
            automatic = effective_benefit_category(transaction, None,
                institution_id=item.institution_id, account_name=account.name, account_type=account.type)
            if category is not None and category == automatic and override is None:
                return {'transaction_id': transaction_id, 'effective_benefit_category': automatic,
                        'override_benefit_category': None, 'automatic_benefit_category': automatic}
            if category is None and override is None:
                return {'transaction_id': transaction_id, 'effective_benefit_category': automatic,
                        'override_benefit_category': None, 'automatic_benefit_category': automatic}
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if override is None:
                override = ManualBenefitCategoryOverride(transaction_id=transaction_id, created_by=actor, created_at=now)
                db.add(override)
            override.benefit_category = category
            override.updated_by = actor
            override.updated_at = now
            override.cleared_by = actor if category is None else None
            override.cleared_at = now if category is None else None
            return {'transaction_id': transaction_id, 'effective_benefit_category': category or automatic,
                    'override_benefit_category': category, 'automatic_benefit_category': automatic}


@router.put('/transactions/{transaction_id}/benefit-category-override')
async def set_benefit_category_override(transaction_id: str, request: BenefitCategoryRequest):
    return await mutate_benefit_category(transaction_id, request.benefit_category)


@router.delete('/transactions/{transaction_id}/benefit-category-override')
async def clear_benefit_category_override(transaction_id: str):
    return await mutate_benefit_category(transaction_id, None)
TransactionType = Literal[
    "expense", "refund", "reimbursement", "income", "card_benefit", "payment", "transfer", "adjustment"
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
            & (Account.account_id == RawTransaction.account_id)
            & (Account.item_id == Item.item_id),
        )
        .where(
            Transaction.transaction_id == transaction_id,
            Item.user_id == _user_id(),
            Item.status == "active",
            Account.consumer_transactions_enabled.is_(True),
            RawTransaction.is_removed.is_(False),
        )
    )


def _label_transaction_scope(transaction_id):
    return (
        select(Transaction)
        .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
        .join(Item, Item.item_id == RawTransaction.item_id)
        .join(Account, (Account.account_id == Transaction.account_id)
              & (Account.account_id == RawTransaction.account_id)
              & (Account.item_id == Item.item_id))
        .where(Transaction.transaction_id == transaction_id, Item.user_id == _user_id(),
               Item.status.in_(("active", "pending")),
               Account.consumer_transactions_enabled.is_(True),
               RawTransaction.is_removed.is_(False))
    )


async def _apply_label(db, transaction, label, decision, actor):
    override = await db.get(ManualTransactionLabelOverride, (transaction.transaction_id, label))
    active = (override.decision if override is not None
              and override.decision is not None and override.cleared_at is None else None)
    changed = not (active == decision or (decision is None and active is None))
    if changed:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if override is None:
            override = ManualTransactionLabelOverride(
                transaction_id=transaction.transaction_id, label=label,
                created_by=actor, created_at=now,
            )
            db.add(override)
        override.decision = decision
        override.updated_by = actor
        override.updated_at = now
        override.cleared_by = actor if decision is None else None
        override.cleared_at = now if decision is None else None
        await db.flush()
    overrides = (await db.execute(select(ManualTransactionLabelOverride).where(
        ManualTransactionLabelOverride.transaction_id == transaction.transaction_id))).scalars().all()
    context = (await db.execute(
        select(Item.institution_id, Account.type, Account.name)
        .join(RawTransaction, RawTransaction.item_id == Item.item_id)
        .join(Account, (Account.account_id == RawTransaction.account_id)
              & (Account.item_id == Item.item_id))
        .where(RawTransaction.transaction_id == transaction.transaction_id,
               Account.account_id == transaction.account_id,
               Item.user_id == actor)
    )).one()
    return {"transaction_id": transaction.transaction_id,
            **label_result(transaction, overrides, institution_id=context[0],
                           account_type=context[1], account_name=context[2])}, changed


async def mutate_label(transaction_id, label, decision):
    if label not in ALLOWED_LABELS:
        raise HTTPException(422, "unsupported transaction label")
    actor = _user_id()
    async with SessionLocal() as db:
        async with db.begin():
            transaction = (await db.execute(
                _label_transaction_scope(transaction_id).with_for_update()
            )).scalar_one_or_none()
            if transaction is None:
                raise HTTPException(404, "transaction not found")
            result, _ = await _apply_label(db, transaction, label, decision, actor)
            return result


@router.put("/transactions/{transaction_id}/labels/{label}")
async def set_label_override(transaction_id: str, label: str, request: LabelDecisionRequest):
    return await mutate_label(transaction_id, label, request.decision)


@router.delete("/transactions/{transaction_id}/labels/{label}")
async def clear_label_override(transaction_id: str, label: str):
    return await mutate_label(transaction_id, label, None)


BulkOperation = Literal["set_classification", "set_category", "include_label", "exclude_label", "restore_label_auto"]
BulkClassificationType = Literal["expense", "reimbursement"]


class BulkEditRequest(BaseModel):
    transaction_ids: list[str]
    operation: BulkOperation
    transaction_type: BulkClassificationType | None = None
    category: str | None = None
    label: str | None = None

    @field_validator("transaction_ids")
    @classmethod
    def valid_ids(cls, values):
        values = list(dict.fromkeys(values))
        if not values or len(values) > 100 or any(not value for value in values):
            raise ValueError("select between 1 and 100 unique transactions")
        return values

    @model_validator(mode="after")
    def valid_action(self):
        if self.operation == "set_classification":
            if self.transaction_type is None or self.category is not None or self.label is not None:
                raise ValueError("set_classification requires an expense or reimbursement transaction type")
        elif self.operation == "set_category":
            if self.category not in MANUAL_CATEGORIES or self.label is not None or self.transaction_type is not None:
                raise ValueError("set_category requires a supported category")
        elif self.label not in ALLOWED_LABELS or self.category is not None or self.transaction_type is not None:
            raise ValueError("label operation requires a supported label")
        return self


def _bulk_classification_errors(rows, transaction_type):
    errors = []
    for transaction, _ in rows:
        error = validate_manual_override(transaction, transaction_type)
        if error is not None:
            errors.append((transaction.transaction_id, error))
    return errors


@router.post("/transactions/bulk-edit")
async def bulk_edit_transactions(request: BulkEditRequest):
    ids = sorted(request.transaction_ids)
    async with SessionLocal() as db:
        async with db.begin():
            rows = (await db.execute(
                select(Transaction, ManualClassificationOverride)
                .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
                .join(Item, Item.item_id == RawTransaction.item_id)
                .join(Account, (Account.account_id == Transaction.account_id)
                      & (Account.account_id == RawTransaction.account_id)
                      & (Account.item_id == Item.item_id))
                .outerjoin(ManualClassificationOverride,
                    ManualClassificationOverride.transaction_id == Transaction.transaction_id)
                .where(Transaction.transaction_id.in_(ids), Item.user_id == _user_id(),
                       Item.status == "active", Account.consumer_transactions_enabled.is_(True),
                       RawTransaction.is_removed.is_(False))
                .order_by(Transaction.transaction_id)
                .with_for_update(of=Transaction)
            )).all()
            if len(rows) != len(ids):
                raise HTTPException(404, detail={
                    "message": "Some selected transactions are no longer available.",
                    "unavailable_count": len(ids) - len(rows),
                })

            if request.operation == "set_category":
                ineligible = [transaction.transaction_id for transaction, classification in rows
                    if not category_editable(transaction,
                        classification.transaction_type if classification and classification.cleared_at is None else None)]
                if ineligible:
                    raise HTTPException(422, detail={
                        "message": "Category editing requires included expense, refund, or reimbursement transactions.",
                        "ineligible_count": len(ineligible),
                    })
            elif request.operation == "set_classification":
                ineligible = _bulk_classification_errors(rows, request.transaction_type)
                if ineligible:
                    raise HTTPException(422, detail={
                        "message": "Every selected transaction must be eligible for the requested classification.",
                        "ineligible_count": len(ineligible),
                    })

            results = []
            changed_count = 0
            actor = _user_id()
            for transaction, classification in rows:
                if request.operation == "set_classification":
                    active_type = (classification.transaction_type if classification is not None
                                   and classification.cleared_at is None else None)
                    changed = active_type != request.transaction_type
                    if changed:
                        await db.execute(
                            insert(ManualClassificationOverride)
                            .values(transaction_id=transaction.transaction_id,
                                    transaction_type=request.transaction_type,
                                    created_by=actor, updated_by=actor,
                                    cleared_by=None, cleared_at=None)
                            .on_conflict_do_update(
                                index_elements=["transaction_id"],
                                set_={"transaction_type": request.transaction_type,
                                      "updated_by": actor, "updated_at": func.now(),
                                      "cleared_by": None, "cleared_at": None},
                            )
                        )
                    result = _result(transaction, request.transaction_type)
                elif request.operation == "set_category":
                    result, changed = await _apply_category(
                        db, transaction, request.category, actor, classification)
                else:
                    decision = {"include_label": "include", "exclude_label": "exclude",
                                "restore_label_auto": None}[request.operation]
                    result, changed = await _apply_label(
                        db, transaction, request.label, decision, actor)
                results.append(result)
                changed_count += int(changed)
            return {"selected_count": len(rows), "changed_count": changed_count,
                    "unchanged_count": len(rows) - changed_count, "results": results}


def _review_ordering():
    return (
        case((Account.type == "credit", 1), else_=0),
        Transaction.transaction_date,
        Transaction.transaction_id,
    )


def _review_filters(mode="needs_review", transaction_type="all", direction="incoming"):
    effective_type = func.coalesce(
        ManualClassificationOverride.transaction_type, Transaction.transaction_type,
        "unclassified",
    )
    filters = [
        Item.user_id == _user_id(),
        Item.status == "active",
        Account.consumer_transactions_enabled.is_(True),
        RawTransaction.is_removed.is_(False),
    ]
    if mode == "credits_transfers":
        incoming = and_(Transaction.amount > 0,
            effective_type.in_(("transfer", "payment", "income", "refund",
                                "reimbursement", "card_benefit", "unclassified")))
        outgoing = and_(Transaction.amount < 0,
            effective_type.in_(("transfer", "payment", "unclassified")))
        filters.append(incoming if direction == "incoming" else
                       outgoing if direction == "outgoing" else or_(incoming, outgoing))
        if transaction_type != "all":
            filters.append(effective_type == transaction_type)
    else:
        filters.extend([
            Transaction.transaction_type.is_(None),
            ManualClassificationOverride.transaction_type.is_(None),
        ])
    return filters


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
    mode: Literal["needs_review", "credits_transfers"] = "needs_review",
    transaction_type: Literal["all", "transfer", "payment", "income", "refund", "reimbursement", "card_benefit", "unclassified"] = "all",
    direction: Literal["incoming", "outgoing", "all"] = "incoming",
):
    filters = _review_filters(mode, transaction_type, direction)
    joins = (
        (RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id),
        (Item, Item.item_id == RawTransaction.item_id),
        (
            Account,
            (Account.account_id == Transaction.account_id)
            & (Account.account_id == RawTransaction.account_id)
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

        statement = select(Transaction, Account, Item, ManualClassificationOverride.transaction_type,
                           ManualCategoryOverride)
        for model, condition in joins:
            statement = statement.join(model, condition)
        statement = (
            statement.outerjoin(
                ManualClassificationOverride,
                ManualClassificationOverride.transaction_id == Transaction.transaction_id,
            )
            .outerjoin(ManualCategoryOverride,
                ManualCategoryOverride.transaction_id == Transaction.transaction_id)
            .where(*filters)
            .order_by(*((
                Transaction.transaction_date.desc(), Transaction.transaction_id,
            ) if mode == "credits_transfers" else _review_ordering()))
            .offset(offset)
            .limit(limit)
        )
        rows = (await db.execute(statement)).all()
        label_overrides = await load_label_overrides(
            db, [transaction.transaction_id for transaction, *_ in rows]
        )

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
                "original_category": transaction.plaid_category,
                "override_category": active_category(category_override),
                "effective_category": effective_category(transaction, category_override, override_type),
                "category_editable": category_editable(transaction, override_type),
                **label_result(transaction, label_overrides.get(transaction.transaction_id, ()),
                               institution_id=item.institution_id,
                               account_type=account.type, account_name=account.name),
                **_result(transaction, override_type),
            }
            for transaction, account, item, override_type, category_override in rows
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
