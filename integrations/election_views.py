"""Student-facing e-voting proxy (JWT). ERP never exposes the API key to the browser."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.student_portal_finance import get_admitted_student_for_user

from .election_client import EvotingConfigError, EvotingRequestError, evoting_request


def _student_reg_no(request):
    if not getattr(request.user, "is_student", False):
        return None, Response(
            {"detail": "Only student portal accounts can vote here."},
            status=status.HTTP_403_FORBIDDEN,
        )
    student = get_admitted_student_for_user(request.user)
    if not student:
        return None, Response(
            {"detail": "No admitted student profile is linked to this account."},
            status=status.HTTP_404_NOT_FOUND,
        )
    reg_no = (student.reg_no or "").strip()
    if not reg_no:
        return None, Response(
            {"detail": "Your registration number is missing. Contact the Academic Registrar."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return reg_no, None


def _evoting_error(exc):
    if isinstance(exc, EvotingConfigError):
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    payload = exc.payload if isinstance(exc.payload, dict) else {"detail": str(exc)}
    if "detail" not in payload:
        payload["detail"] = str(exc)
    return Response(payload, status=exc.status_code)


class ElectionWindowView(APIView):
    """Logged-in student: has an election been set (scheduled or active)?"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, "is_student", False):
            return Response(
                {"detail": "Only student portal accounts can access elections."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            data = evoting_request("GET", "/api/voting-window")
        except (EvotingConfigError, EvotingRequestError) as exc:
            return _evoting_error(exc)
        return Response(
            {
                "election_set": bool(data.get("election_set")),
                "active": bool(data.get("active")),
                "election": data.get("election"),
            }
        )


class ElectionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        reg_no, error = _student_reg_no(request)
        if error:
            return error
        try:
            data = evoting_request(
                "GET",
                "/api/integrations/portal/voter-status",
                reg_no=reg_no,
            )
        except (EvotingConfigError, EvotingRequestError) as exc:
            return _evoting_error(exc)
        data["reg_no"] = data.get("reg_no") or reg_no
        return Response(data)


class ElectionBallotView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        reg_no, error = _student_reg_no(request)
        if error:
            return error
        try:
            data = evoting_request("GET", "/api/ballot", reg_no=reg_no)
        except (EvotingConfigError, EvotingRequestError) as exc:
            return _evoting_error(exc)
        return Response(data)


class ElectionCastView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        reg_no, error = _student_reg_no(request)
        if error:
            return error
        try:
            data = evoting_request(
                "POST",
                "/api/ballot/cast",
                reg_no=reg_no,
                json={"selections": request.data.get("selections", [])},
            )
        except (EvotingConfigError, EvotingRequestError) as exc:
            return _evoting_error(exc)
        return Response(data, status=status.HTTP_201_CREATED)
