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
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import authenticate
from .serializers import *
from .models import *

from audit.utils import log_audit_event

# caching
from django.core.cache import cache

from django.utils.http import urlsafe_base64_decode
from django.shortcuts import redirect
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
        serializer = self.serializer_class(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

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

    def get(self, request, *args, **kwargs):
        cache_key = 'all_campuses_list'

        # Try cache first
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        # Get fresh data
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        # Cache for 24 hours (86,400 seconds)
        cache.set(cache_key, data, timeout=60 * 60 * 24)

        return Response(data)

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

        return Response(serializer.data, status=200)
    
# delete campus
class DeleteCampus(generics.RetrieveDestroyAPIView):
    queryset = Campus.objects.all()
    serializer_class = CampusSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"campus deleted successfully"})
    
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
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "User with this Email not found."}, status=status.HTTP_404_NOT_FOUND)

        celery_send_password_reset_Link.delay(user.id)

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








