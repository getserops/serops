import hashlib
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from .serializers import UserSerializer
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed
from .models import User
from Organisations.models import Organisations
from Organisations.serializers import OrganisationSerializer
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.authtoken.models import Token
from knox.models import AuthToken
from rest_framework import status
from django.contrib import auth
from Utils.email_utils import send_activation_link, send_reset_password_link
from django.contrib.auth.tokens import default_token_generator, PasswordResetTokenGenerator
from django.core import signing
import jwt
import os
from django.conf import settings
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.exceptions import ValidationError
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
import logging
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from Data.audit import log_login, log_logout, log_action

# Get Logger
logger = logging.getLogger(__name__)

# Common response schemas
registration_response = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
        'email': openapi.Schema(type=openapi.TYPE_STRING),
        'first_name': openapi.Schema(type=openapi.TYPE_STRING),
        'last_name': openapi.Schema(type=openapi.TYPE_STRING),
        'phone':openapi.Schema(type=openapi.TYPE_STRING),
    }
)

login_response = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        'token': openapi.Schema(type=openapi.TYPE_STRING),
        'user': openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING),
                'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                'phone':openapi.Schema(type=openapi.TYPE_STRING),
                'organisation': openapi.Schema(type=openapi.TYPE_STRING)
            }
        )
    }
)


def registration_open():
    """Whether POST /api/auth/register may create a new organisation.

    An explicit REGISTRATION_ENABLED wins. Unset means automatic: open
    until a real (non-demo) user belongs to an organisation — the first
    sign-up, or ``createsuperuser``, which provisions one — then closed.
    Demo users and demo organisations are ignored, so seeding the example
    org does not lock the owner out of creating theirs.
    """
    flag = getattr(settings, 'REGISTRATION_ENABLED', None)
    if flag is not None:
        return bool(flag)
    return not User.objects.filter(
        organisation__isnull=False,
        organisation__is_demo=False,
        is_demo=False,
    ).exists()

