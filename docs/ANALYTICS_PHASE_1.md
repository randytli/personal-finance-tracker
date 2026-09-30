# Analytics Phase 1

Analytics includes non-removed transactions from active Items and always applies an
active manual classification override before the automatic classification.

For a calendar month:

- `gross_spending` is the absolute total of included negative expenses.
- `refunds`, `reimbursements`, and `card_benefits` reduce spending.
- `reimbursements` totals positive repayments toward expenses paid by the user,
  in the month the credit posts. It does not move the original expense.
- `net_spending = gross_spending - refunds - reimbursements - card_benefits`.
- `income` is the total of included positive income transactions.
- `net_savings = income - net_spending`.

Payments, transfers, confirmed internal transfers, adjustments, and unclassified
transactions do not contribute to monetary metrics. "Cash flow" is intentionally
reserved for a future analysis of actual depository-account movements.

Category net spending subtracts category refunds and reimbursements from category gross spending.
`spending_transaction_count` counts only those included expenses and refunds.
`reimbursement_transaction_count` separately counts included reimbursements.
Reimbursements use an active manual category or `UNCATEGORIZED`, without automatic
merchant or Plaid category inference.
Card benefits remain unallocated because their transaction categories are not a
reliable indication of the spending they offset.

## Phase 2 M3 canonical category net

The additive `category_net_breakdown` in `/analytics/monthly` uses version 1
canonical attribution. For each category, `net_spending = gross_spending -
refunds - reimbursements - card_benefits`. Each component sums exactly to the
corresponding monthly component, including credit-only and negative-net
categories. The existing `category_breakdown` and `/analytics/category` retain
their Phase 1 meaning, which excludes card benefits from category net.

Expenses and refunds use their own effective spending category (active manual,
exact merchant rule, supported Plaid category, then Uncategorized). Refunds
remain in their own posted month. Reimbursements use only an active manual
spending category or Uncategorized, in the receipt month. No credit is linked
to an expense or allocated to another account. Eligible unknown spending codes
report as Uncategorized without rewriting the source code.

Card benefits use the effective benefit category: active manual benefit choice
before the automatic choice based on effective classification and account
context. Ordinary spending-category overrides do not attribute a benefit.
Dining maps to Dining; Travel to Travel; Shopping to General Merchandise;
Transportation to Transportation; Digital Entertainment and Entertainment to
Entertainment; General Services to General Services; and unknown or
Uncategorized benefits to Uncategorized. The distinct benefit breakdown remains.

`/analytics/category-net` returns one canonical category summary.
`/analytics/transactions` accepts `canonical_category` and
`spending_component=gross|refunds|reimbursements|card_benefits|net`. The net
component is the union of contributing rows and exposes signed
`net_contribution`; filtering precedes pagination. `component_totals` and
`contributing_transaction_count` cover the complete filtered set. Legacy
`category` and `transaction_type` filters remain available but cannot be
combined with their corresponding canonical filters.

Dining uses manual/canonical spending code `DINING`, separately from `GROCERIES`.
Plaid source `FOOD_AND_DRINK` remains preserved in original/source fields and
derives to `DINING`. Manual writes and spending-category filters require `DINING`;
the obsolete manual code is rejected. An explicit reviewed one-time migration
converts active manual overrides without changing their audit metadata. Runtime
startup does not migrate these decisions. See
[PFT_PHASE_2_M3_DINING_MIGRATION_PLAN.md](PFT_PHASE_2_M3_DINING_MIGRATION_PLAN.md).
