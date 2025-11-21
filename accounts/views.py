# from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth import login, logout, authenticate
# from django.contrib.auth.decorators import login_required
# from django.contrib import messages
# from django.http import JsonResponse
# from django.views.decorators.csrf import csrf_exempt
# from django.utils.decorators import method_decorator
# from django.views.generic import View
# from accounts.forms import UserRegistrationForm, UserLoginForm, ProfileUpdateForm, AdminUserCreateForm, CampusForm
# from accounts.models import User, Campus
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








