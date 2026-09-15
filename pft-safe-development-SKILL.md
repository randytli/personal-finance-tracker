---
name: pft-safe-development
description: Use for planning, implementing, reviewing, testing, or validating changes in the Personal Finance Tracker repo, especially Plaid, transaction classification, analytics, statement imports, manual overrides, account scoping, and institution onboarding. Enforce incremental changes, financial-data preservation, explicit Production boundaries, and concise verification/reporting.
---

# PFT Safe Development

Use this workflow for work in the Personal Finance Tracker repository.

## Start by grounding in the repo

- Read the repo's `AGENTS.md` and the smallest relevant docs/code before proposing changes.
- Inspect `git status` and the relevant diff when uncommitted work exists.
- Prefer current repo behavior over assumptions from prior conversations.
- Do not repeat background that the repo already makes obvious.

## Choose the smallest appropriate mode

For low-risk local changes, implement directly unless the user asks for a plan.

Plan first when the task materially changes:
- database schema or migrations,
- Plaid Production behavior,
- ingestion/cursor semantics,
- financial classification semantics,
- cross-domain boundaries,
- destructive or difficult-to-reverse data handling.

For review/audit requests, remain read-only unless the user explicitly authorizes changes.

## Preserve financial invariants

Treat real financial data as durable.

- Never modify Production data or call Production Plaid APIs without explicit authorization for that action.
- Scope Production work to the exact Item/account/institution authorized.
- Do not sync or modify unrelated institutions.
- Keep pending Items out of normal active-only analytics until activation.
- `consumer_transactions_enabled` controls participation in the consumer transaction pipeline; it is not a statement about whether an account can contribute to future investment analytics.
- Consumer-disabled investment accounts must not enter consumer ingestion, classification, review, internal-transfer matching, or consumer analytics.
- Preserve Plaid-origin fields rather than rewriting them to represent normalized/manual values.
- Manual overrides must remain higher precedence than automatic classification/category logic.
- Do not change financial formulas unless the task explicitly requires it.

## Prefer reusable domain logic

Avoid institution-specific hacks when a stable account, merchant, adapter, or domain rule can express the behavior.

Examples:
- account scope by account type/domain rather than `if Robinhood`,
- merchant category normalization through shared rule tables,
- statement parsing through adapters that emit a canonical import model,
- shared analytics/effective-classification queries rather than endpoint-specific copies.

Keep Consumer Finance and Investments as separate pipelines unless a later aggregation layer explicitly combines interpreted financial events.

## Statement import rules

For statement/CSV work:

- Keep institution-specific parsing inside adapters.
- Preserve source provenance and original source evidence.
- Do not pretend imported rows are Plaid transactions.
- Dry-run before apply.
- Make imports idempotent and auditable.
- Detect duplicates against prior imports and Plaid data.
- If a match is ambiguous, block apply rather than guessing unless reviewed row-resolution tooling explicitly exists.
- Explicit statement kinds may seed high-confidence classifications:
  - Purchase/Fee -> expense
  - Refund -> refund
  - Payment -> payment
- Manual overrides still win.
- Unknown/unsupported source kinds fall back to normal classification rather than being force-mapped.

## Production acceptance pattern

When Production work is explicitly authorized:

1. Record a baseline for the exact affected scope plus preservation fingerprints for unrelated data.
2. Perform only the authorized operation.
3. Verify expected rows/state.
4. Re-check unrelated institutions/data/analytics for preservation.
5. Stop at the next authorization boundary.

Do not turn a narrow Production acceptance task into a broad cleanup or refactor.

## Testing and verification

Use focused tests while iterating, then run the appropriate broader checks before declaring completion.

Typical checks:
- relevant Python tests,
- full Python suite when practical,
- Python compilation,
- frontend build/typecheck when frontend/API shapes changed,
- migration/integration tests for schema changes,
- `git diff --check`.

Report skipped tests and why.

After backend/frontend changes, remind the user to restart the affected service before diagnosing runtime behavior. If Next.js shows stale build artifacts, clear `.next` only after restart does not resolve it.

## Git discipline

Keep changes checkpointable and reviewable.

- Do not rewrite unrelated user changes.
- Prefer logical commits, but do not artificially split heavily intertwined validated work.
- Before a checkpoint, inspect `git status`, tests, and `git diff --check`.
- Never commit real bank/credit-card CSV exports, secrets, tokens, or local Production env files.

## Final report

Keep reports concise. Include only what matters:

- files changed,
- behavior/architecture changed,
- verification results,
- whether any Production writes or Plaid calls occurred,
- remaining risks or review items,
- exact next safe step.

Do not restate the entire task or produce a long narrative unless requested.
