# Design direction: Statement and ink

Subject: a self-hosted ledger of one household's money. The owner opens it monthly on a phone or a desk to answer three questions: where this month's money went, what still needs a decision, and what memberships really cost.

Pass 1 (`e70cdb4`) tidied the admin dashboard into the generic SaaS card kit: identical white rounded cards, a bright blue accent, and Inter. Pass 2 borrows from the printed statement instead.

## Tokens

| Role | Value | Use |
| --- | --- | --- |
| Paper | `#F1F3EE` | Page canvas, a cool sage-grey like cheque security paper (deliberately not cream) |
| Sheet | `#FFFFFF` | Statement, ledgers and anything that holds rows |
| Ink | `#17223A` | Text, primary buttons, selection marks |
| Graphite | `#5A6371` | Secondary text |
| Rule | `#D6DCD1` | Hairlines between ledger rows |
| Ledger green | `#1B6A4D` | Credits and income only |
| Oxblood | `#A13A2A` | Net spending in charts and destructive actions |

Type: **Source Serif 4** (optical sizes) for page titles, section titles and statement figures. **Public Sans** for interface text and dense rows. Amounts always use tabular lining figures.

## Principles

1. **The statement is the one bold element.** Net spending and net membership cost appear as the reconciliation they are: lines with a minus sign, a single rule, and the total under an accounting double rule. The formula is no longer a footnote.
2. **Sheets hold rows; paper holds context.** Ledgers and the statement sit on white sheets. Charts and summaries sit on the paper under a rule, so the page is not a stack of identical cards.
3. **Ledger rows scan by column.** On wider screens the date has its own column and the amount aligns right. Account identity is a small colour swatch rather than a saturated pill.
4. **Quiet chrome.** Navigation uses an ink underline, labels use sentence case, and nothing animates unless the user acts.
