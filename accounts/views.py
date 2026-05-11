from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from django.utils import timezone
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.conf import settings
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.permissions import *
from django.contrib.auth.models import Group
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import authenticate
from .serializers import *
from .models import *

from audit.utils import log_audit_event
from django.db import transaction
from django.db.models.deletion import ProtectedError

from django.utils.http import urlsafe_base64_decode
from django.shortcuts import redirect
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from .tasks import celery_send_password_reset_Link

# login view
class ObtainTokenView(TokenObtainPairView):
    serializer_class = ObtainSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            username = request.data.get("username") or request.data.get("email")
            password = request.data.get("password")
            user = authenticate(username=username, password=password)
            if user:
                log_audit_event(
                    user,
                    'login',
                    user,
                    f"User {user.username} logged in via React frontend",
                    request
                )

        return response

# register
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny] 

    def perform_create(self, serializer):
        user = serializer.save()

        # Audit logging
        actor = self.request.user if self.request.user.is_authenticated else user
        log_audit_event(
            actor,
            'register',
            user,
            f"User {user.username} registered via React frontend",
            self.request
        )

# edit user
class UpdateUser(generics.UpdateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        # Never accept raw password writes through ModelSerializer; hash it properly.
        data = request.data.copy()
        new_password = (data.get("password") or "").strip()
        data.pop("password", None)
        data.pop("confirm_password", None)

        serializer = self.serializer_class(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if new_password:
            instance.set_password(new_password)
            instance.must_change_password = True
            instance.save(update_fields=["password", "must_change_password"])

        # ── Lecturer role sync ────────────────────────────────────────────────
        # If the saved role is "Lecturer", ensure is_lecturer=True and Lecturer
        # group membership — matching what AssignLecturerRole does.
        # We only auto-GRANT here; removal remains a deliberate separate action
        # (via the assign_lecturer endpoint) so we never accidentally lock out a
        # lecturer who already has course unit responsibilities.
        new_role = (data.get("role") or "").strip()
        if new_role == "Lecturer" and not instance.is_lecturer:
            instance.is_lecturer = True
            instance.save(update_fields=["is_lecturer"])
            lecturer_group, _ = Group.objects.get_or_create(name="Lecturer")
            instance.groups.add(lecturer_group)
        # ─────────────────────────────────────────────────────────────────────

        return Response(serializer.data, status=200)
    
# get single user
class getUser(generics.RetrieveAPIView):
    queryset = User.objects.prefetch_related('groups', 'user_permissions', 'campuses')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
# list admin users
class ListUsers(generics.ListAPIView):
    queryset = User.objects.filter(is_applicant=False).prefetch_related('groups', 'user_permissions', 'campuses')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]


class ListStaff(generics.ListAPIView):
    """Staff users for assigning as course-unit lecturers."""
    queryset = User.objects.filter(is_staff=True, is_active=True).order_by('first_name', 'last_name')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]


