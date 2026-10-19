from django.contrib.auth.password_validation import validate_password as _validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    # Team page status. "active" once the user has actually logged in,
    # otherwise "pending" (invited-but-never-accepted). The prior UI
    # bug — every team member showing "Pending" including the demo
    # user who was actively signed in — was because ``is_active`` and
    # ``last_login`` were both absent from this serializer, so the
    # frontend fell through to a hard-coded 'Pending' default.
    status = serializers.SerializerMethodField()
    # Path relative to the API base (the frontend prefixes VITE_BASE_URL).
    avatar = serializers.SerializerMethodField()
    last_login = serializers.DateTimeField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'email', 'password',
            'phone', 'role', 'avatar', 'username', 'organisation',
            'is_active', 'last_login', 'status',
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': False, 'allow_blank': True},
            'last_name': {'required': False, 'allow_blank': True},
            'phone': {'required': False, 'allow_blank': True, 'allow_null': True},
        }

    def get_avatar(self, obj):
        return f'/auth/avatar/{obj.avatar_key}' if obj.avatar_key else None

    def get_status(self, obj):
        if not getattr(obj, 'is_active', True):
            return 'suspended'
        if getattr(obj, 'last_login', None):
            return 'active'
        return 'pending'

    def validate(self, data):
        # Check email uniqueness
        email = data.get('email')
        if email and User.objects.filter(email=email).first():
            raise serializers.ValidationError({"error": "Email Address Already Exists"})
        # Phone uniqueness check only if phone is provided and not empty
        phone = data.get('phone')
        if phone and phone.strip() and User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError({"error": "Phone Number Already Exists"})

        # Enforce Django's AUTH_PASSWORD_VALIDATORS on new-password sets.
        # Prior code skipped these entirely because DRF serializers don't
        # invoke Django's form-side validators automatically — settings
        # said "MinimumLengthValidator + CommonPasswordValidator" but
        # register accepted password="123" (BE-P1-05, audit 2026-09-05).
        # Pass a transient User instance so UserAttributeSimilarityValidator
        # can compare the password against email / name.
        password = data.get('password')
        if password:
            transient_user = User(
                email=email or '',
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
            )
            try:
                _validate_password(password, transient_user)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'password': list(exc.messages)})

        return data
    
    def create(self, validated_data):
        password = validated_data.pop('password',None)
        instance = self.Meta.model(**validated_data)
        if password is not None:
            instance.set_password(password)
        instance.save()
        return instance  