"""Student-facing Moodle LMS launch (JWT)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.student_portal_finance import get_admitted_student_for_user

from .models import MoodleIntegrationConfig
from .moodle_sso import build_moodle_sso_launch_url, moodle_launch_signing_secret
from .services import log_moodle_access, moodle_launch_profile_for_student


class StudentMoodleLaunchView(APIView):
    """
    Logged-in student asks STEWARD for a one-time Moodle SSO URL.

    Moodle verifies reg_no|exp HMAC (sig) with the shared secret.
    Launch URL also carries signed profile fields (username, firstname,
    lastname, email, psig) so Moodle can show names on first portal SSO.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        return self._launch(request)

    def get(self, request):
        return self._launch(request)

    def _launch(self, request):
        endpoint = "moodle/launch"
        cfg = MoodleIntegrationConfig.get_solo()
        if not cfg.is_enabled:
            log_moodle_access(endpoint=endpoint, http_status=503, detail="disabled")
            return Response(
                {"detail": "Moodle integration is disabled. Contact ICT."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        student = get_admitted_student_for_user(request.user)
        if not student:
            log_moodle_access(endpoint=endpoint, http_status=404, detail="no student")
            return Response(
                {"detail": "No admitted student profile is linked to this account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        reg_no = (student.reg_no or "").strip()
        if not reg_no:
            log_moodle_access(endpoint=endpoint, http_status=400, detail="no reg_no")
            return Response(
                {"detail": "Your registration number is missing. Contact the Academic Registrar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        secret = moodle_launch_signing_secret(cfg)
        profile = moodle_launch_profile_for_student(student, request.user)
        try:
            payload = build_moodle_sso_launch_url(
                base_url=cfg.moodle_base_url or "",
                reg_no=reg_no,
                secret=secret,
                profile=profile,
            )
        except ValueError as exc:
            log_moodle_access(endpoint=endpoint, http_status=400, detail=str(exc)[:200])
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            detail=reg_no,
        )
        return Response(
            {
                "ok": True,
                "launch_url": payload["launch_url"],
                "reg_no": payload["reg_no"],
                "exp": payload["exp"],
                "ttl_seconds": payload["ttl_seconds"],
            }
        )
