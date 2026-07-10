"""Commitment / tuition payment reminder emails for admitted students."""
from __future__ import annotations

from admissions.models import AdmittedStudent
from ndu_portal.send_grid import send_configurable_email
from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD

DEFAULT_SUBJECT = (
    "RE: REMINDER TO PAY YOUR ADMISSION COMMITMENT FEE BY 17 JULY 2026"
)


def send_commitment_fee_reminder(
    student: AdmittedStudent,
    *,
    paid_ugx: float | None = None,
    balance_ugx: float | None = None,
    subject: str = DEFAULT_SUBJECT,
) -> bool:
    """Send a payment reminder for an admitted student who has not met the commitment fee."""
    application = student.application
    email = (getattr(application, "email", None) or "").strip()
    if not email:
        return False

    first_name = (application.first_name or "").strip()
    last_name = (application.last_name or "").strip()
    full_name = f"{first_name} {last_name}".strip() or "Applicant"
    pay_code = (student.effective_schoolpay_code or student.student_id or "").strip()
    threshold = f"UGX {int(COMMITMENT_FEE_THRESHOLD):,}"

    # Partial payment note — only when some money has been paid but commitment not met
    balance_note = ""
    paid_amount = float(paid_ugx or 0)
    remaining = float(balance_ugx) if balance_ugx is not None else None
    if paid_amount > 0 and remaining is not None and remaining > 0:
        balance_note = (
            f"\nOur records show that you have so far paid UGX {int(paid_amount):,} "
            f"toward the commitment fee. Kindly pay the remaining balance of "
            f"UGX {int(remaining):,} on or before Friday, 17 July 2026 to complete "
            f"the {threshold} requirement.\n"
        )
    elif paid_amount > 0 and remaining is None:
        remaining_calc = max(float(COMMITMENT_FEE_THRESHOLD) - paid_amount, 0)
        if remaining_calc > 0:
            balance_note = (
                f"\nOur records show that you have so far paid UGX {int(paid_amount):,} "
                f"toward the commitment fee. Kindly pay the remaining balance of "
                f"UGX {int(remaining_calc):,} on or before Friday, 17 July 2026 to complete "
                f"the {threshold} requirement.\n"
            )

    pay_code_line = (
        f"Your SchoolPay Payment Code is: {pay_code}\n"
        if pay_code
        else ""
    )

    body = f"""Dear {full_name},

RE: REMINDER TO PAY YOUR ADMISSION COMMITMENT FEE BY 17 JULY 2026

Greetings from Ndejje University.

Congratulations once again on your provisional admission to Ndejje University for the 2026/2027 Academic Year.

This is a reminder to confirm your admission by paying the non-refundable commitment fee of {threshold} on or before Friday, 17 July 2026, using the SchoolPay Payment Code provided on your admission letter.
{pay_code_line}{balance_note}
You can conveniently make your payment using Mobile Money as follows:

MTN Mobile Money
• Dial *160*80#
• Enter your SchoolPay Payment Code
• Confirm the payment details and complete the transaction.

Airtel Money
• Dial *185*6*2#
• Enter your SchoolPay Payment Code
• Confirm the payment details and complete the transaction.

After making the payment, please email the following to confirmation@ndu.ac.ug:
• Your payment confirmation receipt

If you have already paid the commitment fee, please disregard this reminder.

We look forward to welcoming you to Ndejje University and wish you every success in your academic journey.

Yours sincerely,
Admissions Office
Ndejje University
"""

    return send_configurable_email(email, subject, body)
