# utils.py (or payments/utils.py)
import hashlib
import requests
from datetime import date
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.conf import settings

class SchoolPayClient:
    def __init__(self):
        self.school_code = settings.SCHOOL_PAY_CODE  
        self.password = settings.SCHOOL_PAY_PASSWORD

        # self.base_url = "https://schoolpaytest.servicecops.com/uatpaymentapi/AndroidRS/AdhocPayments"

        if settings.DEBUG:
          self.base_url = "https://schoolpaytest.servicecops.com/uatpaymentapi/AndroidRS/AdhocPayments"
          self.sync_base_url = "https://schoolpaytest.servicecops.com/uatpaymentapi/AndroidRS"
        else:
           self.base_url = "https://schoolpay.co.ug/paymentapi/AndroidRS/AdhocPayments"
           self.sync_base_url = "https://schoolpay.co.ug/paymentapi/AndroidRS"
        
        # Session with retries (3 attempts, backoff)
        self.session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('https://', adapter)

    def generate_hash(self, reference):
        raw_string = f"{self.school_code}{reference}{self.password}"
        return hashlib.md5(raw_string.encode()).hexdigest().upper()  

    def _date_string(self, value):
        if isinstance(value, date):
            return value.isoformat()
        return str(value).strip()

    def request_payment(self, amount, phone, ext_ref, first_name, last_name, reason, callBackUrl):
        hash_val = self.generate_hash(ext_ref)
        url = f"{self.base_url}/Request/{self.school_code}/{hash_val}"
        
        payload = {
            "amount": float(amount),
            "externalReference": ext_ref,
            "phoneNumber": phone,  
            "firstName": first_name,
            "lastName": last_name,
            "reason": reason,
            "callBackUrl":callBackUrl
        }
        
        try:
            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ValueError(f"Payment request failed: {str(e)}")

    def register_payment_reference(self, amount, ext_ref, first_name, last_name, reason, callBackUrl):
        """
        Register a one-time payment reference (PRN-like SchoolPay paymentReference).
        Endpoint: /AdhocPayments/Register/{schoolCode}/{hash}
        """
        hash_val = self.generate_hash(ext_ref)
        url = f"{self.base_url}/Register/{self.school_code}/{hash_val}"
        payload = {
            "amount": float(amount),
            "externalReference": ext_ref,
            "firstName": first_name,
            "lastName": last_name,
            "reason": reason,
            "callBackUrl": callBackUrl,
        }
        try:
            response = self.session.post(url, json=payload, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ValueError(f"Payment reference registration failed: {str(e)}")

    def check_status(self, payment_ref):
        hash_val = self.generate_hash(payment_ref) 
        url = f"{self.base_url}/Check/{self.school_code}/{hash_val}/{payment_ref}"
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ValueError(f"Status check failed: {str(e)}")

    def sync_transactions_by_date(self, transaction_date):
        date_str = self._date_string(transaction_date)
        hash_val = self.generate_hash(date_str)
        url = f"{self.sync_base_url}/SyncSchoolTransactions/{self.school_code}/{date_str}/{hash_val}"
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ValueError(f"Sync transactions by date failed: {str(e)}")

    def sync_transactions_by_range(self, from_date, to_date):
        from_str = self._date_string(from_date)
        to_str = self._date_string(to_date)
        hash_val = self.generate_hash(from_str)
        url = f"{self.sync_base_url}/SchoolRangeTransactions/{self.school_code}/{from_str}/{to_str}/{hash_val}"
        try:
            response = self.session.get(url, timeout=25)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ValueError(f"Sync transactions by range failed: {str(e)}")