"""Transaction labels are descriptive metadata, never financial semantics."""
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import select


ALLOWED_LABELS = ("CHINA", "MEMBERSHIP")
LABEL_CHECK = "label IN (" + ",".join("'" + label + "'" for label in ALLOWED_LABELS) + ")"

# Reviewed membership-specific descriptions only. These are normalized in the
# same way as transaction.description; merchant names and cadence are not used.
# Some source descriptions are truncated or include processor text, so retain
# only the exact observed forms instead of prefix matching.
MEMBERSHIP_EXACT_DESCRIPTIONS = frozenset({
    "MEMBERSHIP FEE",
    "RENEWAL MEMBERSHIP FEE",
    "CAPITAL ONE MEMBER FEE",
    "GOLD ANNUAL SUBSCRIPTIO",
    "OPENAI CHATGPT SUBSCR",
    "OPENAI CHATGPT SUBSCR OPENAI COM CA",
    "CLAUDE AI SUBSCRIPTION",
    "CLAUDE AI SUBSCRIPTION ANTHROPIC COMCA",
    "YOUTUBE PREMIUM",
    "YOUTUBEPREMI G CO HELPPAY",
    "YOUTUBEPREMIUCC GOOGLE COM",
    "AMAZON PRIME",
    "PEACOCK",
    "AMAZON GROCERY SUBSCRI",
    "IC INSTACART SUBSCRIP",
    "WMT PLUS NOV 2025 028009666546",
    "WMT PLUS FEB 2026 028009666546",
    "ANTHROPIC CLAUDE SUB ANTHROPIC COMCA",
    "D J WSJ ONLINE",
})

# User-reviewed generic descriptions need both exact merchant/description and
# exact signed expense amount. Never infer membership from merchant or cadence.
MEMBERSHIP_EXACT_EXPENSE_AMOUNTS = {
    ("WALMART", "WALMART"): Decimal("-13.81"),
    ("UBER", "UBER"): Decimal("-9.99"),
}

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


def _membership_expense_amount_match(transaction, merchant, description):
    expected = MEMBERSHIP_EXACT_EXPENSE_AMOUNTS.get((
        normalize_label_text(merchant), normalize_label_text(description)
    ))
    if (expected is None or _value(transaction, "transaction_type") != "expense"
            or _value(transaction, "is_spending") is not True
            or _value(transaction, "is_internal_transfer") is True):
        return False
    try:
        return Decimal(str(_value(transaction, "amount"))) == expected
    except (InvalidOperation, TypeError):
        return False


def automatic_labels(transaction):
    merchant = _value(transaction, "merchant_name")
    description = _value(transaction, "description")
    values = set()
    if _china_match(merchant) or _china_match(description):
        values.add("CHINA")
    if (normalize_label_text(description) in MEMBERSHIP_EXACT_DESCRIPTIONS
            or _membership_expense_amount_match(transaction, merchant, description)):
        values.add("MEMBERSHIP")
    return frozenset(values)


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
