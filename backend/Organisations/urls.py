from django.urls import path
from . import views
from .alert_secret_view import AlertSecretView, AlertSecretRotateView
from .role_views import RoleListView
from .team_views import TeamDetailView, TeamListView

urlpatterns = [
    path('info/', views.OrganisationInfoView.as_view(), name='organisation-info'),
    # Q5-5: per-org alert-ingest secret (see alert_secret_view.py)
    path('alert-secret/', AlertSecretView.as_view(), name='organisation-alert-secret'),
    path('alert-secret/rotate/', AlertSecretRotateView.as_view(), name='organisation-alert-secret-rotate'),
    path('team/', views.OrganisationTeamView.as_view(), name='organisation-team'),
    path('roles/', RoleListView.as_view(), name='organisation-roles'),
    path('teams/', TeamListView.as_view(), name='organisation-teams'),
    path('teams/<int:pk>/', TeamDetailView.as_view(), name='organisation-team-detail'),
    path('member/<int:id>/', views.OrganisationMemberView.as_view(), name='organisation-member'),
    path('create/', views.OrganisationCreateView.as_view(), name='organisation-create'),
    path('update/<int:id>/', views.OrganisationUpdateView.as_view(), name='organisation-update'),
    path('delete/<int:id>/', views.OrganisationDeleteView.as_view(), name='organisation-delete'),
    path('list/', views.OrganisationListPublicView.as_view(), name='organisation-list'),
    path('capabilities/', views.OrganisationCapabilitiesView.as_view(), name='organisation-capabilities'),
    path('edition/', views.EditionView.as_view(), name='organisation-edition'),
    
    # Onboarding Quickstart endpoints
    path('onboarding/status/', views.OnboardingStatusView.as_view(), name='onboarding-status'),
    path('onboarding/skip/', views.OnboardingSkipView.as_view(), name='onboarding-skip'),
    path('onboarding/resume/', views.OnboardingResumeView.as_view(), name='onboarding-resume'),
    path('onboarding/reset/', views.OnboardingResetView.as_view(), name='onboarding-reset'),
]
