from django.urls import path
from . import views
from .alert_secret_view import AlertSecretView, AlertSecretRotateView

urlpatterns = [
    path('info/', views.OrganisationInfoView.as_view(), name='organisation-info'),
    # Q5-5: per-org alert-ingest secret (see alert_secret_view.py)
    path('alert-secret/', AlertSecretView.as_view(), name='organisation-alert-secret'),
    path('alert-secret/rotate/', AlertSecretRotateView.as_view(), name='organisation-alert-secret-rotate'),
    path('team/', views.OrganisationTeamView.as_view(), name='organisation-team'),
    path('member/<int:id>/', views.OrganisationMemberView.as_view(), name='organisation-member'),
    path('create/', views.OrganisationCreateView.as_view(), name='organisation-create'),
    path('update/<int:id>/', views.OrganisationUpdateView.as_view(), name='organisation-update'),
    path('delete/<int:id>/', views.OrganisationDeleteView.as_view(), name='organisation-delete'),
    path('list/', views.OrganisationListPublicView.as_view(), name='organisation-list'),
    path('capabilities/', views.OrganisationCapabilitiesView.as_view(), name='organisation-capabilities'),
    
    # Onboarding Quickstart endpoints
    path('onboarding/status/', views.OnboardingStatusView.as_view(), name='onboarding-status'),
    path('onboarding/skip/', views.OnboardingSkipView.as_view(), name='onboarding-skip'),
    path('onboarding/resume/', views.OnboardingResumeView.as_view(), name='onboarding-resume'),
    path('onboarding/reset/', views.OnboardingResetView.as_view(), name='onboarding-reset'),
]
