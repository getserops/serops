from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import EmailValidator
from django.utils.crypto import get_random_string
from django.contrib.auth.hashers import make_password
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import permission_classes
from rest_framework import status
import logging

from .models import Organisations
from .serializers import OrganisationSerializer
from Users.models import User
from Users.serializers import UserSerializer
from Middlewares.OrganisationMiddleware import OrganisationsPermissions
from Middlewares.rbac import IsAdminRole
from Utils.email_utils import send_invitation_link
from Data.audit import log_team_action

logger = logging.getLogger(__name__)

class OrganisationInfoView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Get authenticated user's organisation information",
        responses={
            200: OrganisationSerializer,
            404: 'Organisation not found',
            500: 'Internal Server Error'
        },
        security=[{'Bearer': []}]
    )
    def get(self, request):
        try:
            organisation = request.user.organisation
            if not organisation:
                logger.error(f"No organisation found for user {request.user.email}")
                return Response(
                    {"error": "No organisation found for this user"}, 
                    status=404
                )

            logger.debug(f"Retrieving organisation info for {organisation.name}")
            serializer = OrganisationSerializer(organisation, context={'request': request})
            return Response(serializer.data)

        except Exception as e:
            logger.exception(f"Error retrieving organisation info: {str(e)}")
            return Response(
                {"error": "An error occurred while retrieving organisation information"}, 
                status=500
            )

    @swagger_auto_schema(
        operation_description="Update organisation information",
        request_body=OrganisationSerializer,
        responses={
            200: OrganisationSerializer,
            400: 'Bad Request',
            404: 'Organisation not found',
            500: 'Internal Server Error'
        },
        security=[{'Bearer': []}]
    )
    def put(self, request):
        if getattr(request.user, 'role', None) != 'admin':
            return Response({"error": "Admin role required"}, status=status.HTTP_403_FORBIDDEN)
        try:
            organisation = request.user.organisation
            if not organisation:
                logger.error(f"No organisation found for user {request.user.email}")
                return Response(
                    {"error": "No organisation found for this user"},
                    status=404
                )

            serializer = OrganisationSerializer(
                organisation,
                data=request.data,
                partial=True,
                context={'request': request},
            )

            if serializer.is_valid():
                serializer.save()
                logger.info(f"Organisation {organisation.name} updated successfully")
                return Response(serializer.data)

            logger.error(f"Invalid data for organisation update: {serializer.errors}")
            return Response(serializer.errors, status=400)

        except Exception as e:
            logger.exception(f"Error updating organisation: {str(e)}")
            return Response(
                {"error": "An error occurred while updating organisation information"},
                status=500
            )

class OrganisationTeamView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    @swagger_auto_schema(
        operation_description="Get all team members in the organization",
        manual_parameters=[
            openapi.Parameter('page', openapi.IN_QUERY, description="Page number", type=openapi.TYPE_INTEGER),
            openapi.Parameter('per_page', openapi.IN_QUERY, description="Items per page", type=openapi.TYPE_INTEGER, default=10),
        ],
        responses={
            200: openapi.Response(
                "Success",
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'users': openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.Schema(type=openapi.TYPE_OBJECT)
                        ),
                        'actual_page': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'total_pages': openapi.Schema(type=openapi.TYPE_INTEGER),
                    }
                )
            ),
            401: "Authentication credentials were not provided",
            403: "Permission denied"
        },
        tags=['Organizations - Team']
    )
    def get(self, request):
        users = User.objects.filter(organisation=request.user.organisation).order_by('id')
        page = request.query_params.get('page', 1)
        per_page = request.query_params.get('per_page', 10)

        paginator = Paginator(users, per_page)
        users_page = paginator.get_page(page)

        serialized_users = UserSerializer(users_page, many=True)

        return Response({
            "users": serialized_users.data,
            "actual_page": users_page.number,
            "total_pages": paginator.num_pages
        })

    @swagger_auto_schema(
        operation_description="Add a new team member to the organization (send invitation)",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['user'],
            properties={
                'user': openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    required=['email', 'role'],
                    properties={
                        'email': openapi.Schema(type=openapi.TYPE_STRING, description='Email address for invitation'),
                        'role': openapi.Schema(type=openapi.TYPE_STRING, description='User role: viewer, user, or admin'),
                    }
                )
            }
        ),
        responses={
            200: openapi.Response("User created successfully", UserSerializer()),
            400: "Invalid input data",
            401: "Authentication credentials were not provided",
            403: "Permission denied"
        },
        tags=['Organizations - Team']
    )
    def post(self, request):
        user_info = request.data.get("user")
        if not user_info:
            return Response({"error": "User data is required"}, status=400)

        email = user_info.get('email')
        if not email:
            return Response({"error": "Email is required"}, status=400)

        try:
            EmailValidator()(email)
        except ValidationError:
            return Response({"email": "Invalid email format"}, status=400)

        user_info['password'] = make_password(get_random_string(length=16))
        user_info['phone'] = user_info.get('phone', '')

        serializer = UserSerializer(data=user_info)
        if serializer.is_valid():
            user = serializer.save()
            user.organisation = request.user.organisation
            user.is_active = True
            user.save()

            send_invitation_link(user)
            
            # Log the team invite action
            log_team_action(request, 'TEAM_INVITE', user.email, role=user.role)
            
            data = serializer.data
            data.pop('password', None)
            return Response({"user": data}, status=200)

        return Response(serializer.errors, status=400)

