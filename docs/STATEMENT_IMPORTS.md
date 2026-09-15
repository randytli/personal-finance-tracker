# Statement imports: Phase 1

Parsing and dry-run only. This standalone Python package imports no database or
Plaid application code and needs no environment configuration or credentials.
It never persists transactions. Keep real exports outside the repository;
committed fixtures contain synthetic data only.

Run from the repository root:

```sh
.venv/bin/python -m statement_imports dry-run /path/to/statement.csv --adapter robinhood-gold-card --through 2026-07-21
```

Omit --through to preview the whole export. The cutoff is inclusive and uses the
CSV Date, with no timezone inference from Time. JSON output includes eligible
date range, kind counts, signed totals, skip reasons, and safe row-indexed issues.
Exit code 2 means parsing errors (the preview may be partial); 0 permits warnings.
Output does not contain source rows, cardholder names, or per-transaction details.
Signed totals include payments and are not spending analytics.

Adapters implement StatementImportAdapter.parse(bytes, through=...) and return
Preview containing ImportedTransaction records. Canonical records contain date,
Decimal signed amount, currency, source transaction kind, merchant/description,
adapter/version, file SHA-256, CSV record number, ending physical line number,
original amount, and original header/value pairs. Source record numbers exclude
the header. Original pairs and the private source file preserve provenance; hashes
are not a deduplication policy.

The initial adapter accepts the observed Robinhood Gold Card UTF-8 export columns:
Date, Time, Cardholder, Amount, Points, Balance, Status, Type, Merchant, Description.
Column order may vary; missing/duplicate headers are errors. Additional columns
are preserved with a warning. Blank/malformed records produce errors.

Only Posted records qualify. Declined and other statuses are skipped; other statuses
raise a warning. Date must be YYYY-MM-DD. Purchase/Fee amounts must be nonnegative
and Refund/Payment amounts nonpositive; normalized amount is the negated source
amount. Zero is retained with a warning. Amounts use exact decimal arithmetic.
Unknown kinds, contradictory signs, and malformed values are not guessed.
USD is an explicit assumption/warning because this export has no currency column.

Kinds purchase/refund/payment/fee describe source events, not automatic PFT
classifications. No category, account, transaction-type rules, or analytics formulas
are changed. Next phase must separately design account targeting, provenance
persistence, deduplication, reviewed apply/rollback, and classification integration.
