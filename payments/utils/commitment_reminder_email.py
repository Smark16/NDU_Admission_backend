"""Commitment / tuition payment reminder emails for admitted students."""
from __future__ import annotations

from admissions.models import AdmittedStudent
from ndu_portal.send_grid import send_configurable_email
from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD


def send_commitment_fee_reminder(
    student: AdmittedStudent,
    *,
    paid_ugx: float | None = None,
    balance_ugx: float | None = None,
    subject: str = "Reminder: Pay Your Commitment Fee — Ndejje University",
) -> bool:
    """Send a payment reminder for an admitted student who has not met the commitment fee."""
    application = student.application
    email = (getattr(application, "email", None) or "").strip()
    if not email:
        return False

    first_name = application.first_name or ""
    last_name = application.last_name or ""
    program_name = student.admitted_program.name if student.admitted_program_id else "your admitted programme"
    pay_code = (student.effective_schoolpay_code or student.student_id or "").strip()
    reg_no = (student.reg_no or "").strip()
    threshold = f"UGX {int(COMMITMENT_FEE_THRESHOLD):,}"

    paid_line = ""
    if paid_ugx is not None:
        paid_line = f"Amount paid so far: UGX {int(paid_ugx):,}\n"
    if balance_ugx is not None and balance_ugx > 0:
        paid_line += f"Remaining toward commitment: UGX {int(balance_ugx):,}\n"

    body = f"""Dear {first_name} {last_name},

This is a friendly reminder from Ndejje University regarding your admission commitment fee.

You were admitted to: {program_name}
Registration Number: {reg_no or "N/A"}
School Pay Code: {pay_code or "N/A"}

To confirm your admission and unlock academic enrollment, please pay the non-refundable commitment fee of {threshold} using your School Pay Code{f" ({pay_code})" if pay_code else ""}.

{paid_line}This amount is credited toward your tuition fees.

PAYMENT GUIDELINES

=> FOR MTN MOBILE MONEY
   1. Dial *165#
   2. Go to payments (4)
   3. Select school fees (3)
   4. Select school pay (2)
   5. Select pay fees (1)
   Enter student No
   Verify your student details
   Enter amount to pay
   Confirm with MTN mobile money PIN

=> FOR AIRTEL MONEY
   1. Dial *185#
   2. Go to school fees (6)
   3. Select school pay (2)
   4. Select pay fees (1)
   Enter student No
   Enter amount to pay
   Verify your student details
   Confirm with Airtel mobile money PIN

After payment, send your Bank Deposit Slip / payment confirmation receipt to:
confirmation@ndu.ac.ug

You may also log in to the Horizon student portal to track your tuition balance.

If you have already paid, please disregard this message and share your receipt with the Finance / Admissions office if it has not yet reflected.

Admissions & Finance Office
Ndejje University
"""

    return send_configurable_email(email, subject, body)
