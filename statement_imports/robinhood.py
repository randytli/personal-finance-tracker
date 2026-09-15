import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal

from .models import ImportedTransaction, Preview


class RobinhoodGoldCardCSV:
    name = "robinhood-gold-card"
    version = "1"
    headers = ("Date", "Time", "Cardholder", "Amount", "Points", "Balance",
               "Status", "Type", "Merchant", "Description")
    kinds = {"Purchase": "purchase", "Refund": "refund", "Payment": "payment", "Fee": "fee"}

    def parse(self, data: bytes, *, through: date | None = None) -> Preview:
        result = Preview(self.name, through)
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            result.errors.append({"code": "invalid_encoding", "message": "Expected UTF-8 CSV"})
            return result
        reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
        try:
            headers = next(reader, [])
            if len(set(headers)) != len(headers) or not set(self.headers).issubset(headers):
                result.errors.append({"code": "invalid_headers", "message": "Missing or duplicate export columns"})
                return result
            if set(headers) != set(self.headers):
                result.warnings.append({"code": "extra_columns", "message": "Extra export columns preserved"})
            result.warnings.append({"code": "currency_assumed", "message": "USD assumed: this export has no currency column"})
            digest = hashlib.sha256(data).hexdigest()
            for record, cells in enumerate(reader, start=1):
                result.rows_read += 1
                def reject(code, message):
                    result.skipped["parse_error"] += 1
                    result.errors.append({"record": record, "line_end": reader.line_num,
                                          "code": code, "message": message})
                if len(cells) != len(headers):
                    reject("invalid_columns", "Record column count differs from header")
                    continue
                row = dict(zip(headers, cells))
                status = row["Status"].strip()
                if status != "Posted":
                    result.skipped["declined" if status == "Declined" else "not_posted"] += 1
                    if status != "Declined":
                        result.warnings.append({"record": record, "code": "not_posted",
                                                "message": "Non-Posted record excluded"})
                    continue
                try:
                    raw_date = row["Date"].strip()
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
                        raise ValueError
                    transaction_date = date.fromisoformat(raw_date)
                except ValueError:
                    reject("invalid_date", "Expected a valid YYYY-MM-DD date")
                    continue
                if through is not None and transaction_date > through:
                    result.skipped["after_through_date"] += 1
                    continue
                kind = self.kinds.get(row["Type"].strip())
                if kind is None:
                    reject("unsupported_kind", "Unsupported Posted transaction type")
                    continue
                value = row["Amount"].strip()
                if not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", value):
                    reject("invalid_amount", "Expected a finite decimal amount with at most two decimal places")
                    continue
                source_amount = Decimal(value)
                if ((kind in ("purchase", "fee") and source_amount < 0)
                        or (kind in ("refund", "payment") and source_amount > 0)):
                    reject("unexpected_sign", "Source amount sign conflicts with transaction type")
                    continue
                if source_amount == 0:
                    result.warnings.append({"record": record, "code": "zero_amount",
                                            "message": "Zero amount retained for review"})
                result.transactions.append(ImportedTransaction(
                    transaction_date=transaction_date, amount=-source_amount,
                    currency="USD", kind=kind, merchant=row["Merchant"].strip() or None,
                    description=row["Description"].strip() or None, adapter=self.name,
                    adapter_version=self.version, source_file_sha256=digest,
                    source_record=record, source_line_end=reader.line_num,
                    source_amount=source_amount, source_fields=tuple(zip(headers, cells)),
                ))
        except csv.Error:
            result.rows_read += 1
            result.skipped["parse_error"] += 1
            result.errors.append({"code": "malformed_csv", "line_end": reader.line_num,
                                  "message": "Malformed CSV; stopped parsing, preview is incomplete"})
        return result