# user status
class ChangeUserStatus(APIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def patch(self, request, *args, **kwargs):
        user_id = self.kwargs['pk']
        newStatus = request.data.get('is_active')

        try:
            user = User.objects.prefetch_related('groups', 'user_permissions', 'campuses').get(pk=user_id)
            user.is_active = newStatus
            user.save()

            serializer = self.serializer_class(user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail":str(e)}, status=400)
        
# delete user
class DeleteUser(generics.RetrieveDestroyAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response({"detail": "User deleted successfully"})


# ── Lecturer role assignment ──────────────────────────────────────────────────
class AssignLecturerRole(APIView):
    """
    PATCH { is_lecturer: true|false, staff_id?: string, password?: string }
    Grants or revokes lecturer portal access for a staff user.
    """
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def patch(self, request, *args, **kwargs):
        user_id = self.kwargs["pk"]
        flag = bool(request.data.get("is_lecturer"))
        try:
            user = User.objects.get(pk=user_id)
            user.is_lecturer = flag
            if "staff_id" in request.data:
                user.staff_id = (request.data.get("staff_id") or "").strip() or None
            if flag and request.data.get("password"):
                user.set_password(str(request.data.get("password")))
                user.must_change_password = True
            fields = ["is_lecturer"]
            if "staff_id" in request.data:
                fields.append("staff_id")
            if flag and request.data.get("password"):
                fields.extend(["password", "must_change_password"])
            user.save(update_fields=fields)

            group, _ = Group.objects.get_or_create(name="Lecturer")
            if flag:
                user.groups.add(group)
            else:
                user.groups.remove(group)

            return Response(UserSerializer(user).data, status=200)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

#=======================================================================roles================================================    
# List roles
class ListRoles(generics.ListAPIView):
    queryset = Group.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# list detailed roles
class ListDetailedRoles(generics.ListAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# list permissions
class ListPermissions(generics.ListAPIView):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# create roles
class CreateRoles(generics.CreateAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# edit roles
class EditRoles(generics.UpdateAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)

# delete roles
class DeleteRoles(generics.RetrieveDestroyAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"role deleted successfully"})

# ==================================================campus=================================================

# create campus
class CreateCampus(generics.CreateAPIView):
    queryset = Campus.objects.all()
    serializer_class = CampusSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# list campus

class ListCampus(generics.ListAPIView):
    queryset = Campus.objects.all()
    serializer_class = CampusSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# edit campus
class EditCampus(generics.UpdateAPIView):
    queryset = Campus.objects.all()
    serializer_class = CampusSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        cache.delete("all_campuses_list")

        return Response(serializer.data, status=200)
    
# delete campus
class DeleteCampus(generics.RetrieveDestroyAPIView):
    queryset = Campus.objects.all()
    serializer_class = CampusSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            with transaction.atomic():
                instance.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete this campus because other records still depend on it "
                        "(for example applications, admissions, or fee rules). Remove or "
                        "reassign those links first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        cache.delete("all_campuses_list")
        return Response(status=status.HTTP_204_NO_CONTENT)
    
# ======================================================Profile===================================================

class EditProfile(generics.UpdateAPIView):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
class GetUserProfile(generics.ListAPIView):
    queryset = Profile.objects.all()
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = Profile.objects.get(user=user)
        serializer = ProfileSerializer(profile)
        return Response(serializer.data, status=200)

# password reset link
class PasswordResetRequestView(APIView):
    def post(self, request):
        email = request.data.get('email')
        user = User.objects.filter(email=email).first()
        if not user:
                return Response({"detail": "User with this Email not found."}, status=status.HTTP_404_NOT_FOUND)
    
        try:
            celery_send_password_reset_Link.delay(user.id)
        except Exception:
            pass

        return Response({"detail": "Password reset email sent."}, status=status.HTTP_200_OK)

# reset login password view
class PasswordResetConfirmView(APIView):
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Step 2: Extract fields from validated data
        uidb64 = serializer.validated_data['uidb64']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['password']

        # Step 3: Decode uid and get user
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"detail": "Invalid user or token."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Step 4: Validate token BEFORE setting password
        if not default_token_generator.check_token(user, token):
            return Response(
                {"token": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Step 5: Now it's safe — set the new password
        user.set_password(new_password)
        user.save()

        return Response(
            {"message": "Password has been reset successfully."},
            status=status.HTTP_200_OK
        )

# Frontend redirect
def password_reset_redirect(request, uidb64, token):
    frontend_url = f"{settings.LOGIN_URL.rstrip('/')}/reset-password?uidb64={uidb64}&token={token}"
    return redirect(frontend_url)


# ── Student first-login forced password change ────────────────────────────────
class StudentFirstLoginChangePassword(APIView):
    """
    POST { new_password, confirm_password }
    Clears must_change_password flag after a successful change.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        user = request.user
        new_password     = request.data.get('new_password', '').strip()
        confirm_password = request.data.get('confirm_password', '').strip()

        if not new_password or not confirm_password:
            return Response(
                {'detail': 'Both new_password and confirm_password are required.'},
                status=400
            )

        if new_password != confirm_password:
            return Response({'detail': 'Passwords do not match.'}, status=400)

        if new_password == 'NDU@1234':
            return Response(
                {'detail': 'Please choose a password different from the default.'},
                status=400
            )

        try:
            validate_password(new_password, user)
        except DjangoValidationError as e:
            return Response({'detail': list(e.messages)}, status=400)

        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])

        # Issue fresh tokens so frontend can go straight to the portal
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        # Stamp custom claims (mirrors ObtainSerializer.get_token)
        for token in (refresh, refresh.access_token):
            token['first_name']          = user.first_name
            token['last_name']           = user.last_name
            token['is_staff']            = user.is_staff
            token['is_applicant']        = user.is_applicant
            token['is_student']          = user.is_student
            token['must_change_password'] = False          # explicitly cleared
            token['role']                = user.groups.first().name if user.groups.exists() else None
            token['phone']               = user.phone
            token['email']               = user.email
            token['username']            = user.username
            token['permissions']         = list(user.get_all_permissions())

        return Response({
            'detail': 'Password changed successfully.',
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
        })


# ─── Prospective Students (NDU Portal) ───────────────────────────────────────

class ProspectiveStudentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from admissions.models import Application
        from django.db.models import OuterRef, Subquery, Value
        from django.db.models.functions import Coalesce

        submitted_statuses = ['submitted', 'under_review', 'accepted', 'Admitted', 'rejected']

        latest_draft = Application.objects.filter(
            applicant=OuterRef('pk'),
            status='draft'
        ).order_by('-created_at')

        prospective = (
            User.objects.filter(is_applicant=True)
            .exclude(pk__in=Application.objects.filter(status__in=submitted_statuses).values('applicant'))
            .annotate(
                has_draft=Coalesce(
                    Subquery(latest_draft.values('status')[:1]),
                    Value('no_application')
                ),
                draft_started_at=Subquery(latest_draft.values('created_at')[:1]),
            )
            .order_by('-date_joined')
        )

        data = [
            {
                'id': u.id,
                'name': u.get_full_name() or u.email,
                'email': u.email,
                'phone': u.phone,
                'date_joined': u.date_joined,
                'last_login': u.last_login,
                'status': 'Draft Started' if u.has_draft == 'draft' else 'Never Started',
                'draft_started_at': u.draft_started_at,
                'days_since_joined': (timezone.now() - u.date_joined).days if u.date_joined else None,
            }
            for u in prospective
        ]
        return Response({'count': len(data), 'results': data})


class SendReminderEmail(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .tasks import celery_send_reminder_email
        try:
            user = User.objects.get(pk=pk, is_applicant=True)
            celery_send_reminder_email.delay(user.id)
            return Response({'detail': f'Reminder sent to {user.email}.'})
        except User.DoesNotExist:
            return Response({'detail': 'Applicant not found.'}, status=status.HTTP_404_NOT_FOUND)


class DeleteProspectiveStudent(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        from admissions.models import Application
        submitted_statuses = ['submitted', 'under_review', 'accepted', 'Admitted', 'rejected']
        try:
            user = User.objects.get(pk=pk, is_applicant=True)
        except User.DoesNotExist:
            return Response({'detail': 'Prospective student not found.'}, status=status.HTTP_404_NOT_FOUND)

        if Application.objects.filter(applicant=user, status__in=submitted_statuses).exists():
            return Response(
                {'detail': 'Cannot delete — this user has a submitted application.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.delete()
        return Response({'detail': 'Prospective student deleted successfully.'}, status=status.HTTP_200_OK)


class ProspectiveAnnouncement(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from admissions.models import Application
        from ndu_portal.send_grid import send_configurable_email

        subject = (request.data.get('subject') or '').strip()
        body = (request.data.get('body') or '').strip()
        status_filter = request.data.get('status', 'all')

        if not subject or not body:
            return Response({'detail': 'Subject and body are required.'}, status=400)

        submitted_statuses = ['submitted', 'under_review', 'accepted', 'Admitted', 'rejected']

        qs = User.objects.filter(
            is_applicant=True,
            is_active=True,
        ).exclude(
            pk__in=Application.objects.filter(
                status__in=submitted_statuses
            ).values('applicant')
        )

        if status_filter == 'Draft Started':
            qs = qs.filter(
                pk__in=Application.objects.filter(status='draft').values('applicant')
            )
        elif status_filter == 'Never Started':
            qs = qs.exclude(
                pk__in=Application.objects.values('applicant')
            )

        recipients = list(qs.values('id', 'first_name', 'last_name', 'email'))
        if not recipients:
            return Response({'detail': 'No prospective students match the selected filter.'}, status=400)

        sent, failed = 0, 0
        for r in recipients:
            personalised = body.replace('{first_name}', r['first_name'] or '').replace('{last_name}', r['last_name'] or '')
            if send_configurable_email(r['email'], subject, personalised):
                sent += 1
            else:
                failed += 1

        return Response({
            'detail': f'Sent to {sent} prospective student(s).{" " + str(failed) + " failed." if failed else ""}',
            'sent': sent, 'failed': failed,
        })


# ─── System Settings (NDU Portal) ────────────────────────────────────────────

class GetSystemSettings(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settings_obj = SystemSettings.get_settings()
        serializer = SystemSettingsSerializer(settings_obj)
        return Response(serializer.data)


class UpdateSystemSettings(APIView):
    permission_classes = [IsAuthenticated]

    def _format_validation_error(self, errors):
        if isinstance(errors, dict):
            for field, value in errors.items():
                if isinstance(value, list) and value:
                    return f"{field}: {value[0]}"
                if isinstance(value, dict):
                    nested = self._format_validation_error(value)
                    if nested:
                        return nested
        return "Invalid settings data."

    def _update(self, request):
        settings_obj = SystemSettings.get_settings()
        serializer = SystemSettingsSerializer(settings_obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(updated_by=request.user)
            return Response({'detail': 'Settings updated successfully.', **serializer.data})
        return Response(
            {
                "detail": self._format_validation_error(serializer.errors),
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def patch(self, request):
        return self._update(request)

    def put(self, request):
        return self._update(request)


# ─── System Usage Report (admin Reports → System Usage) ─────────────────────
class SystemUsageReport(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from audit.models import AuditLog
        from django.db.models import Count, Max
        from django.db.models.functions import TruncDate
        from datetime import timedelta

        thirty_days_ago = timezone.now() - timedelta(days=30)

        user_stats = (
            AuditLog.objects.filter(action='login')
            .values('user__id', 'user__first_name', 'user__last_name', 'user__email',
                    'user__is_staff', 'user__is_applicant')
            .annotate(login_count=Count('id'), last_seen=Max('timestamp'))
            .order_by('-login_count')
        )

        daily_logins = (
            AuditLog.objects.filter(action='login', timestamp__gte=thirty_days_ago)
            .annotate(day=TruncDate('timestamp'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )

        recent = AuditLog.objects.filter(action='login').select_related('user')[:50]
        recent_data = [
            {
                'user': f"{r.user.first_name} {r.user.last_name}".strip() if r.user else 'Unknown',
                'email': r.user.email if r.user else '',
                'is_staff': r.user.is_staff if r.user else False,
                'ip_address': r.ip_address,
                'timestamp': r.timestamp,
            }
            for r in recent
        ]

        total_logins = AuditLog.objects.filter(action='login').count()
        logins_today = AuditLog.objects.filter(
            action='login', timestamp__date=timezone.now().date()
        ).count()
        unique_users_today = AuditLog.objects.filter(
            action='login', timestamp__date=timezone.now().date()
        ).values('user').distinct().count()

        return Response({
            'summary': {
                'total_logins': total_logins,
                'logins_today': logins_today,
                'unique_users_today': unique_users_today,
            },
            'user_stats': list(user_stats),
            'daily_logins': list(daily_logins),
            'recent_logins': recent_data,
        })








