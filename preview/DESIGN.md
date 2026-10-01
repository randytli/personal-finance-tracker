# Design direction: Night ledger (pass 3)

Subject: a self-hosted ledger of one household's money. The owner opens it on a phone or a desk to see where this month's money went, what still needs a decision, and what memberships really cost.

History: pass 1 (`e70cdb4`) tidied the admin dashboard into generic cards. Pass 2 (`4e2cf13`) tried a printed-statement look (serif totals, double rules, sage paper) and was rejected. Pass 3 follows the design language of modern dark personal-finance apps (reference: Copilot Money) without borrowing its brand, mark, copy, palette values or exact layout.

## Tokens

| Role | Value | Use |
| --- | --- | --- |
| Night | `#060A14` | Page background |
| Deep | `#0C1324` | Cards: one step lighter, 1px `#1B2742` border, 18px radius, no shadow |
| Mist | `#E6EBF5` | Primary text |
| Slate | `#8A98B8` | Secondary text |
| Signal blue | `#3563DA` fill / `#6E95F7` text | Active nav, primary pill buttons, group labels and links |
| Good / on / bad | `#3DD68C` / `#F4B740` / `#F26464` | Tracking line, callouts, credits, warnings, errors |

Type: **Plus Jakarta Sans**, self-hosted through `next/font`, for everything. Amounts use the `.money` class, which applies tabular figures and never wraps. Manrope was tried first, but its narrow word spaces made 12px captions run together.

Category colour: each category has one hue in `components/category-display.tsx`. Pills use that hue for uppercase text over a 14% tint, list rows use an icon tile, and the donut and share bars use it as a solid colour. Line icons are used instead of emoji so the text of category cells stays exactly the label.

Every pair checked passes WCAG AA on the card surface; the lowest is 5.3:1 for white on the accent blue.

## Principles

1. **One hero per page.** Overview leads with net spending and its tracking line; Memberships leads with net cost. Everything else is a compact secondary card or list.
2. **Colour never works alone.** The tracking line pairs green or red with a signed callout ("↑ $550 over avg") and a caption, net savings carries a "Saved" or "Overspent" badge with an arrow, and debits keep their minus sign.
3. **Rows scan as name, pill, amount.** Lists are grouped under date labels, with no gridlines and a rounded hover. Secondary tags sit behind a "+N" chip; editors the user acts on stay visible on desktop.
4. **Quiet chrome.** Card titles sit on the left with a quiet action on the right. Sync warnings stay to one truncated line each. Nothing animates on its own.

## Constraints that shaped the layout

- The Memberships chart stays a five-series line chart because its test pins those series. Rounded bars appear in the category list and the Memberships composition bar instead.
- On desktop, row editors (classification, benefit category, labels) stay visible because the M4 harness drives them without expanding the row. On phones they sit behind each row's "Details & editing" chip.
- The sidebar shows no account balances, and Memberships has no "upcoming charges" list, because no existing endpoint provides that data. Membership transactions use the date-first list style instead.
