from django.urls import path

from .access.projects import ProjectAccessView
from .access.roles import RoleCreateView, RoleDetailView
from .views import LicenseView

urlpatterns = [
    path('license/', LicenseView.as_view(), name='ee-license'),
    path('roles/', RoleCreateView.as_view(), name='ee-roles'),
    path('roles/<int:pk>/', RoleDetailView.as_view(), name='ee-role-detail'),
    path('projects/<int:pk>/access/', ProjectAccessView.as_view(), name='ee-project-access'),
]
