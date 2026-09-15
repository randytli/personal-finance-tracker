from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol
from collections import Counter

TransactionKind = Literal["purchase", "refund", "payment", "fee"]


@dataclass(frozen=True)
class ImportedTransaction:
    transaction_date: date
    amount: Decimal
    currency: str
    kind: TransactionKind
    merchant: str | None
    description: str | None
    adapter: str
    adapter_version: str
    source_file_sha256: str
    source_record: int
    source_line_end: int
    source_amount: Decimal
    # Keep original header/value pairs in memory for future provenance, not CLI output.
    source_fields: tuple[tuple[str, str], ...]


@dataclass
class Preview:
    adapter: str
    through: date | None
    rows_read: int = 0
    transactions: list[ImportedTransaction] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def report(self):
        totals = {kind: Decimal("0") for kind in ("purchase", "refund", "payment", "fee")}
        counts = Counter()
        for row in self.transactions:
            counts[row.kind] += 1
            totals[row.kind] += row.amount
        dates = [row.transaction_date for row in self.transactions]
        return {
            "adapter": self.adapter, "dry_run": True,
            "import_through": self.through.isoformat() if self.through else None,
            "rows_read": self.rows_read, "eligible_rows": len(self.transactions),
            "skipped_rows": sum(self.skipped.values()), "skipped_by_reason": dict(self.skipped),
            "date_range": {"earliest": min(dates).isoformat() if dates else None,
                           "latest": max(dates).isoformat() if dates else None},
            "transaction_kind_counts": {kind: counts[kind] for kind in totals},
            "normalized_amount_totals": {kind: format(value, ".2f") for kind, value in totals.items()},
            "normalized_amount_total": format(sum(totals.values(), Decimal("0")), ".2f"),
            "currency": "USD", "errors": self.errors, "warnings": self.warnings,
        }


class StatementImportAdapter(Protocol):
    supported_accounts: frozenset[tuple[str, str | None]]
    name: str
    version: str

    def parse(self, data: bytes, *, through: date | None = None) -> Preview: ...
