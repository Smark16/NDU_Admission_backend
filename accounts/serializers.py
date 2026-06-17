from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from .models import User, Campus, Profile, SystemSettings
from admissions.models import Faculty
from .jwt_utils import apply_user_token_claims
from .role_assignment import role_requires_faculty_assignment
from .tasks import celery_send_account_email
from django.conf import settings
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator

# serializers

# campus
class CampusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campus
        fields = '__all__'

# user
def normalize_staff_id(value):
    text = (value or "").strip()
    return text or None


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'

    def validate_staff_id(self, value):
        return normalize_staff_id(value)

    def to_representation(self, instance):
        response =  super().to_representation(instance)
        response['campuses'] = CampusSerializer(instance.campuses.all(), many=True).data
        response['faculties'] = [
            {"id": f.id, "name": f.name, "code": f.code}
            for f in instance.faculties.all()
        ]
        response['groups'] = RoleSerializer(instance.groups.all(), many=True).data
        return response
    
# login
class ObtainSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        apply_user_token_claims(token, user)
        return token


class NduTokenRefreshSerializer(TokenRefreshSerializer):
    """Re-issue access tokens with up-to-date permissions after role changes."""

    def validate(self, attrs):
        data = super().validate(attrs)
        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.payload.get("user_id")
        if not user_id:
            return data
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return data
        access = ObtainSerializer.get_token(user)
        data["access"] = str(access.access_token)
        return data
    
# register user
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )

    confirm_password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    roles = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        write_only=True,
    )

    campuses = serializers.PrimaryKeyRelatedField(
        queryset=Campus.objects.all(),
        required=False,
        allow_null=True,
        many=True  # ✅ allow multiple campus IDs if needed
    )
    faculties = serializers.PrimaryKeyRelatedField(
        queryset=Faculty.objects.filter(is_active=True),
        required=False,
        many=True,
    )

    class Meta:
        model = User
        fields = [
            'id', 'email', 'password', 'confirm_password', 'roles',
            'first_name', 'last_name', 'last_login',
            'date_joined', 'role', 'campuses', 'faculties', 'phone',
            'is_active', 'is_staff', 'is_applicant',
        ]
        read_only_fields = ('id', 'last_login', 'date_joined')

    def validate_phone(self, value):
        if value in (None, ''):
            return ''
        return str(value).strip().replace(' ', '')[:20]

    def validate(self, data):
        role_name = (data.get("role") or "").strip().lower()
        roles = data.get("roles") or []
        role_names = [str(r).strip() for r in roles if str(r).strip()] if roles else ([data.get("role")] if data.get("role") else [])
        if role_name == "student" or any((r or "").strip().lower() == "student" for r in role_names):
            raise serializers.ValidationError(
                {"role": "Student accounts are created from Admissions/Direct Admission, not User Management."}
            )
        if any(role_requires_faculty_assignment(r) for r in role_names):
            faculty_list = data.get("faculties") or []
            if not faculty_list:
                raise serializers.ValidationError(
                    {"faculties": f"Assign at least one faculty for a {role_names[0].strip()} account."}
                )
        if bool(data.get("is_student")):
            raise serializers.ValidationError(
                {"is_student": "Student flag cannot be set from User Management."}
            )
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})

        # Check email uniqueness
        if User.objects.filter(email=data.get('email')).exists():
            raise serializers.ValidationError({'email': 'A user with this email already exists.'})
        
        return data

    def create(self, validated_data):
        role_name = validated_data.get('role', None)
        roles = validated_data.pop('roles', None)
        password = validated_data.pop('password')
        validated_data.pop('confirm_password')
        campuses = validated_data.pop('campuses', [])
        faculties = validated_data.pop('faculties', [])

        # Create user (excluding ManyToMany fields)
        user = User.objects.create(
            email=validated_data.get('email', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            phone=validated_data.get('phone', ''),
            username=validated_data.get('email', ''),
            role=validated_data.get('role', None),
            is_staff=validated_data.get('is_staff', False),
            is_applicant=validated_data.get('is_applicant', False)
        )

        # Assign campuses (ManyToMany field)
        if campuses:
            user.campuses.set(campuses)
        if faculties:
            user.faculties.set(faculties)

        user.set_password(password)
        user.save()

        from accounts.role_assignment import assign_user_role, set_user_roles

        if roles:
            set_user_roles(user, roles)
        elif role_name:
            assign_user_role(user, role_name)

        # Send email (best-effort — skip if broker/Redis is unavailable)
        try:
            celery_send_account_email.delay(user.id, password)
        except Exception:
            pass

        return user

#login password reset
class ResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)
    uidb64 = serializers.CharField(write_only=True, required=True) 
    token = serializers.CharField(write_only=True, required=True)  

    class Meta:
        model = User
        fields = ('password', 'password2', 'uidb64', 'token')

    def validate(self, attrs):
        # Check if the new password and its confirmation match
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})

        # Decode user ID from uidb64 and check token validity
        try:
            uid = urlsafe_base64_decode(attrs['uidb64']).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uidb64": "Invalid user."})

        attrs['user'] = user  
        return attrs

    def save(self, **kwargs):
        # Reset the user's password
        user = self.validated_data['user']
        user.set_password(self.validated_data['password'])
        user.save()
        return user
   
# list role
class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ['id', 'name']

# create role
class GroupSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(
        queryset=Permission.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Group
        fields = ("id", "name", "permissions")


# permissions (for role matrix UI)
class PermissionSerializer(serializers.ModelSerializer):
    app_label = serializers.CharField(source="content_type.app_label", read_only=True)

    class Meta:
        model = Permission
        fields = ("id", "name", "codename", "content_type", "app_label")

# profile
class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = '__all__'


class SystemSettingsSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source='updated_by.full_name', read_only=True, allow_null=True)
    portal_logo_url = serializers.SerializerMethodField()
    login_cover_url = serializers.SerializerMethodField()

    class Meta:
        model = SystemSettings
        fields = [
            'student_session_timeout',
            'admin_session_timeout',
            'id_card_templates',
            'active_id_card_template',
            'university_name',
            'portal_logo',
            'login_cover_image',
            'portal_logo_url',
            'login_cover_url',
            'updated_by_name',
            'updated_at',
        ]
        read_only_fields = ['portal_logo_url', 'login_cover_url', 'updated_at']

    def _absolute_media_url(self, file_field):
        if not file_field or not getattr(file_field, "name", None):
            return None
        request = self.context.get("request")
        url = file_field.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def get_portal_logo_url(self, obj):
        return self._absolute_media_url(obj.portal_logo)

    def get_login_cover_url(self, obj):
        return self._absolute_media_url(obj.login_cover_image)