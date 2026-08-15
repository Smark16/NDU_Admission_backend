"""Mark an ad-hoc charge as paid from existing SchoolPay / tuition credit."""

CREDIT_ALLOCATION_TX_PREFIX = "CREDIT-"


def is_credit_reallocation_payment(payment) -> bool:
    return (getattr(payment, "transaction_id", None) or "").strip().startswith(
        CREDIT_ALLOCATION_TX_PREFIX
    )
