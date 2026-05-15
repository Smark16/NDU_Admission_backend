"""Email body for programme-of-choice verification outreach."""
from __future__ import annotations

from django.conf import settings

from admissions.utils.application_programs_display import ordered_programs_for_application


def build_program_choice_verification_email(application) -> tuple[str, str]:
  """
  Return (subject, plain_text_body) for an applicant to confirm programme choices.
  """
  programs = ordered_programs_for_application(application)
  if programs:
    lines = [f"  {i}. {p.name}" for i, p in enumerate(programs, start=1)]
    programme_block = "Your application currently lists these programme(s) of choice:\n\n" + "\n".join(
      lines
    )
  else:
    programme_block = (
      "We could not display programme choices on your application record. "
      "Please sign in to the portal and review or re-select your programme(s) of choice."
    )

  portal_url = getattr(settings, "ERP_FRONTEND_URL", "").rstrip("/") or "[admissions portal URL]"

  subject = "Action required: Please confirm your programme(s) of choice — Ndejje University"

  body = f"""Dear {application.first_name} {application.last_name},

We are writing regarding your application for admission to Ndejje University (Application reference: {application.id}).

As part of a routine data review, we are asking applicants to confirm that the programme(s) of choice recorded on their application are correct.

{programme_block}

Please sign in to the admissions portal at {portal_url} and:

  1. Review the programme(s) of choice shown on your application.
  2. Confirm that they match what you intended to apply for.
  3. If anything is incorrect, contact the Admissions Office promptly so we can assist you.

If your choices are already correct, no change is required — a brief reply to this email confirming that the listed programme(s) are correct would be appreciated.

We apologise for any inconvenience and thank you for your cooperation.

Admissions Office
Ndejje University
"""

  return subject, body.strip()
