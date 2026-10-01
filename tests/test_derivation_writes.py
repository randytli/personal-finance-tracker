"""Derivation write-set tests on disposable PostgreSQL schemas with synthetic Plaid only.

The legacy functions below are the pre-diff-write normalization and classification
loops, kept verbatim as a differential reference: every scenario must leave the
same financial state as rewriting every row on every sync.
"""

import os
import unittest
import uuid
from datetime import date
from unittest.mock import patch

from sqlalchemy import event, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.models import Account, Base, Item, ManualClassificationOverride, RawTransaction, Transaction
from api.services import derivation
from api.services import sync_all as service
from api.statement_semantics import lock_consumer_derivation, normalized_raw_values
from statement_imports.persistence import external_classifications

USER = "synthetic-user"


async def legacy_normalize_item_transactions(db, user_id, item_id):
    await lock_consumer_derivation(db, user_id)
    item = await db.scalar(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id,
        Item.status.in_(("pending", "active")),
    ).with_for_update().execution_options(populate_existing=True))
    await db.execute(select(Account).where(Account.item_id == item_id)
                     .order_by(Account.account_id).with_for_update())
    result = await db.execute(
        select(RawTransaction).join(Account,
            (Account.account_id == RawTransaction.account_id)
            & (Account.item_id == RawTransaction.item_id)).where(
            RawTransaction.item_id == item.item_id,
            RawTransaction.is_removed.is_(False),
            Account.consumer_transactions_enabled.is_(True),
        ).execution_options(populate_existing=True)
    )
    raw_transactions = result.scalars().all()
    for raw_transaction in raw_transactions:
        derivation.validate_normalization_input(raw_transaction)
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
        await db.execute(statement.on_conflict_do_update(
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
        ))
    return {"normalized_count": len(raw_transactions)}


async def legacy_classify_active_transactions(db, user_id):
    await lock_consumer_derivation(db, user_id)
    inputs = await derivation._classification_inputs(db, user_id, Item.status == "active")
    classifications, _ = derivation.build_classifications(
        *inputs[:4], active_manual_types=inputs[4])
    classified = 0
    for transaction in sorted(inputs[0], key=lambda candidate: candidate.transaction_id):
        transaction_type, is_spending, is_internal_transfer = classifications[transaction.transaction_id]
        await db.execute(update(Transaction)
                         .where(Transaction.transaction_id == transaction.transaction_id)
                         .values(transaction_type=transaction_type, is_spending=is_spending,
                                 is_internal_transfer=is_internal_transfer))
        classified += transaction_type is not None
    return {"classified_count": classified}


class Response:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class Client:
    """Synthetic SDK: one page per Item; an omitted token is a no-op page."""

    def __init__(self, cursors, added=(), modified=(), removed=()):
        self.cursors = cursors
        self.added, self.modified, self.removed = list(added), list(modified), list(removed)

    def transactions_sync(self, request, *, _request_timeout):
        token = request.to_dict()["access_token"]
        item = token.removeprefix("token-")
        owned = lambda rows: [row for row in rows if row.get("item") == item]
        strip = lambda rows: [{k: v for k, v in row.items() if k != "item"} for row in owned(rows)]
        return Response({"added": strip(self.added), "modified": strip(self.modified),
                         "removed": strip(self.removed), "next_cursor": self.cursors[item],
                         "has_more": False, "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"})


def plaid_tx(ident, account, amount, day, name, category, merchant=None):
    return {"item": account.split("-")[0], "transaction_id": ident, "account_id": account,
            "date": date(2026, 8, day), "amount": amount, "name": name, "merchant_name": merchant,
            "personal_finance_category": {"primary": category}}


def removal(ident, account):
    return {"item": account.split("-")[0], "transaction_id": ident}


