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
