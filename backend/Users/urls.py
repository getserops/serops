from django.urls import path
from .views import AcceptInvitationView, AvatarView, DeleteAccountView, DemoLoginView, EmailVerification, ForgetPasswordView, InvitationsetPasswordView, LogoutView, ProfileAvatarView, ProfileView, RegisterView, RegistrationStatusView, LoginView, ResendVerificationLinkView, SetPasswordView, UpdatePasswordView
from .sso_views import SSOConfigView, SSOInitView, SSOCallbackView, SSOExchangeView


urlpatterns = [
    path('login',LoginView.as_view(),name="login"),
    path('demo-login', DemoLoginView.as_view(), name='demo-login'),
    path('registration-status', RegistrationStatusView.as_view(), name='registration-status'),
    path('register',RegisterView.as_view(),name="register"),
     path('logout',LogoutView.as_view(),name="logout"),
     path('profile',ProfileView.as_view(),name="profile"),
    path('password',UpdatePasswordView.as_view(),name="update-password"),
    path('resend',ResendVerificationLinkView.as_view(),name="resend-verification"),
    path('activate/<str:token>',EmailVerification.as_view(),name="activate"),
    path('accept/invitation/<str:token>',AcceptInvitationView.as_view(),name="accept-invitation"),
    path('password/forget',ForgetPasswordView.as_view(),name="forget-password"),
    path('password/set/<str:uidb64>/<str:token>',SetPasswordView.as_view(),name="set-password"),
    path('accept/password',InvitationsetPasswordView.as_view(),name="accept-password"),
    path('profile/upload-avatar/', ProfileAvatarView.as_view(), name='upload-profile-avatar'),
    path('avatar/<str:key>', AvatarView.as_view(), name='avatar'),
    path('account', DeleteAccountView.as_view(), name='delete-account'),
    
    # SSO Endpoints
    path('sso/config', SSOConfigView.as_view(), name='sso-config'),
    path('sso/init', SSOInitView.as_view(), name='sso-init'),
    path('sso/callback', SSOCallbackView.as_view(), name='sso-callback'),
    path('sso/exchange', SSOExchangeView.as_view(), name='sso-exchange'),
]