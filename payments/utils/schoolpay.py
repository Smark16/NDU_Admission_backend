# utils.py (or payments/utils.py)
import hashlib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings

class SchoolPayClient:
    def __init__(self):
        self.school_code = settings.SCHOOL_PAY_CODE  # Assuming you have SCHOOL_PAY_CODE in settings
        self.password = settings.SCHOOL_PAY_PASSWORD
        self.base_url = "https://schoolpay.co.ug/AndroidRS/AdhocPayments"
        
        # Session with retries (3 attempts, backoff)
        self.session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('https://', adapter)

    def generate_hash(self, reference):
        raw_string = f"{self.school_code}{reference}{self.password}"
        return hashlib.md5(raw_string.encode()).hexdigest().upper()  # Uppercase as per docs (assuming)

    def request_payment(self, amount, phone, ext_ref, first_name, last_name, reason):
        hash_val = self.generate_hash(ext_ref)
        url = f"{self.base_url}/Request/{self.school_code}/{hash_val}"
        
        payload = {
            "amount": float(amount),
            "externalReference": ext_ref,
            "phoneNumber": phone,  # 077... or 25677...
            "firstName": first_name,
            "lastName": last_name,
            "reason": reason
        }
        
        try:
            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            # Log error (use logging module)
            raise ValueError(f"Payment request failed: {str(e)}")

    def check_status(self, payment_ref):
        hash_val = self.generate_hash(payment_ref)  # Identifying ref = payment_ref for Check
        url = f"{self.base_url}/Check/{self.school_code}/{hash_val}/{payment_ref}"
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ValueError(f"Status check failed: {str(e)}")