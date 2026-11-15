from django.urls import path

from .access.projects import ProjectAccessView
from .access.roles import RoleCreateView, RoleDetailView
from .audit_stream.views import AuditStreamDetailView, AuditStreamsView, AuditStreamTestView
from .saml.views import SamlAcsView, SamlConfigView, SamlMetadataView
from .scim import views as scim
from .scim.token_views import ScimTokenDetailView, ScimTokensView
from .views import LicenseView

urlpatterns = [
    path('license/', LicenseView.as_view(), name='ee-license'),
    path('roles/', RoleCreateView.as_view(), name='ee-roles'),
    path('roles/<int:pk>/', RoleDetailView.as_view(), name='ee-role-detail'),
    path('projects/<int:pk>/access/', ProjectAccessView.as_view(), name='ee-project-access'),
    path('saml/config/', SamlConfigView.as_view(), name='ee-saml-config'),
    path('saml/<uuid:sp_id>/metadata/', SamlMetadataView.as_view(), name='ee-saml-metadata'),
    path('saml/<uuid:sp_id>/acs/', SamlAcsView.as_view(), name='ee-saml-acs'),
    path('audit-streams/', AuditStreamsView.as_view(), name='ee-audit-streams'),
    path('audit-streams/<int:pk>/', AuditStreamDetailView.as_view(), name='ee-audit-stream'),
    path('audit-streams/<int:pk>/test/', AuditStreamTestView.as_view(), name='ee-audit-stream-test'),
    path('scim/tokens/', ScimTokensView.as_view(), name='ee-scim-tokens'),
    path('scim/tokens/<int:pk>/', ScimTokenDetailView.as_view(), name='ee-scim-token-detail'),
    path('scim/v2/ServiceProviderConfig', scim.ServiceProviderConfigView.as_view()),
    path('scim/v2/Schemas', scim.SchemasView.as_view()),
    path('scim/v2/Schemas/<str:schema_id>', scim.SchemasView.as_view()),
    path('scim/v2/ResourceTypes', scim.ResourceTypesView.as_view()),
    path('scim/v2/ResourceTypes/<str:type_id>', scim.ResourceTypesView.as_view()),
    path('scim/v2/Users', scim.UsersView.as_view(), name='ee-scim-users'),
    path('scim/v2/Users/<str:scim_id>', scim.UserDetailView.as_view(), name='ee-scim-user'),
    path('scim/v2/Groups', scim.GroupsView.as_view(), name='ee-scim-groups'),
    path('scim/v2/Groups/<str:scim_id>', scim.GroupDetailView.as_view(), name='ee-scim-group'),
]
