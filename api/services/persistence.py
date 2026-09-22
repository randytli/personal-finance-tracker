"""Plaid persistence using a caller-owned transaction and session."""

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from api.consumer_scope import initial_consumer_scope, account_type_drift
from api.models import Account, Item, RawTransaction
from api.statement_semantics import lock_consumer_derivation


async def persist_consumer_transactions(db, user_id, item_id, starting_cursor, added, modified, removed, cursor, pages_fetched):
    accepted_added, accepted_modified, accepted_removed = [], [], []
    skipped = {"added": 0, "modified": 0, "removed": 0}
    await lock_consumer_derivation(db, user_id)
    item = (await db.execute(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id,
        Item.status.in_(("pending", "active")),
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if item is None or item.transactions_cursor != starting_cursor:
        raise HTTPException(409, "Item changed during sync; retry")
    accounts = {a.account_id: a for a in (await db.execute(
        select(Account).where(Account.item_id == item_id)
        .order_by(Account.account_id).with_for_update().execution_options(populate_existing=True)
    )).scalars()}
    ids = {t["transaction_id"] for t in added + modified + removed}
    existing = {r.transaction_id: r for r in (await db.execute(
        select(RawTransaction).where(RawTransaction.transaction_id.in_(ids))
        .execution_options(populate_existing=True)
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



async def persist_account_metadata(db, user_id, item_id, accounts):
    drift = []
    safe_accounts = []
    await lock_consumer_derivation(db, user_id)
    item = (await db.execute(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id,
        Item.status.in_(("active", "pending")),
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Item not found")
    account_ids = sorted({account["account_id"] for account in accounts})
    if account_ids:
        await db.execute(select(Account).where(Account.account_id.in_(account_ids))
                         .order_by(Account.account_id).with_for_update())
    for account in accounts:
        existing = await db.get(Account, account["account_id"], populate_existing=True)
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
