"""Consumer-domain eligibility; never infer scope from institution or account mask."""


def initial_consumer_scope(account_type):
    return getattr(account_type, "value", account_type) in {"credit", "depository"}


def account_type_drift(existing, account_type, subtype):
    if existing.type == account_type and existing.subtype == subtype:
        return None
    return {
        "name": existing.name, "mask": existing.mask,
        "previous_type": existing.type, "previous_subtype": existing.subtype,
        "type": account_type, "subtype": subtype,
        "consumer_transactions_enabled": existing.consumer_transactions_enabled,
    }