class OrganisationMemberView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    @swagger_auto_schema(
        operation_description="Get details of a specific team member",
        responses={
            200: openapi.Response("Success", UserSerializer()),
            400: "User does not exist",
            401: "Authentication credentials were not provided",
            403: "Permission denied"
        },
        tags=['Organizations - Members']
    )
    def get(self, request, id):
        try:
            user = User.objects.get(pk=id, organisation=request.user.organisation)
            return Response({"user": UserSerializer(user).data}, status=200)
        except User.DoesNotExist:
            return Response({'error': 'User does not exist'}, status=400)

    @swagger_auto_schema(
        operation_description="Delete a team member",
        responses={
            200: "User deleted successfully",
            400: "User does not exist",
            401: "Authentication credentials were not provided",
            403: "Permission denied"
        },
        tags=['Organizations - Members']
    )
    def delete(self, request, id):
        try:
            user = User.objects.get(pk=id, organisation=request.user.organisation)
            email_to_remove = user.email
            user.delete()
            
            # Log the team remove action
            log_team_action(request, 'TEAM_REMOVE', email_to_remove)
            
            return Response({'success': 'User deleted successfully'}, status=200)
        except User.DoesNotExist:
            return Response({'error': 'User does not exist'}, status=400)

    @swagger_auto_schema(
        operation_description="Update a team member's information",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                'email': openapi.Schema(type=openapi.TYPE_STRING),
                'phone': openapi.Schema(type=openapi.TYPE_STRING),
                'role': openapi.Schema(type=openapi.TYPE_STRING),
            }
        ),
        responses={
            200: "User updated successfully",
            400: "Invalid input or user does not exist",
            401: "Authentication credentials were not provided",
            403: "Permission denied"
        },
        tags=['Organizations - Members']
    )
    def put(self, request, id):
        try:
            user = User.objects.get(pk=id, organisation=request.user.organisation)
            for field in ['first_name', 'last_name', 'email', 'phone', 'role']:
                if field in request.data:
                    setattr(user, field, request.data[field])
            user.save()
            
            # Log the role change if it was updated
            if 'role' in request.data:
                log_team_action(request, 'TEAM_ROLE_CHANGE', user.email, role=user.role)
                
            return Response({'message': 'User updated successfully'}, status=200)
        except User.DoesNotExist:
            return Response({'error': 'User does not exist'}, status=400)

class OrganisationCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    @swagger_auto_schema(
        operation_description="Create a new organization",
        request_body=OrganisationSerializer,
        responses={
            201: OrganisationSerializer,
            400: 'Invalid input data',
            500: 'Internal Server Error'
        },
        tags=['Organizations']
    )
    def post(self, request):
        try:
            serializer = OrganisationSerializer(data=request.data)
            if serializer.is_valid():
                organisation = serializer.save()
                logger.info(f"Organisation {organisation.name} created successfully")
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            
            logger.error(f"Invalid data for organisation creation: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.exception(f"Error creating organisation: {str(e)}")
            return Response(
                {"error": "An error occurred while creating the organisation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class OrganisationUpdateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    @swagger_auto_schema(
        operation_description="Update an existing organization",
        request_body=OrganisationSerializer,
        responses={
            200: OrganisationSerializer,
            400: 'Invalid input data',
            404: 'Organisation not found',
            500: 'Internal Server Error'
        },
        tags=['Organizations']
    )
    def put(self, request, id):
        try:
            # BE-P2-02 (audit 2026-09-05): fetch scoped to caller's org
            # so cross-org existence isn't observable through the
            # response status (404 vs 403 leaked "org id X exists but
            # belongs to someone else" — an enumeration oracle).
            organisation = Organisations.objects.filter(
                pk=id, id=request.user.organisation_id,
            ).first()
            if organisation is None:
                return Response(
                    {"error": "Organisation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = OrganisationSerializer(
                organisation,
                data=request.data,
                partial=True
            )
            
            if serializer.is_valid():
                serializer.save()
                logger.info(f"Organisation {organisation.name} updated successfully")
                return Response(serializer.data)
            
            logger.error(f"Invalid data for organisation update: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.exception(f"Error updating organisation: {str(e)}")
            return Response(
                {"error": "An error occurred while updating the organisation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class OrganisationDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    @swagger_auto_schema(
        operation_description="Delete an existing organization",
        responses={
            204: 'Organisation deleted successfully',
            404: 'Organisation not found',
            500: 'Internal Server Error'
        },
        tags=['Organizations']
    )
    def delete(self, request, id):
        try:
            # Same 404-not-403 pattern as the update path — see the
            # BE-P2-02 comment there for the rationale.
            organisation = Organisations.objects.filter(
                pk=id, id=request.user.organisation_id,
            ).first()
            if organisation is None:
                return Response(
                    {"error": "Organisation not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            organisation_name = organisation.name
            organisation.delete()
            logger.info(f"Organisation {organisation_name} deleted successfully")
            return Response(status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
            logger.exception(f"Error deleting organisation: {str(e)}")
            return Response(
                {"error": "An error occurred while deleting the organisation"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

class OrganisationListPublicView(APIView):
    permission_classes = [IsAuthenticated]
    
    @swagger_auto_schema(
        operation_description="List all organizations (public)",
        responses={
            200: openapi.Response(
                "Success",
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'organisations': openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.Schema(type=openapi.TYPE_OBJECT)
                        )
                    }
                )
            ),
            500: 'Internal Server Error'
        },
        tags=['Organizations']
    )
    def get(self, request):
        try:
            # Scope to the caller's org (superusers see the whole
            # catalogue for site-admin tooling). Prior version returned
            # every org in the DB to any authenticated user — a
            # customer-enumeration leak on a multi-tenant OSS product.
            qs = Organisations.objects.all()
            if not request.user.is_superuser:
                user_org = getattr(request.user, 'organisation', None)
                qs = qs.filter(id=user_org.id) if user_org else qs.none()
            serializer = OrganisationSerializer(qs, many=True)
            return Response({"organisations": serializer.data})
        except Exception as e:
            logger.exception(f"Error listing organisations (public): {str(e)}")
            return Response(
                {"error": "An error occurred while listing organisations"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================================
# Onboarding Quickstart API
# ============================================================================

from .models import OnboardingStatus


def _serialize_onboarding(onboarding):
    """Shared response payload for GET + mutation endpoints.

    Extended 2026-08-30 (item #11) with ``computed_state`` and
    ``skipped_steps``. The wizard frontend keys off ``computed_state``
    directly — ``completed_steps`` is retained for backwards compat
    but is now a cache of computed truth rather than user attestation.
    """
    return {
        'current_step': onboarding.current_step,
        'current_step_display': onboarding.get_current_step_display(),
        'completed_steps': onboarding.completed_steps,
        'skipped_steps': onboarding.skipped_steps,
        'computed_state': onboarding.get_computed_state(),
        'progress_percentage': onboarding.progress_percentage,
        'is_completed': onboarding.is_completed,
        'is_skipped': onboarding.is_skipped,
        'completed_at': onboarding.completed_at,
        'skipped_at': onboarding.skipped_at,
        'onboarding_data': onboarding.onboarding_data,
        'available_steps': [
            {'code': code, 'name': name, 'skippable': code in OnboardingStatus.SKIPPABLE_STEPS}
            for code, name in OnboardingStatus.ONBOARDING_STEPS
        ],
    }


class OnboardingStatusView(APIView):
    """API for the onboarding quickstart wizard.

    Endpoints:
        GET    /api/organisation/onboarding/status/  — current state (refreshed from real DB)
        PUT    /api/organisation/onboarding/status/  — mutations (skip_step / store_data)

    Semantics reworked 2026-08-30 (item #11). Completion is computed
    from underlying DB state on every GET — there is no "mark this
    step complete" action anymore. The PUT endpoint takes an
    ``action`` field:

        - ``skip_step`` (with ``step``): mark an optional step
          (SCM / CI/CD) as user-dismissed
        - ``store_data`` (with ``data``): write to onboarding_data
          scratchpad (e.g. remembering which provider the user
          selected in the modal so we can resume)
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Get current onboarding status (refreshed from real DB state)",
        tags=['Onboarding'],
    )
    def get(self, request):
        # Defence-in-depth for E1-3: if the user has no organisation
        # (invitation-flow race, direct DB tweak, historical superuser
        # created before E1-4 fix), don't crash the endpoint with a
        # NOT NULL constraint violation. Return a 409 with an
        # actionable hint so the frontend can route to a "join or
        # create an organisation" flow rather than blowing up the
        # whole wizard.
        if request.user.organisation_id is None:
            return Response(
                {
                    'error': 'no_organisation',
                    'message': (
                        'Your user account is not attached to any organisation. '
                        'Ask an existing admin to invite you, or create a new '
                        'organisation via the signup flow.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        onboarding = OnboardingStatus.get_or_create_for_org(request.user.organisation)
        # Every GET recomputes — the wizard shows a live picture even
        # if the user completed a step from another tab / API / CLI.
        onboarding.refresh_and_advance()
        return Response(_serialize_onboarding(onboarding))

    @swagger_auto_schema(
        operation_description="Mutate onboarding state: skip an optional step or store scratchpad data",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['action'],
            properties={
                'action': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="One of: 'skip_step', 'store_data'",
                ),
                'step': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="Step name (required for skip_step). Must be in SKIPPABLE_STEPS.",
                ),
                'data': openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    description="Payload for store_data — merged into onboarding_data.",
                ),
            },
        ),
        tags=['Onboarding'],
    )
    def put(self, request):
        action = request.data.get('action')
        onboarding = OnboardingStatus.get_or_create_for_org(request.user.organisation)

        if action == 'skip_step':
            step = request.data.get('step')
            if not step:
                return Response(
                    {'error': "'step' is required when action='skip_step'"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                onboarding.skip_step(step)
            except ValueError as e:
                # Required step — spelled-out reason from the model.
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        elif action == 'store_data':
            data = request.data.get('data')
            if not isinstance(data, dict):
                return Response(
                    {'error': "'data' must be an object"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            onboarding.store_data(data)
            onboarding.refresh_and_advance()
        else:
            return Response(
                {'error': "'action' must be one of: 'skip_step', 'store_data'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_serialize_onboarding(onboarding))


class OnboardingSkipView(APIView):
    """Dismiss the wizard UI (does NOT mark onboarding complete).

    Semantic change 2026-08-30: previously this set ``current_step='completed'``
    and effectively marked the org as onboarded. Now it only hides
    the wizard — ``is_completed`` still reflects real state. That
    distinction matters for activation reporting (a dismissed org
    is not an activated org) and it lets us un-hide the wizard via
    :class:`OnboardingResumeView` without lying about progress.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Dismiss the onboarding wizard UI (reversible via /resume/)",
        tags=['Onboarding'],
    )
    def post(self, request):
        onboarding = OnboardingStatus.get_or_create_for_org(request.user.organisation)
        onboarding.dismiss()
        return Response({
            'success': True,
            'message': 'Onboarding wizard dismissed. Reopen via /resume/.',
            'is_skipped': True,
            'is_completed': onboarding.is_completed,
        })


class OnboardingResumeView(APIView):
    """Undo a dismiss — makes the wizard reappear."""
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Undo a previous dismiss — makes the wizard reappear.",
        tags=['Onboarding'],
    )
    def post(self, request):
        onboarding = OnboardingStatus.get_or_create_for_org(request.user.organisation)
        onboarding.resume()
        onboarding.refresh_and_advance()
        return Response({
            'success': True,
            'message': 'Onboarding wizard resumed.',
            'is_skipped': False,
            'current_step': onboarding.current_step,
        })


class OnboardingResetView(APIView):
    """Reset onboarding to start fresh (admin only)."""
    permission_classes = [IsAuthenticated, IsAdminRole]

    @swagger_auto_schema(
        operation_description="Reset onboarding to start fresh (admin only)",
        tags=['Onboarding'],
    )
    def post(self, request):
        onboarding = OnboardingStatus.get_or_create_for_org(request.user.organisation)
        onboarding.reset()
        return Response({
            'success': True,
            'message': 'Onboarding reset',
            'current_step': onboarding.current_step,
        })


class OrganisationCapabilitiesView(APIView):
    """
    Return the set of data-source capabilities the caller's org has
    at least one configured integration for. Used by the frontend to
    gate sidebar entries, dashboard widgets, and dropdown options so a
    logs-only user never sees dead UI for unconnected sources.

    Response shape::

        {
            "capabilities": ["logs", "traces"],
            "all_known": ["logs", "metrics", "code", "cicd", "traces"]
        }

    ``capabilities`` is derived live from ObservabilityIntegration
    rows, SCMBinding / CICDBinding presence, and IngestKey activity.
    No user configuration needed — the moment an integration is added
    or removed, this endpoint reflects it.
    """

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="List enabled data-source capabilities for the caller's org.",
        tags=['Organisation'],
        security=[{'Bearer': []}],
    )
    def get(self, request):
        organisation = getattr(request.user, 'organisation', None)
        if organisation is None:
            return Response(
                {'capabilities': [], 'all_known': []},
                status=200,
            )
        from Organisations.capability_registry import (
            ALL_CAPABILITIES, enabled_capabilities_for_org,
        )
        return Response({
            'capabilities': sorted(enabled_capabilities_for_org(organisation)),
            'all_known': sorted(ALL_CAPABILITIES),
        })