class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_register'

    @swagger_auto_schema(
        operation_description="Register a new user and organization",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['user', 'organisation'],
            properties={
                'user': openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    required=['email', 'password', 'password_confirmation', 'first_name', 'last_name', 'phone'],
                    properties={
                        'email': openapi.Schema(type=openapi.TYPE_STRING),
                        'password': openapi.Schema(type=openapi.TYPE_STRING),
                        'password_confirmation': openapi.Schema(type=openapi.TYPE_STRING),
                        'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'phone': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                ),
                'organisation': openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    required=['name', 'website'],
                    properties={
                        'name': openapi.Schema(type=openapi.TYPE_STRING),
                        'website': openapi.Schema(type=openapi.TYPE_STRING)
                    }
                )
            }
        ),
        responses={
            201: registration_response,
            400: 'Bad Request',
            500: 'Internal Server Error'
        },
        security=[{'Bearer': []}]
    )
    def post(self, request):
        # Gate: instances may disable open registration entirely (e.g. the
        # public demo host). Team members invited by an existing admin
        # still work — they go through /api/auth/accept/invitation, not
        # /register, so this check does not affect them.
        if not registration_open():
            return Response(
                {
                    'status': 'error',
                    'error': 'registration_disabled',
                    'message': (
                        'This SerOps instance does not accept new '
                        'registrations. Ask an admin for an invite, or '
                        'self-host your own instance: '
                        'https://serops.ai/docs/getting-started/quick-start-self-hosted/'
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if settings.BETA_INVITE_CODE:
            invite_code = request.data.get('invite_code')
            if not invite_code or invite_code != settings.BETA_INVITE_CODE:
                return Response({"status": "error", "message": "Invalid or missing invite code. Please request access to join the beta."}, status=status.HTTP_400_BAD_REQUEST)

        logger.debug("Received registration request")
        try:
            user_data = request.data.get('user', {})
            organisation_data = request.data.get('organisation', {})
            email = user_data.get('email', '')
            
            if not user_data or not organisation_data:
                logger.error("Missing required data: user or organisation data not provided")
                return Response(
                    {"error": "Both user and organisation data are required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.debug(f"Attempting to register user with email {email}")

            if user_data.get('password') != user_data.get('password_confirmation'):
                logger.warning(f"Password mismatch for user {email}")
                return Response(
                    {"error": "Passwords do not match"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            if User.objects.filter(email=email).exists():
                logger.error(f"Registration failed: Email {email} already exists")
                return Response(
                    {"error": "Email already exists"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Set default role to admin
            user_data['role'] = 'admin'
            # Auto-activate if no SMTP is configured at all (fresh on-prem
            # install without env vars AND no UI-configured SystemMailSettings
            # row). has_working_smtp_config() honors PLATFORM_SMTP_ENFORCED so
            # SaaS hosts only trust env-var SMTP.
            from notifications.services import has_working_smtp_config
            email_configured = has_working_smtp_config()

            serializer = UserSerializer(data=user_data)
            organisation_serializer = OrganisationSerializer(data=organisation_data)

            if not serializer.is_valid():
                logger.error(f"User validation failed for {email}: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            if not organisation_serializer.is_valid():
                logger.error(f"Organisation validation failed for user {email}: {organisation_serializer.errors}")
                return Response(organisation_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # SaaS: Initialize 14-Day Free Trial
            trial_days = 14
            from django.utils import timezone
            from datetime import timedelta
            
            # Create organisation manually or via serializer? Serializer is used for validation.
            # We save it, then update the SaaS fields which are not in the serializer fields list.
            user_organisation = organisation_serializer.save()
            
            user_organisation.subscription_status = 'trial'
            user_organisation.plan = 'starter'
            user_organisation.trial_ends_at = timezone.now() + timedelta(days=trial_days)
            user_organisation.save()

            user = serializer.save()
            user.organisation_id = user_organisation.id
            if not email_configured:
                user.is_active = True
            user.save()

            if email_configured:
                try:
                    send_activation_link(user, request)
                    logger.info(f"Activation email sent to {email}")
                except Exception as e:
                    logger.error(f"Failed to send activation email to {email}: {str(e)}")

            logger.info(f"User registered: {email}, role: admin, is_active: {user.is_active}")

            response_data = serializer.data
            if email_configured:
                response_data['message'] = "Registration successful! Please check your email and click the activation link to activate your account."
            else:
                response_data['message'] = "Registration successful! You can now log in."
            
            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.exception(f"Unexpected error during registration : {str(e)}")
            return Response(
                {"error": "An unexpected error occurred during registration"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_login'

    @swagger_auto_schema(
        operation_description="Login with email and password",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'password'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING),
                'password': openapi.Schema(type=openapi.TYPE_STRING)
            }
        ),
        responses={
            200: login_response,
            400: 'Bad Request',
            401: 'Unauthorized',
            403: 'Account not activated',
            404: 'Not Found',
            500: 'Internal Server Error'
        }
    )
    def post(self, request):
        logger.debug("Received login request")
        try:
            email = request.data.get('email')
            password = request.data.get('password')

            # Validate input parameters
            if not email or not password:
                logger.warning("Login attempt failed: Missing email or password")
                return Response(
                    {'error': 'Email and password are required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.debug(f"Attempting login for user: {email}")
            user = User.objects.filter(email=email).first()

            if not user:
                logger.error(f"Failed login attempt: no user found with email {email}")
                log_login(request, user=None, success=False)
                return Response(
                    {'error': 'User not found with this email'}, 
                    status=status.HTTP_404_NOT_FOUND
                )

            if not user.check_password(password):
                logger.error(f"Failed login attempt: incorrect password for user {email}")
                log_login(request, user=user, success=False)
                return Response(
                    {'error': 'Invalid password'}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Check if account is activated
            if not user.is_active:
                logger.warning(f"Login attempt rejected: account not activated for user {email}")
                return Response(
                    {'error': 'Your account is not activated. Please check your email and activate your account first.'}, 
                    status=status.HTTP_403_FORBIDDEN
                )

            status_messages = {
                "suspended": "Your account has been suspended. Please contact support.",
                "disabled": "Your account has been disabled. Please contact support."
            }

            if user.status in status_messages:
                logger.warning(f"Login attempt rejected: {user.status} account for user {email}")
                return Response(
                    {'error': status_messages[user.status]}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )

            try:
                # Use Knox for token with expiration
                # Delete any existing DRF tokens (for migration)
                Token.objects.filter(user=user).delete()
                
                # Create Knox token with expiration
                instance, token = AuthToken.objects.create(user)
                auth.login(request, user)
                
                userinfo = UserSerializer(user).data
                userinfo['organisation'] = user.organisation.name if user.organisation else None
                userinfo['role'] = user.role  # Include role for frontend RBAC
                
                log_login(request, user=user, success=True)
                # BE-P2-04 (audit 2026-09-05): use the proxy-aware helper
                # so audit-trail IPs behind Caddy/nginx/ELB are the
                # client's real address, not the load-balancer's.
                from Data.audit import get_client_ip
                logger.info(
                    "Successful login for user_id=%s from IP %s",
                    user.pk, get_client_ip(request),
                )
                return Response({
                    'token': token,
                    'user': userinfo
                }, status=status.HTTP_200_OK)

            except Exception as e:
                logger.error(f"Token creation failed for user {email}: {str(e)}")
                return Response(
                    {'error': 'Authentication failed. Please try again.'}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        except Exception as e:
            logger.exception(f"Unexpected error during login: {str(e)}")
            return Response(
                {'error': 'An unexpected error occurred. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DemoLoginView(APIView):
    """Anonymous one-click sign-in for the public read-only demo.

    Returns a fresh Knox token for the seeded ``demo@serops.ai`` user
    so visitors can land on the dashboard without typing credentials.
    The user is read-only at the application layer (see
    ``Middlewares.DemoUserMiddleware``); this endpoint just issues
    the session.

    Returns 404 when the seed has not been run yet, so a fresh
    self-host that hasn't run ``python manage.py seed_demo_org``
    cleanly signals "no demo configured" instead of half-failing.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_demo_login'

    @swagger_auto_schema(
        operation_description=(
            "Anonymous bootstrap for the public live demo. Issues a Knox "
            "token for the seeded read-only demo user. No request body."
        ),
        responses={
            200: 'Returns {token, user, banner}',
            404: 'Demo org not configured on this deployment',
            429: 'Too many requests',
        },
    )
    def post(self, request):
        # Find a user explicitly flagged as the demo identity. We avoid
        # matching by email so a self-hoster who renamed the seeded
        # account still gets the right user picked.
        demo_user = (
            User.objects
            .filter(is_demo=True, is_active=True, organisation__is_demo=True)
            .select_related('organisation')
            .first()
        )
        if demo_user is None:
            return Response(
                {
                    'error': 'demo_not_configured',
                    'message': (
                        'No demo organisation is configured on this '
                        'deployment. Run `python manage.py seed_demo_org` '
                        'to create one.'
                    ),
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        _instance, token = AuthToken.objects.create(demo_user)
        return Response({
            'token': token,
            'user': {
                'id': demo_user.id,
                'email': demo_user.email,
                'username': demo_user.username,
                'first_name': demo_user.first_name,
                'last_name': demo_user.last_name,
                'role': demo_user.role,
                'is_demo': True,
                'organisation_id': demo_user.organisation_id,
                'organisation_name': (
                    demo_user.organisation.name
                    if demo_user.organisation else None
                ),
            },
            # Copy the frontend renders verbatim on a persistent
            # banner. Keeping it server-side lets ops tweak the message
            # without a frontend redeploy.
            'banner': (
                "You're in the SerOps live demo — data resets nightly. "
                "Sign up for your own org to make changes."
            ),
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Logout current user",
        responses={
            200: openapi.Response('Successfully logged out'),
            400: 'Bad Request',
            500: 'Internal Server Error'
        }
    )
    def post(self, request):
        logger.debug("Received logout request")
        user = request.user
        logger.debug(f"User {user.email} is attempting to log out.")
        token = request.auth
        if not token:
            logger.warning(f"Logout failed: No authentication token provided by user {user.email}")
            return Response({"error": "Invalid token or already logged out."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            # Log logout before deleting token/session to ensure valid state
            log_logout(request, user=user)
            
            # Delete the current Knox token
            request._auth.delete()
            auth.logout(request)
            
            logger.info(f"User {user.email} successfully logged out.")
            return Response({
                "message": "You have successfully logged out.",
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Logout error for user {user.email}: {str(e)}")
            return Response({"error": "Logout failed due to an internal error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class EmailVerification(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_description="Verify email with token",
        manual_parameters=[
            openapi.Parameter(
                'token',
                openapi.IN_PATH,
                description="Verification token",
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        responses={
            200: 'Email verified successfully',
            400: 'Bad Request - Invalid token',
            404: 'User not found',
            500: 'Internal Server Error'
        }
    )
    def get(self, request, token):
        # Never log the raw token — it grants account activation (BE-P1-04,
        # audit 2026-09-05). Log outcome only.
        try:
            user_id = signing.loads(token)
        except signing.BadSignature:
            logger.warning("Email verification: invalid token signature")
            return Response({"error": "Invalid token."}, status=400)
        except signing.SignatureExpired:
            logger.warning("Email verification: expired token")
            return Response({"error": "Token has expired."}, status=400)
        except Exception as e:
            logger.exception(f"Unexpected error decoding token: {str(e)}")
            return Response({"error": "Something went wrong while processing the token."}, status=500)
        
        try:
            user = User.objects.get(pk=user_id)
            if user.is_active:
                logger.info(f"User {user.email} (ID: {user_id}) is already active.")
                return Response({"message": "Your account is already activated."}, status=200)
            
            # Activate the user account
            user.is_active = True
            user.save()
            
            logger.info(f"User {user.email} (ID: {user_id}) successfully activated via email verification.")
            return Response({"message": "You have successfully activated your account. You can now log in."}, status=200)
            
        except User.DoesNotExist:
            logger.error(f"User with ID {user_id} not found.")
            return Response({"error": "User not found."}, status=404)
        except Exception as e:
            logger.exception(f"Unexpected error activating user {user_id}: {str(e)}")
            return Response({"error": "Something went wrong while activating your account."}, status=500)

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Get user profile",
        responses={
            200: UserSerializer,
            500: 'Internal Server Error'
        }
    )
    def get(self, request):
        """Retrieve the authenticated user's profile."""
        try:
            logger.debug(f"Fetching profile for user {request.user.email}")
            user = get_object_or_404(User, id=request.user.id)
            serializer = UserSerializer(user)
            logger.info(f"Profile successfully retrieved for user {user.email}")
            return Response(serializer.data, status=200)
        except Exception as e:
            logger.exception(f"Unexpected error while retrieving profile: {str(e)}")
            return Response({"error": "Something went wrong while retrieving your profile."}, status=500)

    @swagger_auto_schema(
        operation_description="Update user profile",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING),
                'phone': openapi.Schema(type=openapi.TYPE_STRING),
                'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                'last_name': openapi.Schema(type=openapi.TYPE_STRING)
            }
        ),
        responses={
            200: UserSerializer,
            400: 'Bad Request',
            500: 'Internal Server Error'
        }
    )
    def post(self, request):
        """Update the authenticated user's profile."""
        try:
            logger.debug(f"Updating profile for user {request.user.email}")
            user = get_object_or_404(User, id=request.user.id)

            email = request.data.get('email', user.email)
            phone = request.data.get('phone', user.phone)
            first_name = request.data.get('first_name', user.first_name)
            last_name = request.data.get('last_name', user.last_name)

            # Check if the email is being changed and if it already exists
            if email != user.email and User.objects.filter(email=email).exists():
                logger.warning(f"Email update failed for user {user.email}: {email} already in use")
                return Response({"error": "Email address already used!"}, status=400)

            # Check if the phone is being changed and if it already exists
            if phone != user.phone and User.objects.filter(phone=phone).exists():
                logger.warning(f"Phone update failed for user {user.email}: {phone} already in use")
                return Response({"error": "Phone number already used!"}, status=400)

            # Perform the update
            user.email = email
            user.phone = phone
            user.first_name = first_name
            user.last_name = last_name
            user.save()

            serializer = UserSerializer(user)
            logger.info(f"Profile successfully updated for user {user.email}")
            return Response(serializer.data, status=200)

        except Exception as e:
            logger.exception(f"Unexpected error while updating profile for {request.user.email}: {str(e)}")
            return Response({"error": "Something went wrong while updating your profile."}, status=500)

class UpdatePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Update user password",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['old_password', 'new_password', 'new_password_copy'],
            properties={
                'old_password': openapi.Schema(type=openapi.TYPE_STRING),
                'new_password': openapi.Schema(type=openapi.TYPE_STRING),
                'new_password_copy': openapi.Schema(type=openapi.TYPE_STRING)
            }
        ),
        responses={
            200: 'Password updated successfully',
            400: 'Bad Request',
            500: 'Internal Server Error'
        }
    )
    def post(self, request):
        logger.debug(f"Password update requested for user {request.user.email}")
        user = User.objects.get(id=request.user.id)
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')
        new_password_copy = request.data.get('new_password_copy')
        if not old_password or not new_password or not new_password_copy:
            logger.warning(f"Password update failed: missing required fields for user {user.email}")
            return Response({'error': 'Old password and new password are required fields'}, status=400)
        if not user.check_password(old_password):
            logger.warning(f"Password update failed: invalid old password for user {user.email}")
            return Response({'error': 'Invalid old password'}, status=400)
        if new_password != new_password_copy:
            logger.warning(f"Password update failed: new passwords don't match for user {user.email}")
            return Response({'error': 'Invalid new password'}, status=400)
        user.set_password(new_password)
        user.save()

        # Revoke every existing Knox token for this user so any stale or
        # stolen token cannot survive a password rotation. The token used
        # for this request is included — the client must log in again.
        revoked = AuthToken.objects.filter(user=user).delete()[0]
        logger.info(
            f"Password updated for user {user.email}; revoked {revoked} active tokens"
        )

        log_action(request, 'PASSWORD_CHANGE', user=user)
        return Response({'success': 'Password updated successfully'}, status=200)

class ResendVerificationLinkView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Resend verification email",
        responses={
            200: 'Email sent successfully',
            400: 'Account already activated',
            500: 'Internal Server Error'
        }
    )
    def get(self, request):
        logger.debug(f"Resend verification requested for user {request.user.email}")
        user = User.objects.get(id=request.user.id)
        if user.is_active == True:
            logger.warning(f"Verification resend rejected: account already active for user {user.email}")
            return Response({'error': 'Account Already activated'}, status=400)
        send_activation_link(user, request)
        logger.info(f"Verification email resent to user {user.email}")
        return Response({'success': 'Email was sent successfully'})

class AcceptInvitationView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_description="Accept user invitation",
        manual_parameters=[
            openapi.Parameter(
                'token',
                openapi.IN_PATH,
                description="Invitation token",
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        responses={
            200: UserSerializer,
            400: 'Invalid Token',
            500: 'Internal Server Error'
        }
    )
    def get(self, request, token):
        # Never log the token itself — signed JWT grants account access
        # for its full TTL. Whoever ships logs to a SIEM gets outstanding
        # invitations for free (BE-P1-04, audit 2026-09-05).
        try:
            decoded_token = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            user_id = decoded_token['user']
            user = User.objects.get(pk=user_id)
            serializer = UserSerializer(user)
            logger.info("Invitation accepted for user_id=%s", user.pk)
            return Response({"user": serializer.data}, status=200)
        except jwt.InvalidTokenError:
            logger.warning("Invalid invitation token presented")
            return Response({"error": "Invalid Token"}, status=400)

class ForgetPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'

    @swagger_auto_schema(
        operation_description="Request password reset",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING)
            }
        ),
        responses={
            200: 'Password reset email sent',
            400: 'Bad Request',
            500: 'Internal Server Error'
        }
    )
    def post(self, request):
        # Constant response — never confirm whether the email exists. Prior
        # implementation returned 400 "Email address not found" which let
        # unauthenticated callers enumerate the customer list. Rate-limit
        # slows enumeration but doesn't prevent it (BE-P1-03, audit
        # 2026-09-05).
        generic_success = Response(
            {'message': 'If an account exists with that email, we have '
                        'sent a password reset link.'},
            status=status.HTTP_200_OK,
        )

        email = request.data.get('email')
        if not email:
            return Response(
                {'error': 'Email is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Do not log the attempted email — either it's a fat-finger
            # typo (log noise) or an enumeration attempt (feeding the
            # attacker's discovery loop). Both cases: swallow silently.
            return generic_success

        token_generator = PasswordResetTokenGenerator()
        uidb64 = urlsafe_base64_encode(str(user.pk).encode('utf-8'))
        token = token_generator.make_token(user)
        reset_password_url = f'{settings.REACT_URL}/password/reset/{uidb64}/{token}'
        send_reset_password_link(user.email, reset_password_url)
        # Log user id, not email — email in logs is a GDPR/SOC2 concern
        # and doesn't add debugging value we don't already have.
        logger.info("Password reset link sent for user_id=%s", user.pk)
        return generic_success

class SetPasswordView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_description="Reset password with token",
        manual_parameters=[
            openapi.Parameter(
                'uidb64',
                openapi.IN_PATH,
                description="User ID",
                type=openapi.TYPE_STRING,
                required=True
            ),
            openapi.Parameter(
                'token',
                openapi.IN_PATH,
                description="Reset token",
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['new_password', 'new_password_confirm'],
            properties={
                'new_password': openapi.Schema(type=openapi.TYPE_STRING),
                'new_password_confirm': openapi.Schema(type=openapi.TYPE_STRING)
            }
        ),
        responses={
            200: 'Password reset successfully',
            400: 'Bad Request',
            500: 'Internal Server Error'
        }
    )
    def post(self, request, uidb64, token):
        # Never log the reset token itself (BE-P1-04, audit 2026-09-05).
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
            token_generator = PasswordResetTokenGenerator()
            if not token_generator.check_token(user, token):
                logger.warning("Password reset: invalid/expired token for user_id=%s", user.pk)
                return Response({'error': 'Invalid or expired token'}, status=status.HTTP_400_BAD_REQUEST)
            
            new_password = request.data.get('new_password')
            new_password_confirm = request.data.get('new_password_confirm')
            
            if not new_password or not new_password_confirm:
                logger.warning(f"Password reset failed: missing password for user {user.email}")
                raise ValidationError({'new_password': 'Password is required.'})
            
            if new_password != new_password_confirm:
                logger.warning(f"Password reset failed: passwords don't match for user {user.email}")
                raise ValidationError({'new_password_confirm': 'Passwords do not match.'})
            
            user.set_password(new_password)
            user.save()

            # Defensive: a password reset is often triggered because the
            # user suspects compromise. Burn any active tokens.
            revoked = AuthToken.objects.filter(user=user).delete()[0]
            logger.info(
                f"Password reset for user {user.email}; revoked {revoked} active tokens"
            )

            log_action(request, 'PASSWORD_CHANGE', user=user)
            return Response({'message': 'Password reset successfully!'}, status=status.HTTP_200_OK)
            
        except (ValueError, TypeError, User.DoesNotExist):
            logger.error(f"Invalid password reset attempt with uidb64: {uidb64}")
            return Response({'error': 'Invalid token or user'}, status=status.HTTP_400_BAD_REQUEST)

class InvitationsetPasswordView(APIView):
    """Complete the invitation flow — set the invited user's password.

    Security note (2026-08-30): prior version trusted a body-supplied
    ``user_id`` under ``AllowAny``, which meant any unauthenticated
    caller could POST ``{"user_id": 1, "password": "x"}`` and take
    over any account. Full-account-takeover for every user in the
    system. Now the view requires the same JWT that was issued in
    the invitation email — the ``user_id`` is decoded from the
    signed token server-side. Body-supplied ``user_id`` is ignored.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'

    @swagger_auto_schema(
        operation_description="Set password for invited user (requires invitation JWT)",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['token', 'password', 'password_confirmation'],
            properties={
                'token': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='Signed invitation JWT (same token that was in the invitation email).',
                ),
                'password': openapi.Schema(type=openapi.TYPE_STRING),
                'password_confirmation': openapi.Schema(type=openapi.TYPE_STRING),
            },
        ),
        responses={
            200: 'Password set successfully',
            400: 'Bad Request',
            401: 'Invalid or expired invitation token',
            404: 'User not found',
        },
    )
    def post(self, request):
        token = request.data.get('token')
        password = request.data.get('password')
        password_confirmation = request.data.get('password_confirmation')

        if not token:
            return Response({"error": "Invitation token is required"}, status=400)
        if not password:
            return Response({"error": "password is required"}, status=400)
        if not password_confirmation:
            return Response({"error": "password confirmation is required"}, status=400)
        if password != password_confirmation:
            return Response({"error": "Passwords do not match"}, status=400)

        try:
            decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            logger.warning("Invitation password set: expired token presented")
            return Response({"error": "Invitation token has expired"}, status=401)
        except jwt.InvalidTokenError:
            logger.warning("Invitation password set: invalid token presented")
            return Response({"error": "Invalid invitation token"}, status=401)

        user_id = decoded.get('user')
        if not user_id:
            return Response({"error": "Invalid invitation token"}, status=401)

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            # Log at info — a stale token for a deleted user is
            # possible, doesn't warrant an error-level alarm.
            logger.info(f"Invitation password set: token references missing user id={user_id}")
            return Response({"error": "User does not exist"}, status=404)

        user.set_password(password)
        user.save()
        log_action(request, 'PASSWORD_CHANGE', user=user)
        logger.info(f"Password successfully set for invited user {user.email}")
        return Response({'success': 'Password updated successfully'}, status=200)

class ProfileAvatarView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    ALLOWED_IMAGE_EXTENSIONS = ["png","jpeg","jpg"]
    @swagger_auto_schema(
        operation_description="Update user avatar",
        manual_parameters=[
            openapi.Parameter(
                'avatar',
                openapi.IN_FORM,
                description="Avatar image file (JPEG, JPG, PNG only)",
                type=openapi.TYPE_FILE,
                required=True
            )
        ],
        responses={
            200: 'Avatar uploaded successfully',
            400: 'Bad Request - Invalid file format',
            500: 'Internal Server Error'
        }
    )
    def put(self, request):
        logger.debug(f"Avatar update requested for user {request.user.email}")
        user = User.objects.get(id=request.user.id)
        
        if 'avatar' not in request.data:
            logger.warning(f"Avatar update failed: no avatar data provided for user {user.email}")
            return Response({'error': 'No avatar data provided'}, status=400)
            
        avatar_file = request.FILES.get('avatar')
        file_extension = avatar_file.name.split('.')[-1].lower()

        if file_extension not in self.ALLOWED_IMAGE_EXTENSIONS:
            logger.warning(f"Avatar update failed: invalid format ({file_extension}) for user {user.email}")
            return Response({'error': 'Invalid image format. Allowed formats: JPEG, JPG, PNG'}, status=400)

        file_hash = hashlib.sha256(avatar_file.read()).hexdigest()
        avatar_file.seek(0)
        avatar_filename = f"{user.id}_{file_hash[:10]}.{file_extension}"
        avatar_path = os.path.join('images/', avatar_filename)
        os.makedirs('images', exist_ok=True)

        with open(avatar_path, 'wb+') as destination:
            for chunk in avatar_file.chunks():
                destination.write(chunk)
                
        user.avatar = avatar_path
        user.save()
        logger.info(f"Avatar successfully updated for user {user.email}")
        return Response({'message': 'Avatar uploaded successfully'}, status=200)


class DeleteAccountView(APIView):
    """GDPR right-to-erasure endpoint.

    DELETE /api/auth/account — hard-deletes the authenticated user.

    To prevent accidental deletion, the request body must contain
    ``{"confirm": "DELETE"}`` exactly. The endpoint returns 400 otherwise.

    Cascade behaviour:
      - All Knox tokens for the user are revoked.
      - Owned ChatSessions, ChatMessages, LogAnalyses, and Notifications
        are deleted via the on_delete=CASCADE FK on those models.
      - AuditLog rows have ``on_delete=SET_NULL`` on the user FK, so the
        compliance trail is preserved but no longer identifies the user.
      - If the user is the sole admin of their organisation, the
        organisation itself is deleted (which cascades all org-scoped
        data: projects, services, batches, issues, integrations,
        settings, audit logs).
      - Otherwise the organisation stays — other admins keep their access.

    An ACCOUNT_DELETE (or ORG_DELETE when the org goes too) AuditLog row
    is written BEFORE the destructive operation so the action is
    recorded even when the org is being purged.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description=(
            "GDPR right-to-erasure. Permanently deletes the authenticated "
            "user. Requires body {\"confirm\": \"DELETE\"}."
        ),
        responses={
            204: 'Account deleted',
            400: 'Missing or invalid confirmation token',
            500: 'Internal Server Error',
        },
    )
    def delete(self, request):
        from django.db import transaction
        from django.db.models import Q
        from Organisations.models import Organisations

        if request.data.get('confirm') != 'DELETE':
            return Response(
                {'error': 'Confirmation required. Send {"confirm": "DELETE"} in the body.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        org = user.organisation
        user_email_for_log = user.email
        user_id_for_log = user.id

        # Decide whether the org goes too. The user is the "sole admin"
        # when no other active admin shares the organisation.
        delete_org = False
        if org is not None:
            other_admins_exist = User.objects.filter(
                organisation=org,
                role='admin',
                is_active=True,
            ).filter(~Q(pk=user.pk)).exists()
            if not other_admins_exist:
                delete_org = True

        try:
            with transaction.atomic():
                # Write the audit log BEFORE the destructive op so the
                # row survives even when the org is cascaded away.
                # When delete_org is True the AuditLog row will be
                # cascade-deleted with the org, which is GDPR-correct —
                # the trail goes with the data.
                log_action(
                    request,
                    'ORG_DELETE' if delete_org else 'ACCOUNT_DELETE',
                    details={
                        'deleted_user_id': user_id_for_log,
                        'deleted_user_email': user_email_for_log,
                        'org_deleted': delete_org,
                    },
                )

                # Revoke every Knox token for this user (cascade would
                # take them too, but doing it explicitly leaves no
                # window where a stolen token could outlive the user).
                AuthToken.objects.filter(user=user).delete()

                if delete_org:
                    org.delete()
                else:
                    user.delete()
        except Exception as e:
            logger.exception(f"Failed to delete account for {user_email_for_log}: {e}")
            return Response(
                {'error': 'Account deletion failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            f"GDPR account deletion completed: user_id={user_id_for_log}, "
            f"email={user_email_for_log}, org_deleted={delete_org}"
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class RegistrationStatusView(APIView):
    """Public flag the frontend polls on the Login page.

    Returns whether this SerOps instance accepts open registrations.
    Instances (like the hosted demo) that only allow one-click demo
    login or admin-invited users report ``registration_enabled=False``;
    the frontend hides the "Create account" / "Have invite code"
    prompts based on this value.

    Kept as a dedicated read-only endpoint so it can be polled without
    authentication and cached at the CDN if needed.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({
            'registration_enabled': registration_open(),
        })