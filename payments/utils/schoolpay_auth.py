import hashlib

from django.conf import settings


def build_schoolpay_hash(school_code: str, reference: str, password: str) -> str:
    raw = f"{school_code}{reference}{password}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

def schoolpay_api_root() -> str:
    if settings.DEBUG:
        return "https://schoolpaytest.servicecops.com/uatpaymentapi/AndroidRS"
    return "https://schoolpay.co.ug/paymentapi/AndroidRS"
