"""Reviewed statement persistence. No initialization, network calls, or implicit sync."""
import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from api.models import (Account, Item, RawTransaction, Transaction, StatementImportBatch,
                        StatementImportRow, ManualClassificationOverride, ManualCategoryOverride)
from api.statement_semantics import normalized_raw_values, statement_classification, lock_consumer_derivation


class ImportBlocked(ValueError):
    """Safe, deliberately payload-free operator error."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def canonical(row):
    return {"date": row.transaction_date.isoformat(), "amount": str(row.amount),
            "currency": row.currency, "kind": row.kind, "merchant": row.merchant,
            "description": row.description, "source_amount": str(row.source_amount)}


def row_identity(account_id, row):
    return "statement:" + digest([account_id, row.adapter, row.source_file_sha256, row.source_record])


def candidate_match(left_date, left_amount, left_currency, right_date, right_amount, right_currency):
    # Deliberately conservative Phase 2 policy: evidence is NOT proof of a duplicate.
    return (left_currency == right_currency and Decimal(left_amount) == Decimal(right_amount)
            and abs((left_date - right_date).days) <= 7)


def raw_amount_currency(raw):
    if raw.source == "statement":
        return Decimal(raw.payload["amount"]), raw.payload["currency"]
    currency = raw.payload.get("iso_currency_code")
    return -Decimal(str(raw.payload["amount"])), currency


async def target(db, user_id, account_id, adapter, lock=False):
    # Consistent lock order with Plaid persistence: Item, then Account.
    item_id = await db.scalar(select(Account.item_id).where(Account.account_id == account_id))
    q = select(Item).where(Item.item_id == item_id, Item.user_id == user_id)
    if lock:
        q = q.with_for_update()
    item = await db.scalar(q.execution_options(populate_existing=True))
    q = select(Account).where(Account.account_id == account_id)
    if lock:
        q = q.with_for_update()
    account = await db.scalar(q.execution_options(populate_existing=True))
    if (item is None or account is None or account.item_id != item.item_id
            or item.status not in {"pending", "active"} or not account.consumer_transactions_enabled
            or (account.type, account.subtype) not in adapter.supported_accounts):
        raise ImportBlocked("Target must be an owned, enabled, supported account on a pending/active Item")
    return item, account


async def external_classifications(db, user_id, excluded=()):
    rows = (await db.execute(select(Transaction).join(Account, Account.account_id == Transaction.account_id)
                            .join(Item, Item.item_id == Account.item_id).where(Item.user_id == user_id)
                            .order_by(Transaction.transaction_id)
                            .execution_options(populate_existing=True))).scalars()
    return digest([(t.transaction_id, t.transaction_type, t.is_spending, t.is_internal_transfer)
                   for t in rows if t.transaction_id not in excluded])


async def preview(db, user_id, account_id, adapter, data, through=None):
    item, account = await target(db, user_id, account_id, adapter)
    parsed = adapter.parse(data, through=through)
    file_hash = hashlib.sha256(data).hexdigest()
    previous = await db.scalar(select(StatementImportBatch).where(
        StatementImportBatch.account_id == account_id, StatementImportBatch.adapter == adapter.name,
        StatementImportBatch.file_sha256 == file_hash).execution_options(populate_existing=True))
    raw = list((await db.execute(select(RawTransaction).where(RawTransaction.account_id == account_id)
                                .order_by(RawTransaction.transaction_id)
                                .execution_options(populate_existing=True))).scalars())
    entries, blockers = [], []
    if parsed.errors:
        blockers.append("parsing_errors")
    if previous and (previous.status != "applied" or previous.import_through != through
                     or previous.adapter_version != adapter.version):
        blockers.append("existing_batch_settings_or_state_conflict")
    for row in parsed.transactions:
        identity = row_identity(account_id, row)
        matches = []
        for old in raw:
            if old.transaction_id == identity:
                matches.append({"transaction_id": old.transaction_id, "reason": "same_source_row",
                                "removed": old.is_removed})
                continue
            if abs((row.transaction_date - old.transaction_date).days) > 7:
                continue
            try:
                amount, currency = raw_amount_currency(old)
                # Missing currency or malformed nearby evidence must not permit silent overlap.
                if amount == row.amount and currency is None:
                    matches.append({"transaction_id": old.transaction_id, "reason": "unknown_currency"})
                elif candidate_match(row.transaction_date, row.amount, row.currency,
                                     old.transaction_date, amount, currency):
                    matches.append({"transaction_id": old.transaction_id, "reason": "possible_overlap",
                                    "removed": old.is_removed})
            except (ValueError, KeyError, TypeError, ArithmeticError):
                matches.append({"transaction_id": old.transaction_id, "reason": "invalid_existing_evidence"})
        same_file = [other.source_record for other in parsed.transactions
                     if other.source_record != row.source_record
                     and canonical(other) == canonical(row) and other.source_fields == row.source_fields]
        duplicate = len(matches) == 1 and matches[0]["reason"] == "same_source_row" and not matches[0]["removed"]
        disposition = "duplicate" if duplicate else "ambiguous" if matches or same_file else "new"
        if row.currency != "USD":
            blockers.append("unsupported_currency")
        if disposition == "ambiguous":
            blockers.append("ambiguous_rows")
        seed = statement_classification(row.kind, row.amount)
        entries.append({"record": row.source_record, "transaction_id": identity,
                        "canonical": canonical(row), "disposition": disposition,
                        "matches": matches, "indistinguishable_records": same_file,
                        "proposed_type": seed[0] if seed else "unclassified"})
    if not parsed.transactions:
        blockers.append("no_eligible_rows")
    counts = {state: sum(e["disposition"] == state for e in entries)
              for state in ("new", "duplicate", "ambiguous")}
    counts["skipped"] = sum(parsed.skipped.values())
    auto_fingerprint = await external_classifications(db, user_id)
    override_snapshot = []
    for model in (ManualClassificationOverride, ManualCategoryOverride):
        rows = (await db.execute(select(model).join(Transaction, Transaction.transaction_id == model.transaction_id)
                .where(Transaction.account_id == account_id).order_by(model.transaction_id)
                .execution_options(populate_existing=True))).scalars()
        override_snapshot.extend((model.__tablename__, r.transaction_id, r.updated_at, r.cleared_at,
                                  getattr(r, "category", None), getattr(r, "transaction_type", None)) for r in rows)
    # Raw payload fingerprints cover raw-only changes without exposing payloads.
    manifest = {"version": 1, "target": {"user_id": user_id, "item_id": item.item_id,
                "account_id": account_id, "institution": item.institution_name, "name": account.name,
                "mask": account.mask, "status": item.status, "type": account.type, "subtype": account.subtype},
                "adapter": adapter.name, "adapter_version": adapter.version, "file_sha256": file_hash,
                "through": through.isoformat() if through else None, "parser": parsed.report(),
                "counts": counts, "rows": entries, "blockers": sorted(set(blockers)),
                "existing_batch_id": previous.batch_id if previous else None,
                "external_classification_digest": auto_fingerprint,
                "override_snapshot": digest(override_snapshot),
                "raw_snapshot": digest([(r.transaction_id, r.source, r.is_removed, r.transaction_date,
                                         r.payload) for r in raw])}
    # Payment candidates are advisory only: never write counterpart flags during import.
    candidates = (await db.execute(select(Transaction).join(Account, Account.account_id == Transaction.account_id)
                 .join(Item, Item.item_id == Account.item_id)
                 .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
                 .where(Item.user_id == user_id, Item.status.in_(("pending", "active")),
                        Account.consumer_transactions_enabled.is_(True), RawTransaction.is_removed.is_(False),
                        Account.item_id == RawTransaction.item_id, Account.account_id == RawTransaction.account_id,
                        Transaction.account_id != account_id,
                        Transaction.transaction_type.in_(("payment", "transfer"))))).scalars().all()
    manifest["payment_candidates"] = [{"record": r.source_record, "transaction_id": t.transaction_id}
        for r in parsed.transactions if r.kind == "payment" and r.amount > 0
        for t in candidates if t.amount == -r.amount and abs((t.transaction_date-r.transaction_date).days) <= 3]
    manifest["digest"] = digest(manifest)
    return manifest


async def apply(db, user_id, account_id, adapter, data, through, approved, confirmation):
    await lock_consumer_derivation(db, user_id)
    if confirmation != approved.get("digest"):
        raise ImportBlocked("Explicit reviewed digest confirmation required")
    if digest({k: v for k, v in approved.items() if k != "digest"}) != confirmation:
        raise ImportBlocked("Manifest was edited; generate a new preview")
    item, account = await target(db, user_id, account_id, adapter, lock=True)
    if (approved["target"]["account_id"] != account_id or approved["target"]["user_id"] != user_id
            or approved["file_sha256"] != hashlib.sha256(data).hexdigest()
            or approved["adapter"] != adapter.name or approved["adapter_version"] != adapter.version
            or approved["through"] != (through.isoformat() if through else None)):
        raise ImportBlocked("File, target, or parser settings differ from approval")
    existing = await db.scalar(select(StatementImportBatch).where(
        StatementImportBatch.account_id == account_id, StatementImportBatch.adapter == adapter.name,
        StatementImportBatch.file_sha256 == approved["file_sha256"])
        .execution_options(populate_existing=True))
    if existing:
        if (existing.status != "applied" or existing.import_through != through
                or existing.adapter_version != adapter.version or approved["blockers"]):
            raise ImportBlocked("Existing batch cannot be extended or restored")
        return {"batch_id": existing.batch_id, "status": existing.status, "inserted": 0, "idempotent": True}
    current = await preview(db, user_id, account_id, adapter, data, through)
    if current["digest"] != confirmation:
        raise ImportBlocked("Preview is stale; review a fresh preview")
    if current["blockers"]:
        raise ImportBlocked("Preview has blockers; no rows applied")
    batch = StatementImportBatch(batch_id=str(uuid.uuid4()), user_id=user_id, item_id=item.item_id,
            account_id=account_id, adapter=adapter.name, adapter_version=adapter.version,
            file_sha256=current["file_sha256"], import_through=through, preview_digest=confirmation,
            manifest=current, status="applied", applied_by=user_id)
    db.add(batch)
    await db.flush()
    decisions = {e["record"]: e for e in current["rows"]}
    for row in adapter.parse(data, through=through).transactions:
        entry = decisions[row.source_record]
        ident = row_identity(account_id, row)
        db.add(StatementImportRow(row_id=ident, batch_id=batch.batch_id, source_record=row.source_record,
               source_line_end=row.source_line_end, fingerprint=digest(asdict(row)),
               disposition=entry["disposition"], canonical=canonical(row), source_evidence=list(row.source_fields)))
        await db.flush()
        if entry["disposition"] != "new":
            continue
        raw = RawTransaction(transaction_id=ident, item_id=item.item_id, account_id=account_id,
                             transaction_date=row.transaction_date, source="statement", statement_row_id=ident,
                             payload=canonical(row), is_removed=False)
        db.add(raw)
        await db.flush()
        seed = (statement_classification(row.kind, row.amount)
                if item.status == "active" else None) or (None, None, None)
        db.add(Transaction(transaction_id=ident, account_id=account_id, transaction_date=row.transaction_date,
                           **normalized_raw_values(raw), transaction_type=seed[0], is_spending=seed[1],
                           is_internal_transfer=seed[2]))
    await db.flush()
    return {"batch_id": batch.batch_id, "status": "applied", "inserted": current["counts"]["new"], "idempotent": False}


async def rollback_preview(db, user_id, batch_id, lock=False):
    batch = await db.scalar(select(StatementImportBatch).where(StatementImportBatch.batch_id == batch_id,
                                                            StatementImportBatch.user_id == user_id)
                            .execution_options(populate_existing=True))
    if batch is None:
        raise ImportBlocked("Batch not found for current user")
    owner = await db.scalar(select(Item.user_id).where(Item.item_id == batch.item_id))
    if owner != user_id:
        raise ImportBlocked("Batch Item ownership changed")
    if lock:
        await db.execute(select(Item).where(Item.item_id == batch.item_id).with_for_update())
        await db.execute(select(Account).where(Account.account_id == batch.account_id).with_for_update())
        await db.refresh(batch, with_for_update=True)
    rows = (await db.execute(select(RawTransaction).join(StatementImportRow,
            StatementImportRow.row_id == RawTransaction.statement_row_id)
            .where(StatementImportRow.batch_id == batch_id)
            .execution_options(populate_existing=True))).scalars().all()
    ids = [r.transaction_id for r in rows]
    blockers = []
    expected = {e["transaction_id"]: e["canonical"] for e in batch.manifest["rows"]
                if e["disposition"] == "new"}
    if set(ids) != set(expected) or any(r.payload != expected.get(r.transaction_id) for r in rows):
        blockers.append("batch_rows_missing_or_changed")
    if any(r.source != "statement" or r.account_id != batch.account_id or r.item_id != batch.item_id for r in rows):
        blockers.append("ownership_or_source_conflict")
    external = await external_classifications(db, user_id, ids)
    if batch.status != "rolled_back" and external != batch.manifest["external_classification_digest"]:
        blockers.append("external_classifications_changed_requires_reconciliation")
    override_rows = []
    for model in (ManualClassificationOverride, ManualCategoryOverride):
        for row in (await db.execute(select(model).where(model.transaction_id.in_(ids))
                                    .execution_options(populate_existing=True))).scalars():
            override_rows.append((model.__tablename__, row.transaction_id, row.updated_at, row.cleared_at))
    result = {"batch_id": batch_id, "status": batch.status, "rows": len(rows),
              "active_rows": sum(not r.is_removed for r in rows), "override_rows": len(override_rows),
              "blockers": blockers, "snapshot": digest([external, override_rows,
                  [(r.transaction_id, r.is_removed, r.payload) for r in rows]])}
    result["digest"] = digest(result)
    return result, batch, rows


async def rollback(db, user_id, batch_id, confirmation, reason):
    await lock_consumer_derivation(db, user_id)
    if not reason or not reason.strip():
        raise ImportBlocked("Rollback reason required")
    result, batch, rows = await rollback_preview(db, user_id, batch_id, lock=True)
    if batch.status == "rolled_back":
        return {"batch_id": batch_id, "status": "rolled_back", "withdrawn": 0}
    if result["digest"] != confirmation or result["blockers"]:
        raise ImportBlocked("Rollback blocked or stale; review rollback preview")
    for row in rows:
        row.is_removed = True
    batch.status = "rolled_back"
    batch.rolled_back_by = user_id
    batch.rolled_back_at = datetime.now(timezone.utc).replace(tzinfo=None)
    batch.rollback_reason = reason.strip()
    await db.flush()
    return {"batch_id": batch_id, "status": "rolled_back", "withdrawn": len(rows)}


async def block_plaid_overlap(db, item_id, transactions):
    """Temporary Phase 2 guard. Caller transaction rolls back cursor and all writes."""
    if not transactions:
        return
    accounts = {t["account_id"] for t in transactions}
    imported = (await db.execute(select(RawTransaction).where(RawTransaction.item_id == item_id,
                RawTransaction.account_id.in_(accounts), RawTransaction.source == "statement",
                RawTransaction.is_removed.is_(False))
                .execution_options(populate_existing=True))).scalars().all()
    for tx in transactions:
        incoming_date = tx["date"] if isinstance(tx["date"], date) else date.fromisoformat(tx["date"])
        for row in imported:
            if row.account_id != tx["account_id"]:
                continue
            amount, currency = raw_amount_currency(row)
            # Unknown currency is conservatively treated as potentially overlapping.
            if candidate_match(incoming_date, -Decimal(str(tx["amount"])),
                               tx.get("iso_currency_code") or currency,
                               row.transaction_date, amount, currency):
                raise ImportBlocked("Plaid overlaps a statement import; reconciliation required before sync")
