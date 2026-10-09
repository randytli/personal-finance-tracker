"""M5 R13: CPU scaling of build_classifications on synthetic rows (no database).

python -m scripts.pft_m5_classification_profile [--sizes 5000,10000,20000,40000] [--profile]

Rows are synthetic and deterministic (seeded). The mix roughly follows a
consumer ledger: mostly card expenses, some unmatched credits, transfer pairs
across accounts and a few refunds. Prints wall time per size and, with
--profile, the top cumulative functions for the largest size.
"""
import argparse
import cProfile
from datetime import date, timedelta
from decimal import Decimal
import io
import pstats
import random
import time

from api.classification_rules import ClassificationCandidate, build_classifications

ACCOUNTS = [f"acct-{i}" for i in range(6)]
MERCHANTS = [f"MERCHANT {i:03d}" for i in range(400)]
CATEGORIES = ["FOOD_AND_DRINK", "GENERAL_MERCHANDISE", "TRANSPORTATION", "TRAVEL", "ENTERTAINMENT"]


def synthetic_rows(n, seed=20261009):
    rng = random.Random(seed)
    start = date(2020, 1, 1)
    days = 365 * 6
    rows = []

    def add(account, day, amount, merchant, description, category):
        rows.append(ClassificationCandidate(
            transaction_id=f"tx-{len(rows)}", item_id="item", account_id=account,
            transaction_date=start + timedelta(days=day), amount=Decimal(amount),
            merchant_name=merchant, description=description, plaid_category=category,
            statement_kind=None))

    while len(rows) < n:
        roll = rng.random()
        day = rng.randrange(days)
        account = rng.choice(ACCOUNTS)
        merchant = rng.choice(MERCHANTS)
        amount = f"{rng.randrange(100, 20000) / 100:.2f}"
        if roll < 0.78:
            add(account, day, "-" + amount, merchant, merchant + " PURCHASE", rng.choice(CATEGORIES))
        elif roll < 0.88:
            add(account, day, amount, None, f"CREDIT {rng.randrange(10**6)}", "OTHER")
        elif roll < 0.96:
            other = rng.choice([a for a in ACCOUNTS if a != account])
            add(account, day, "-" + amount, None, "ONLINE TRANSFER", "TRANSFER_OUT")
            add(other, day + rng.randrange(3), amount, None, "ONLINE TRANSFER", "TRANSFER_IN")
        else:
            category = rng.choice(CATEGORIES)
            add(account, day, "-" + amount, merchant, merchant + " PURCHASE", category)
            add(account, day + rng.randrange(1, 30), amount, merchant, merchant + " REFUND", category)
    return rows[:n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="5000,10000,20000,40000")
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",")]
    for n in sizes:
        rows = synthetic_rows(n)
        started = time.perf_counter()
        _, refunds = build_classifications(rows)
        print(f"n={n:>6} wall_s={time.perf_counter() - started:7.2f} refund_matches={refunds}")
    if args.profile:
        rows = synthetic_rows(sizes[-1])
        profiler = cProfile.Profile()
        profiler.enable()
        build_classifications(rows)
        profiler.disable()
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(12)
        print(stream.getvalue())


if __name__ == "__main__":
    main()
