"""Synthetic rehearsal: fingerprints before and after the institution lifecycle migration.

Run each phase against a disposable loopback database, with PYTHONPATH pointing at
the code under test: `seed` and `fingerprint` with the old code, then `migrate`
and `fingerprint` with the new code. Only interfaces present in both versions are
used. Synthetic data and a fake Plaid client only; it refuses non-loopback hosts,
the default port and PLAID_ENV=production.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import sys
from datetime import date, timedelta

USER = "rehearsal-user"


def _guard():
    from sqlalchemy.engine import make_url
    url = make_url(os.environ["DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost"} or url.port in {None, 5432}:
        raise SystemExit("Refusing: rehearsal needs a loopback database on a non-default port")
    if os.environ.get("PLAID_ENV", "").lower() == "production":
        raise SystemExit("Refusing: PLAID_ENV is production")
    os.environ["PLAID_PILOT_USER_ID"] = USER


class _Response:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class FakePlaid:
    def __init__(self, pages):
        self.pages = pages

    def transactions_sync(self, request, *, _request_timeout):
        item = request.to_dict()["access_token"].removeprefix("token-")
        added, cursor = self.pages[item]
        return _Response({"added": added, "modified": [], "removed": [], "next_cursor": cursor,
                          "has_more": False, "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"})


def _tx(ident, account, amount, day, name, category, merchant=None):
    return {"transaction_id": ident, "account_id": account, "date": day, "amount": amount,
            "name": name, "merchant_name": merchant, "personal_finance_category": {"primary": category}}


def synthetic_pages():
    rng = random.Random(20261002)
    start = date(2026, 3, 1)
    merchants = [("COFFEE SHOP", "FOOD_AND_DRINK"), ("MARKET", "FOOD_AND_DRINK"),
                 ("BOOK STORE", "GENERAL_MERCHANDISE"), ("AIRLINE", "TRAVEL"),
                 ("PHARMACY", "MEDICAL"), ("CINEMA", "ENTERTAINMENT")]
    pages = {"chase": [], "amex": [], "ally": []}
    for n in range(240):
        day = start + timedelta(days=rng.randrange(180))
        name, category = rng.choice(merchants)
        account = rng.choice(["chase-card", "chase-check", "amex-card"])
        amount = round(rng.uniform(3, 180), 2)
        pages[account.split("-")[0]].append(_tx(f"e{n}", account, amount, day, name, category, name.title()))
        if n % 17 == 0:
            pages[account.split("-")[0]].append(
                _tx(f"r{n}", account, -amount, day + timedelta(days=3), name, category, name.title()))
    for n in range(6):
        month = date(2026, 3 + n, 1)
        pages["chase"].append(_tx(f"pay{n}", "chase-check", -3200, month, "PAYROLL", "INCOME"))
        pages["chase"].append(_tx(f"cardpay{n}", "chase-check", 900, month + timedelta(days=10),
                                  "AMEX EPAYMENT", "TRANSFER_OUT"))
        pages["amex"].append(_tx(f"cardpaid{n}", "amex-card", -900, month + timedelta(days=11),
                                 "PAYMENT RECEIVED", "TRANSFER_IN"))
        pages["chase"].append(_tx(f"zin{n}", "chase-check", -75, month + timedelta(days=14),
                                  f"ZELLE PAYMENT FROM SAM CONF# ABCD{n:04d}", "INCOME"))
        pages["ally"].append(_tx(f"zout{n}", "ally-check", 75, month + timedelta(days=14),
                                 f"ZELLE PAYMENT TO RANDY CONF# ABCD{n:04d}", "TRANSFER_OUT"))
        pages["amex"].append(_tx(f"credit{n}", "amex-card", -15, month + timedelta(days=5),
                                 "UBER CASH", "TRANSFER_IN"))
    pages["chase"].append(_tx("brokerage", "chase-invest", 500, date(2026, 4, 2), "BUY", "TRANSFER_OUT"))
    return pages


async def seed():
    from sqlalchemy import text
    from api import db as database
    from api.card_benefits import AMERICAN_EXPRESS_INSTITUTION_ID
    from api.models import Account, Item, ManualCategoryOverride, ManualClassificationOverride
    from api.services.derivation import classify_active_transactions, normalize_item_transactions
    from api.services.persistence import persist_consumer_transactions
    from api.services.sync_all import sync_all

    await database.init_db()
    pages = synthetic_pages()
    async with database.SessionLocal.begin() as db:
        for item_id, institution, name, status in (
                ("chase", "ins_56", "Chase", "active"),
                ("amex", AMERICAN_EXPRESS_INSTITUTION_ID, "American Express", "active"),
                ("ally", "ins_ally", "Ally", "pending"),
                ("rejected", "ins_rejected", "Rejected", "disabled")):
            db.add(Item(item_id=item_id, user_id=USER, institution_id=institution, institution_name=name,
                        status=status, access_token="token-" + item_id))
        await db.flush()
        for account_id, item_id, name, kind, enabled in (
                ("chase-check", "chase", "Checking", "depository", True),
                ("chase-card", "chase", "Freedom", "credit", True),
                ("chase-invest", "chase", "Brokerage", "investment", False),
                ("amex-card", "amex", "Platinum Card", "credit", True),
                ("ally-check", "ally", "Ally Checking", "depository", True)):
            db.add(Account(account_id=account_id, item_id=item_id, name=name, type=kind,
                           consumer_transactions_enabled=enabled))
    client = FakePlaid({"chase": (pages["chase"], "chase-1"), "amex": (pages["amex"], "amex-1")})
    result = await sync_all(USER, client=client)
    assert result["status"] == "success", result
    async with database.SessionLocal.begin() as db:
        await persist_consumer_transactions(db, USER, "ally", None, pages["ally"], [], [], "ally-1", 1)
        await normalize_item_transactions(db, USER, "ally")
    async with database.SessionLocal.begin() as db:
        db.add(ManualClassificationOverride(transaction_id="e3", transaction_type="reimbursement",
                                            created_by="rehearsal", updated_by="rehearsal"))
        db.add(ManualCategoryOverride(transaction_id="e5", category="GROCERIES",
                                      created_by="rehearsal", updated_by="rehearsal"))
        await db.execute(text("UPDATE raw_transactions SET is_removed = true WHERE transaction_id = 'e7'"))
    async with database.SessionLocal.begin() as db:
        await classify_active_transactions(db, USER)
    await database.engine.dispose()


async def migrate():
    from api import db as database
    await database.init_db()
    await database.engine.dispose()


async def fingerprint(reclassify):
    from sqlalchemy import select, text
    from api import db as database
    from api.models import Item
    from api.routes import analytics
    from api.services.derivation import classify_active_transactions
    from statement_imports.persistence import external_classifications

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    if reclassify:
        async with database.SessionLocal.begin() as db:
            await classify_active_transactions(db, USER)
    async with database.SessionLocal() as db:
        transactions = await db.scalar(text(
            "SELECT md5(coalesce(string_agg((to_jsonb(t) - 'created_at' - 'updated_at')::text, "
            "E'\\n' ORDER BY t.transaction_id), '')) FROM transactions t"))
        raw = await db.scalar(text(
            "SELECT md5(coalesce(string_agg((to_jsonb(r) - 'created_at' - 'updated_at')::text, "
            "E'\\n' ORDER BY r.transaction_id), '')) FROM raw_transactions r"))
        items = [(row.item_id, row.status, row.transactions_cursor,
                  hashlib.sha256(row.access_token.encode()).hexdigest()[:12])
                 for row in (await db.execute(select(Item).order_by(Item.item_id))).scalars()]
        classifications = await external_classifications(db, USER)
        rows = await analytics._active_analytics_rows(date(1900, 1, 1), date(9999, 12, 31), db)
        months = {}
        for row in rows:
            months.setdefault(row[0].transaction_date.strftime("%Y-%m"), []).append(row)
        monthly = {month: analytics.summarize_monthly_transactions(month_rows)
                   for month, month_rows in sorted(months.items())}
    await database.engine.dispose()
    return {"transactions_md5": transactions, "raw_transactions_md5": raw, "items": items,
            "classification_digest": classifications, "analytics_rows": len(rows),
            "analytics_months": sorted(monthly), "analytics_digest": digest(monthly),
            "analytics_income_by_month": {m: str(v["income"]) for m, v in monthly.items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["seed", "migrate", "fingerprint"])
    parser.add_argument("--reclassify", action="store_true")
    args = parser.parse_args()
    _guard()
    if args.phase == "seed":
        asyncio.run(seed())
    elif args.phase == "migrate":
        asyncio.run(migrate())
    else:
        json.dump(asyncio.run(fingerprint(args.reclassify)), sys.stdout, indent=2, sort_keys=True)
        print()


if __name__ == "__main__":
    main()