class SyntheticSchema:
    """One disposable schema with two active Items and a disabled investment account."""

    def __init__(self, url):
        self.name = "derivation_test_" + uuid.uuid4().hex
        self.url = url
        self.cursor = 0
        self.statements = []
        self.recording = False

    async def create(self, admin):
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.name}"'))
        self.engine = create_async_engine(self.url, connect_args={
            "server_settings": {"search_path": self.name}})

        @event.listens_for(self.engine.sync_engine, "before_cursor_execute")
        def record(connection, cursor, statement, parameters, context, executemany):
            if self.recording:
                self.statements.append(statement)

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            for item_id in ("a", "b"):
                db.add(Item(item_id=item_id, user_id=USER, institution_id="ins_" + item_id,
                            institution_name="Synthetic", status="active", access_token="token-" + item_id,
                            transactions_cursor="start"))
                await db.flush()
                db.add(Account(account_id=item_id + "-card", item_id=item_id, name="Card",
                               type="credit", consumer_transactions_enabled=True))
                db.add(Account(account_id=item_id + "-check", item_id=item_id, name="Checking",
                               type="depository", consumer_transactions_enabled=True))
            db.add(Account(account_id="a-invest", item_id="a", name="Brokerage",
                           type="investment", consumer_transactions_enabled=False))

    async def drop(self, admin):
        await self.engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.name}" CASCADE'))

    async def sync(self, added=(), modified=(), removed=(), *, legacy=False):
        self.cursor += 1
        client = Client({"a": f"a-{self.cursor}", "b": f"b-{self.cursor}"}, added, modified, removed)
        patches = []
        if legacy:
            patches = [patch.object(service, "normalize_item_transactions", legacy_normalize_item_transactions),
                       patch.object(service, "classify_active_transactions", legacy_classify_active_transactions)]
        for active in patches:
            active.start()
        try:
            result = await service.sync_all(USER, client=client, session_factory=self.sessions,
                                            engine=self.engine)
        finally:
            for active in patches:
                active.stop()
        assert result["status"] == "success", result
        return result

    async def fingerprints(self):
        async with self.sessions() as db:
            classifications = await external_classifications(db, USER)
            # Timestamps are bookkeeping; every financial column must match exactly.
            rows = await db.scalar(text(
                "SELECT md5(coalesce(string_agg((to_jsonb(t) - 'created_at' - 'updated_at')::text, "
                "E'\\n' ORDER BY t.transaction_id), '')) FROM transactions t"))
            cursors = (await db.execute(select(Item.item_id, Item.transactions_cursor)
                                        .order_by(Item.item_id))).all()
        return {"classifications": classifications, "transactions": rows, "cursors": cursors}

    async def classification(self, transaction_id):
        async with self.sessions() as db:
            row = await db.get(Transaction, transaction_id)
            return row.transaction_type, row.is_spending, row.is_internal_transfer

    async def override(self, transaction_id, transaction_type):
        async with self.sessions.begin() as db:
            db.add(ManualClassificationOverride(transaction_id=transaction_id, transaction_type=transaction_type,
                                                created_by="test", updated_by="test"))


