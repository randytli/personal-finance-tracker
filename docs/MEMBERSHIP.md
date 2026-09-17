# Membership label and cost view

`MEMBERSHIP` is an effective transaction label, independent of category and
classification. It can coexist with `CHINA` and any supported category. The
existing label editor and atomic bulk editor can include, exclude, or restore
the automatic decision for each label independently.

The Membership page defaults to the selected ending month and previous 11
calendar months. YTD instead reports January through the selected ending
month's end. The selected period applies to the overall metrics, monthly trend,
account breakdown, labeled/excluded counts, and paginated transaction details.
The current ending month is marked partial. The existing Membership API defaults
to trailing 12 months when no period is supplied. The page uses each
transaction's actual account ID for account breakdowns.
Only effective MEMBERSHIP transactions contribute:

- Gross charges: included negative expenses, expressed as positive dollars.
- Refunds: positive effective refunds on their own accounts.
- Card benefits: positive effective card benefits on their own accounts.
- Net cost: gross charges minus refunds minus card benefits.

Labeled payments, transfers, internal transfers, income, adjustments, and
unclassified entries remain visible in transaction details but contribute zero.
The labeled transaction count includes these rows; a separate excluded count
shows how many did not affect cost. Counts are not subscription counts.

Automatic MEMBERSHIP rules use only reviewed exact normalized transaction
descriptions in api/labels.py: explicit card membership fees, Gold annual
subscription, individually approved subscriptions, and the reviewed Instacart,
WMT PLUS, Anthropic, and WSJ descriptions. A separately approved rule matches
only exact generic WALMART/WALMART expenses of -$13.81 or UBER/UBER expenses
of -$9.99, using normalized merchant and description plus signed amount.
No rule uses a broad merchant name, substring, recurrence, or cadence.
Observed truncations and
processor-expanded descriptions are separate exact values. Historical matching
transactions gain the label dynamically; no historical override rows are
written. Manual include/exclude/restore-auto decisions retain precedence.
Category, classification, and monthly spending formulas are unchanged.

## Production acceptance boundary

1. Record Item/account/financial-row, override-audit, token/cursor, and active
   analytics fingerprints on the validated Production database.
2. Run the existing idempotent schema initialization twice to expand the label
   CHECK constraint; verify existing CHINA decisions and all fingerprints.
3. Run the read-only Membership candidate audit and review exact descriptions.
4. Enable only the separately approved exact descriptions. Do not create manual
   decisions or bulk-label historical transactions as part of the rule change.

Implementation verification uses synthetic data only. No Plaid call is needed.
