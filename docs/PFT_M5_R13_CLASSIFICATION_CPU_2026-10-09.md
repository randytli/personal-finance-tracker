# M5 R13: `build_classifications` CPU — 2026-10-09

Status: **measured locally on synthetic rows. The fix is applied in `api/classification_rules.py` on branch `m5-unattended-20261009` (uncommitted, pending owner review) and proven equivalent to the original.** No database, cloud, Production or Plaid access.

## Finding

`api/classification_rules.build_classifications` has two quadratic candidate scans:

1. **Refund matching**, lines 174–213. For every unclassified credit, the code scans **all** expenses twice: once for same-day candidates and once for historical candidates.
2. **Transfer pairing**, lines 273–284. All eligible transfers are compared pairwise.

Every filter in both scans requires an exact key match:
- Refund candidates need the same `account_id` and `abs(expense.amount) == credit.amount`.
- Transfer pairs need `amount == -counterpart.amount != 0`.

So only rows sharing that key can ever match.

## Measurements [M, local, synthetic]

Script: `python -m scripts.pft_m5_classification_profile --profile`. The rows are a seeded synthetic ledger: 6 accounts, 400 merchants, about 78% card expenses, unmatched credits, transfer pairs and refunds. Python 3.12.3, WSL2.

| rows | current (s) | bucketed prototype (s) | identical output |
| ---: | ---: | ---: | --- |
| 5,000 | 0.14 | — | — |
| 10,000 | 0.47 | 0.024 | yes |
| 20,000 | 1.82 | 0.051 | yes |
| 35,600 | 6.14 | 0.097 | yes |
| 40,000 | 7.80 | 0.115 | yes |
| 80,000 | not run | 0.252 | — |

- Current code: doubling n multiplies the time by about 4, so it is O(n²).
- cProfile at 40k: 8.4 of 9.4 s are spent inside `build_classifications` itself, in its list comprehensions. `SequenceMatcher` takes only 0.06 s.
- The earlier cloud figure was 2.87 s at 35,600 real rows [M, round-trip fix doc]. The synthetic ledger has proportionally more unmatched credits, so its absolute times run higher. The scaling is what matters.

## Change (applied on the branch, uncommitted)

`api/classification_rules.build_classifications` keeps the same rules; only the two scans change:

- Expenses are indexed by `(account_id, abs(amount))`. Each credit looks only at its own bucket.
- Eligible transfers with a non-zero amount are grouped by `abs(amount)`. Pairs are compared only within a group.
- Bucket lists keep input order. The rules only use candidate counts and the single candidate, so the results do not change.

Equivalence test: `tests/test_m5_classification_bucketed.py` compares full results (the classification map and `refund_matches`) of the new application function with a frozen copy of the original, `experiments/m5_cloud/classification_quadratic_reference.py`:
- 5 seeds × 2 sizes of the synthetic ledger;
- 40 seeds of a collision-heavy set: 3 accounts, 6 amounts including `10`/`10.0`/`10.00` and `0`, 20 days, Zelle confirmation codes, interest descriptions, and random manual types.

Mutation check, done on the prototype: two wrong variants were both caught. One drops `abs()` from the refund key; the other buckets transfers by signed amount. Full suite with the change: 386 tests, 0 failures, 21 skipped (age binary or PyJWT not present locally).

## Recommendation (owner decision)

- Review and commit the change on the branch. It is behaviour-preserving.
- Keep the reference and the equivalence test for at least one release.
- This change touches classification code, so per `pft-safe-development` it should go through the normal review. It does not change any rule or formula.
- With this change, catch-up and history growth no longer put classification CPU at risk of the G2 deadline: about 0.1 s at today's size, versus multiple seconds growing as O(n²).

## Not done

- No measurement on real Production rows (not allowed unattended).
- Not deployed anywhere.
