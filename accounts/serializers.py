from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from .models import User, Campus, Profile
from django.core.mail import send_mail
from django.conf import settings

# serializers

# campus
class CampusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campus
        fields = '__all__'

# user
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'

    def to_representation(self, instance):
        response =  super().to_representation(instance)
        response['campuses'] = CampusSerializer(instance.campuses.all(), many=True).data
        response['groups'] = RoleSerializer(instance.groups.all(), many=True).data
        return response
    
# login
class ObtainSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['first_name'] = user.first_name
        token['last_name'] = user.last_name
        token['is_staff'] = user.is_staff
        token['is_applicant'] = user.is_applicant
        token['last_login'] = user.last_login.isoformat() if user.last_login else None
        token['role'] = user.groups.first().name if user.groups.exists() else None
        token['phone'] = user.phone
        token['email'] = user.email 
        token['username'] = user.username

        return token
    
# register user
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )

    confirm_password = serializers.CharField(write_only=True, required=True, validators=[validate_password], style={'input_type': 'password'})

    campuses = serializers.PrimaryKeyRelatedField(
        queryset=Campus.objects.all(),
        required=False,
        allow_null=True,
        many=True  # ✅ allow multiple campus IDs if needed
    )

    class Meta:
        model = User
        fields = [
            'id', 'email', 'password','confirm_password',
            'first_name', 'last_name', 'last_login',
            'date_joined', 'role', 'campuses','phone',
            'is_active', 'is_staff', 'is_applicant'
        ]

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})

        # Check email uniqueness
        if User.objects.filter(email=data.get('email')).exists():
            raise serializers.ValidationError({'email': 'A user with this email already exists.'})
        
        return data

    def create(self, validated_data):
        role_name = validated_data.get('role', None)
        password = validated_data.pop('password')
        validated_data.pop('confirm_password')
        campuses = validated_data.pop('campuses', [])

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
            user.campuses.set(campuses)  # ✅ correct way for ManyToMany

        user.set_password(password)
        user.save()

        # Assign role if provided
        if role_name:
            try:
                group = Group.objects.get(name=role_name)
                user.groups.add(group)
            except Group.DoesNotExist:
                raise serializers.ValidationError({'role': f'Role "{role_name}" does not exist.'})

        # Send email
        # subject = "Account Created Successfully"
        # message = (
        #     f"Hello {user.first_name or user.email},\n\n"
        #     f"Your account has been created successfully.\n\n"
        #     f"Email: {user.email}\n"
        #     f"Password: {password}\n\n"
        #     f"Please log in and change your password."
        # )

        # send_mail(
        #     subject,
        #     message,
        #     settings.DEFAULT_FROM_EMAIL,
        #     [user.email],
        #     fail_silently=False,
        # )

        return user
   
# list role
class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ['id', 'name']

# create role
class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = '__all__'

#permissions
class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'

# profile
class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = '__all__'