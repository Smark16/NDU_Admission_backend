"""Student-facing Zimbra webmail launch (SSO via domain preauth)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.student_portal_finance import get_admitted_student_for_user

from .models import ZimbraIntegrationConfig
from .zimbra_preauth import build_zimbra_preauth_url


class StudentZimbraLaunchView(APIView):
    """Logged-in student asks STEWARD for a one-time Zimbra webmail SSO URL."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        return self._launch(request)

    def get(self, request):
        return self._launch(request)

    def _launch(self, request):
        cfg = ZimbraIntegrationConfig.get_solo()

        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "No admitted student profile is linked to this account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        university_email = (student.university_email or "").strip()
        if not university_email:
            return Response(
                {
                    "detail": (
                        "Your university email hasn't been set up yet. "
                        "Contact ICT support if this persists."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            launch_url = build_zimbra_preauth_url(
                base_url=cfg.webmail_base_url,
                account_email=university_email,
                preauth_key=cfg.preauth_key,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(
            {
                "ok": True,
                "launch_url": launch_url,
                "university_email": university_email,
            }
        )
