"""Transaction labels are descriptive metadata, never financial semantics."""
import re

from sqlalchemy import select


ALLOWED_LABELS = ("CHINA",)
LABEL_CHECK = "label IN (" + ",".join("'" + label + "'" for label in ALLOWED_LABELS) + ")"

CHINA_EXACT_NAMES = frozenset({
    "ALIPAY", "WEIXIN", "AMAP TAXI", "MEITUAN", "NANJING METRO", "TAOBAO",
    "MIXUE ICE CITY", "HONEY SNOW ICE", "JIMING SOUP DUM",
})


def normalize_label_text(value):
    return " ".join(re.findall(r"[A-Z0-9]+", value or "", flags=re.IGNORECASE)).upper()


def _value(transaction, name):
    return transaction.get(name) if isinstance(transaction, dict) else getattr(transaction, name, None)


def _china_match(value):
    normalized = normalize_label_text(value)
    return (
        normalized in CHINA_EXACT_NAMES
        or normalized.startswith("ALIPAY ")
        or normalized.startswith("WEIXIN ")
        or normalized.startswith("REFUND ALIPAY ")
        or normalized.startswith("REFUND WEIXIN ")
    )


def automatic_labels(transaction):
    merchant = _value(transaction, "merchant_name")
    description = _value(transaction, "description")
    return frozenset({"CHINA"}) if _china_match(merchant) or _china_match(description) else frozenset()


def active_label_decisions(overrides):
    return {
        override.label: override.decision
        for override in overrides
        if override.decision is not None and override.cleared_at is None
    }


def effective_labels(transaction, decisions=None):
    values = set(automatic_labels(transaction))
    for label, decision in (decisions or {}).items():
        if decision == "include":
            values.add(label)
        elif decision == "exclude":
            values.discard(label)
    return tuple(sorted(values))


def label_result(transaction, overrides=()):
    decisions = active_label_decisions(overrides)
    return {
        "automatic_labels": sorted(automatic_labels(transaction)),
        "manual_label_decisions": decisions,
        "effective_labels": list(effective_labels(transaction, decisions)),
    }


async def load_label_overrides(db, transaction_ids):
    from api.models import ManualTransactionLabelOverride
    if not transaction_ids:
        return {}
    rows = (await db.execute(select(ManualTransactionLabelOverride).where(
        ManualTransactionLabelOverride.transaction_id.in_(transaction_ids)))).scalars().all()
    result = {transaction_id: [] for transaction_id in transaction_ids}
    for row in rows:
        result.setdefault(row.transaction_id, []).append(row)
    return result