@unittest.skipUnless(os.environ.get("PFT_SYNC_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class DerivationWriteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine as default_engine
        self.assertEqual(default_engine.url.port, 55439)
        self.assertIn(default_engine.url.host, {"127.0.0.1", "localhost"})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.url = default_engine.url
        self.admin = create_async_engine(self.url)
        self.schemas = []

    async def asyncTearDown(self):
        for schema in self.schemas:
            await schema.drop(self.admin)
        await self.admin.dispose()

    async def schema(self):
        schema = SyntheticSchema(self.url)
        await schema.create(self.admin)
        self.schemas.append(schema)
        return schema

    async def test_diff_writes_match_full_rewrite_across_sync_scenarios(self):
        legacy, current = await self.schema(), await self.schema()

        async def step(name, *args, **kwargs):
            await legacy.sync(*args, legacy=True, **kwargs)
            await current.sync(*args, **kwargs)
            expected, actual = await legacy.fingerprints(), await current.fingerprints()
            self.assertEqual(actual, expected, name)
            return actual

        seed = await step("seed", added=[
            plaid_tx("e1", "a-card", 25, 1, "COFFEE SHOP", "FOOD_AND_DRINK", "Coffee Shop"),
            plaid_tx("r1", "a-card", -25, 5, "COFFEE SHOP", "FOOD_AND_DRINK", "Coffee Shop"),
            plaid_tx("e2", "b-card", 40, 2, "BOOK STORE", "GENERAL_MERCHANDISE", "Book Store"),
            plaid_tx("t-out", "a-check", 100, 3, "TRANSFER TO CARD", "TRANSFER_OUT"),
            plaid_tx("z1", "a-check", 50, 4, "ZELLE PAYMENT TO ALEX CONF# ABCD1234", "TRANSFER_OUT"),
            plaid_tx("z2", "b-check", -50, 4, "ZELLE PAYMENT FROM SAM CONF# ABCD1234", "TRANSFER_IN"),
            plaid_tx("pay", "b-check", -2000, 1, "PAYROLL", "INCOME"),
            plaid_tx("skip", "a-invest", 10, 1, "BROKERAGE BUY", "TRANSFER_OUT"),
        ])
        self.assertEqual(await current.classification("r1"), ("refund", False, False))
        self.assertEqual(await current.classification("z1"), ("transfer", False, True))
        self.assertEqual(await current.classification("z2"), ("transfer", False, True))
        self.assertEqual(await current.classification("t-out"), ("transfer", False, None))

        no_op = await step("no-op")
        self.assertEqual((no_op["classifications"], no_op["transactions"]),
                         (seed["classifications"], seed["transactions"]))

        await step("added counterpart forms a transfer pair", added=[
            plaid_tx("t-in", "b-card", -100, 4, "TRANSFER FROM CHECKING", "TRANSFER_IN"),
            plaid_tx("e3", "a-card", 12.34, 6, "LUNCH", "FOOD_AND_DRINK", "Deli"),
        ])
        self.assertEqual(await current.classification("t-out"), ("transfer", False, True))

        await step("modified expense breaks the refund match", modified=[
            plaid_tx("e1", "a-card", 30, 1, "COFFEE SHOP", "FOOD_AND_DRINK", "Coffee Shop"),
            plaid_tx("e2", "b-card", 40, 2, "BOOK STORE ONLINE", "GENERAL_MERCHANDISE", "Book Store"),
        ])
        self.assertEqual(await current.classification("r1"), (None, None, None))

        await legacy.override("z1", "expense")
        await current.override("z1", "expense")
        await step("override then no-op blocks the Zelle pair")
        self.assertEqual(await current.classification("z2"), ("transfer", False, None))

        await step("removed counterpart unpairs the transfer", removed=[removal("t-in", "b-card")])
        self.assertEqual(await current.classification("t-out"), ("transfer", False, None))
        await step("final no-op")

    async def test_noop_classification_issues_no_row_updates(self):
        schema = await self.schema()
        await schema.sync(added=[
            plaid_tx(f"e{i}", "a-card", 10 + i, 1 + i % 20, f"SHOP {i}", "GENERAL_MERCHANDISE")
            for i in range(30)
        ])
        schema.recording = True
        async with schema.sessions.begin() as db:
            result = await derivation.classify_active_transactions(db, USER)
        schema.recording = False
        self.assertEqual(result["expense"], 30)
        self.assertEqual([s for s in schema.statements if s.lstrip().upper().startswith("UPDATE TRANSACTIONS")], [])

    async def test_changed_classifications_are_written_in_one_statement(self):
        schema = await self.schema()
        await schema.sync(added=[
            plaid_tx("z1", "a-check", 50, 4, "ZELLE PAYMENT TO ALEX CONF# ABCD1234", "TRANSFER_OUT"),
            plaid_tx("z2", "b-check", -50, 4, "ZELLE PAYMENT FROM SAM CONF# ABCD1234", "TRANSFER_IN"),
            *[plaid_tx(f"e{i}", "a-card", 10 + i, 1 + i % 20, f"SHOP {i}", "GENERAL_MERCHANDISE")
              for i in range(10)],
        ])
        await schema.override("z1", "expense")
        schema.recording = True
        async with schema.sessions.begin() as db:
            await derivation.classify_active_transactions(db, USER)
        schema.recording = False
        updates = [s for s in schema.statements if s.lstrip().upper().startswith("UPDATE TRANSACTIONS")]
        self.assertEqual(len(updates), 1)
        self.assertEqual(await schema.classification("z1"), ("transfer", False, None))
        self.assertEqual(await schema.classification("z2"), ("transfer", False, None))
        self.assertEqual(await schema.classification("e0"), ("expense", True, False))


if __name__ == "__main__":
    unittest.main()
